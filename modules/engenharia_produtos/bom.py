"""Persistência e regras de versionamento da estrutura de materiais."""

from contextlib import contextmanager
from datetime import date
from pathlib import Path

from database import DATABASE_URL, conectar, q, transaction
from .bom_calculo import REGRAS, UNIDADES, calcular_necessidades, numero

CLASSIFICACOES = (
    "MATERIA_PRIMA", "EMBALAGEM", "INSUMO", "INTERMEDIARIO",
    "SUBPRODUTO", "COPRODUTO", "CONSUMIVEL_PROCESSO",
)
MIGRACOES = Path(__file__).resolve().parents[2] / "database"


def _executar(cursor, sql, params=()):
    cursor.execute(q(sql), params)
    return cursor


def _um(cursor, sql, params=()):
    registro = _executar(cursor, sql, params).fetchone()
    return dict(registro) if registro is not None else None


def _todos(cursor, sql, params=()):
    return [dict(registro) for registro in _executar(cursor, sql, params).fetchall()]


@contextmanager
def _escrita():
    conn = conectar()
    try:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("LOCK TABLE bom IN SHARE ROW EXCLUSIVE MODE")
        else:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute("BEGIN IMMEDIATE")
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrar(*, reverter=False):
    with transaction() as conn:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("LOCK TABLE skus IN ACCESS EXCLUSIVE MODE")
        else:
            cursor.execute("BEGIN IMMEDIATE")
        if DATABASE_URL:
            cursor.execute("SELECT to_regclass('bom') AS nome")
        else:
            cursor.execute("SELECT name AS nome FROM sqlite_master WHERE type = 'table' AND name = 'bom'")
        registro = cursor.fetchone()
        existe = registro is not None and registro["nome"] is not None
        if existe != reverter:
            return
        arquivo = "20261118_bom_down.sql" if reverter else "20261118_bom.sql"
        sql = (MIGRACOES / arquivo).read_text(encoding="utf-8")
        if not DATABASE_URL:
            sql = sql.split("-- Somente PostgreSQL", 1)[0]
            sql = sql.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY")
            sql = sql.replace("NUMERIC(18,6)", "TEXT")
            for campo in ("quantidade_base", "fator", "perda_prevista_percentual",
                          "rendimento_entrada", "rendimento_saida"):
                sql = sql.replace(f"{campo} >", f"CAST({campo} AS NUMERIC) >")
        for comando in sql.split(";"):
            if comando.strip():
                cursor.execute(comando)


def _inteiro(valor, nome):
    try:
        convertido = int(valor)
        if str(convertido) != str(valor).strip() or not 0 < convertido <= 2147483647:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError(f"{nome} inválido.") from None
    return convertido


def _data(valor):
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ValueError("Informe uma data de vigência válida.") from None


def _unidade(valor):
    unidades = {unidade.casefold(): unidade for unidade in UNIDADES}
    unidade = unidades.get((valor or "").strip().casefold())
    if unidade is None:
        raise ValueError("Unidade inválida.")
    return unidade


def _produto(cursor, produto_id, *, fabricavel=False):
    bloqueio = " FOR SHARE" if DATABASE_URL else ""
    produto = _um(cursor, "SELECT * FROM skus WHERE id = ?" + bloqueio, (produto_id,))
    if not produto or produto["ativo"] != "Sim" or produto["excluido_em"]:
        raise ValueError("Selecione um produto ativo.")
    if fabricavel and not produto["fabricavel"]:
        raise ValueError("Selecione um produto fabricável.")
    return produto


def definir_aquisicao(produto_id, fabricavel, compravel):
    if not (fabricavel or compravel):
        raise ValueError("Selecione pelo menos uma forma de aquisição.")
    with _escrita() as cursor:
        _produto(cursor, produto_id)
        if not fabricavel and _um(
            cursor, "SELECT id FROM bom WHERE produto_id = ? AND ativa LIMIT 1", (produto_id,)
        ):
            raise ValueError("Inative as BOMs publicadas antes de retirar a opção fabricável.")
        _executar(cursor, "UPDATE skus SET fabricavel = ?, compravel = ? WHERE id = ?",
                  (fabricavel, compravel, produto_id))


def _versao(cursor, bom_id):
    versao = _um(cursor, """
        SELECT b.*, s.nome AS produto FROM bom b JOIN skus s ON s.id = b.produto_id
        WHERE b.id = ?
    """, (bom_id,))
    if not versao:
        raise LookupError("Versão de BOM não encontrada.")
    return versao


def _rascunho(cursor, bom_id):
    versao = _versao(cursor, bom_id)
    if versao["status"] != "RASCUNHO":
        raise ValueError("Crie uma nova versão para alterar uma BOM publicada ou inativa.")
    _produto(cursor, versao["produto_id"], fabricavel=True)
    return versao


def _cabecalho(dados):
    descricao = dados.get("descricao", "").strip()
    if not descricao:
        raise ValueError("Informe a descrição da BOM.")
    inicio = _data(dados.get("data_inicio_vigencia"))
    fim = _data(dados["data_fim_vigencia"]) if dados.get("data_fim_vigencia") else None
    if fim and fim < inicio:
        raise ValueError("O fim da vigência deve ocorrer no início ou depois dele.")
    campos = ("rendimento_entrada", "rendimento_saida",
              "rendimento_unidade_entrada", "rendimento_unidade_saida")
    rendimento = (None,) * 4
    if any(dados.get(campo) for campo in campos):
        rendimento = (
            str(numero(dados.get(campos[0]), "Entrada do rendimento")),
            str(numero(dados.get(campos[1]), "Saída do rendimento")),
            _unidade(dados.get(campos[2])),
            _unidade(dados.get(campos[3])),
        )
    return descricao, inicio.isoformat(), fim.isoformat() if fim else None, dados.get("observacoes", "").strip(), *rendimento


CAMPOS_ITEM = (
    "componente_produto_id", "componente_insumo_id", "sequencia", "classificacao",
    "quantidade_base", "unidade", "regra_calculo", "fator",
    "perda_prevista_percentual", "etapa_id", "observacoes", "ativo",
)


def criar_versao(produto_id, dados, usuario_id, origem_id=None, clonar=False):
    cabecalho = _cabecalho(dados)
    with _escrita() as cursor:
        _produto(cursor, produto_id, fabricavel=True)
        if clonar and origem_id is None:
            raise ValueError("Selecione a versão de origem.")
        if origem_id is not None and _versao(cursor, origem_id)["produto_id"] != produto_id:
            raise ValueError("A versão de origem pertence a outro produto.")
        ultima = _um(cursor, "SELECT MAX(numero_versao) AS numero FROM bom WHERE produto_id = ?",
                     (produto_id,))
        nova = _um(cursor, """
            INSERT INTO bom (produto_id, numero_versao, descricao, data_inicio_vigencia,
                data_fim_vigencia, observacoes, rendimento_entrada, rendimento_saida,
                rendimento_unidade_entrada, rendimento_unidade_saida, criado_por, atualizado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id
        """, (produto_id, (ultima["numero"] or 0) + 1, *cabecalho, usuario_id, usuario_id))
        if clonar:
            _validar_componentes(cursor, origem_id)
            campos = ", ".join(CAMPOS_ITEM)
            _executar(cursor, f"INSERT INTO bom_item (bom_id, {campos}) "
                      f"SELECT ?, {campos} FROM bom_item WHERE bom_id = ?", (nova["id"], origem_id))
            _validar_ciclos(cursor, nova["id"])
        return nova["id"]


def atualizar_cabecalho(bom_id, dados, usuario_id):
    cabecalho = _cabecalho(dados)
    with _escrita() as cursor:
        _rascunho(cursor, bom_id)
        _executar(cursor, """
            UPDATE bom SET descricao = ?, data_inicio_vigencia = ?, data_fim_vigencia = ?,
                observacoes = ?, rendimento_entrada = ?, rendimento_saida = ?,
                rendimento_unidade_entrada = ?, rendimento_unidade_saida = ?,
                atualizado_em = CURRENT_TIMESTAMP, atualizado_por = ? WHERE id = ?
        """, (*cabecalho, usuario_id, bom_id))


def _validar_ciclos(cursor, bom_id):
    candidatas = _todos(cursor, """
        SELECT b.produto_id, i.componente_produto_id
        FROM bom b JOIN bom_item i ON i.bom_id = b.id
        WHERE (b.id = ? OR b.status <> 'INATIVA') AND i.ativo AND i.componente_produto_id IS NOT NULL
    """, (bom_id,))
    grafo = {}
    for aresta in candidatas:
        grafo.setdefault(aresta["produto_id"], set()).add(aresta["componente_produto_id"])
    origem = _versao(cursor, bom_id)["produto_id"]
    pendentes = list(grafo.get(origem, ()))
    visitados = set()
    while pendentes:
        destino = pendentes.pop()
        if destino == origem:
            raise ValueError("O componente gera um ciclo na estrutura de fabricação.")
        if destino not in visitados:
            visitados.add(destino)
            pendentes.extend(grafo.get(destino, ()))


def _componente(cursor, produto_id, insumo_id):
    if produto_id:
        return _produto(cursor, produto_id)
    bloqueio = " FOR SHARE" if DATABASE_URL else ""
    insumo = _um(cursor, "SELECT * FROM almoxarifado_insumos WHERE id = ?" + bloqueio, (insumo_id,))
    if not insumo or insumo["ativo"] != "Sim":
        raise ValueError("Selecione um insumo ativo.")
    return insumo


def salvar_item(bom_id, dados, usuario_id, item_id=None):
    tipo, _, identificador = (dados.get("componente") or "").partition(":")
    componente_id = _inteiro(identificador, "Componente")
    if tipo not in ("produto", "insumo"):
        raise ValueError("Selecione um componente válido.")
    produto_id = componente_id if tipo == "produto" else None
    insumo_id = componente_id if tipo == "insumo" else None
    etapa = _inteiro(dados["etapa_id"], "Etapa") if dados.get("etapa_id") else None
    sequencia = _inteiro(dados.get("sequencia"), "Sequência")
    classificacao = dados.get("classificacao", "").strip()
    regra = dados.get("regra_calculo")
    if regra not in REGRAS or not classificacao:
        raise ValueError("Informe uma classificação e uma regra válida.")
    valores = (
        produto_id, insumo_id, sequencia, classificacao,
        str(numero(dados.get("quantidade_base"), "Quantidade base")), _unidade(dados.get("unidade")),
        regra, str(numero(dados.get("fator"), "Fator")),
        str(numero(dados.get("perda_prevista_percentual"), "Perda", aceita_zero=True)),
        etapa, dados.get("observacoes", "").strip(), dados.get("ativo") == "1",
    )
    with _escrita() as cursor:
        versao = _rascunho(cursor, bom_id)
        _componente(cursor, produto_id, insumo_id)
        if produto_id == versao["produto_id"]:
            raise ValueError("Um produto não pode ser seu próprio componente.")
        if etapa and not _um(cursor, "SELECT id FROM etapas_catalogo WHERE id = ? AND ativo = 1", (etapa,)):
            raise ValueError("Etapa inválida.")
        if _um(cursor, "SELECT id FROM bom_item WHERE bom_id = ? AND sequencia = ? AND id <> ?",
               (bom_id, sequencia, item_id or 0)):
            raise ValueError("A sequência já está em uso nesta versão.")
        if item_id is None:
            campos = ", ".join(CAMPOS_ITEM)
            marcadores = ", ".join("?" for _ in CAMPOS_ITEM)
            _executar(cursor, f"INSERT INTO bom_item (bom_id, {campos}) VALUES (?, {marcadores})",
                      (bom_id, *valores))
        else:
            atribuicoes = ", ".join(f"{campo} = ?" for campo in CAMPOS_ITEM)
            alterado = _executar(cursor, f"UPDATE bom_item SET {atribuicoes}, "
                                 "atualizado_em = CURRENT_TIMESTAMP WHERE bom_id = ? AND id = ?",
                                 (*valores, bom_id, item_id))
            if alterado.rowcount != 1:
                raise LookupError("Componente não encontrado.")
        _validar_ciclos(cursor, bom_id)
        _auditar(cursor, bom_id, usuario_id)


def _auditar(cursor, bom_id, usuario_id):
    _executar(cursor, "UPDATE bom SET atualizado_em = CURRENT_TIMESTAMP, atualizado_por = ? WHERE id = ?",
              (usuario_id, bom_id))


def remover_item(bom_id, item_id, usuario_id):
    with _escrita() as cursor:
        _rascunho(cursor, bom_id)
        if _executar(cursor, "DELETE FROM bom_item WHERE bom_id = ? AND id = ?", (bom_id, item_id)).rowcount != 1:
            raise LookupError("Componente não encontrado.")
        _auditar(cursor, bom_id, usuario_id)


def _validar_componentes(cursor, bom_id):
    itens = _todos(cursor, "SELECT * FROM bom_item WHERE bom_id = ? AND ativo", (bom_id,))
    for item in itens:
        _componente(cursor, item["componente_produto_id"], item["componente_insumo_id"])


def publicar(bom_id, usuario_id):
    with _escrita() as cursor:
        versao = _rascunho(cursor, bom_id)
        _validar_componentes(cursor, bom_id)
        _validar_ciclos(cursor, bom_id)
        inicio = versao["data_inicio_vigencia"]
        fim = versao["data_fim_vigencia"]
        if _um(cursor, """
            SELECT id FROM bom WHERE produto_id = ? AND id <> ? AND status <> 'RASCUNHO'
                AND (data_fim_vigencia IS NULL OR data_fim_vigencia >= ?)
                AND data_inicio_vigencia <= ?
            LIMIT 1
        """, (versao["produto_id"], bom_id, inicio, fim or date.max.isoformat())):
            raise ValueError("A vigência se sobrepõe à de outra versão. Ajuste as vigências.")
        _executar(cursor, "UPDATE bom SET status = 'PUBLICADA', ativa = TRUE WHERE id = ?", (bom_id,))
        _auditar(cursor, bom_id, usuario_id)


def inativar(bom_id, ultimo_dia, usuario_id):
    fim = _data(ultimo_dia)
    with _escrita() as cursor:
        versao = _versao(cursor, bom_id)
        if not versao["ativa"]:
            raise ValueError("Selecione uma BOM publicada.")
        inicio = _data(versao["data_inicio_vigencia"])
        fim_atual = versao["data_fim_vigencia"]
        if fim < inicio or (fim_atual and fim > _data(fim_atual)):
            raise ValueError("A data final deve estar dentro da vigência original.")
        _executar(cursor, "UPDATE bom SET status = 'INATIVA', ativa = FALSE, data_fim_vigencia = ? WHERE id = ?",
                  (fim.isoformat(), bom_id))
        _auditar(cursor, bom_id, usuario_id)


def listar():
    with transaction() as conn:
        return _todos(conn.cursor(), """
            SELECT b.*, s.nome AS produto,
                (SELECT COUNT(*) FROM bom_item i WHERE i.bom_id = b.id AND i.ativo) AS quantidade_itens
            FROM bom b JOIN skus s ON s.id = b.produto_id
            ORDER BY s.nome, b.numero_versao DESC
        """)


def detalhar(bom_id):
    with transaction() as conn:
        cursor = conn.cursor()
        versao = _versao(cursor, bom_id)
        versao["itens"] = _todos(cursor, """
            SELECT i.*, COALESCE(s.nome, a.descricao) AS componente, p.nome AS etapa
            FROM bom_item i LEFT JOIN skus s ON s.id = i.componente_produto_id
            LEFT JOIN almoxarifado_insumos a ON a.id = i.componente_insumo_id
            LEFT JOIN etapas_catalogo p ON p.id = i.etapa_id
            WHERE i.bom_id = ? ORDER BY i.sequencia
        """, (bom_id,))
        return versao


def opcoes():
    with transaction() as conn:
        cursor = conn.cursor()
        return {
            "produtos": _todos(cursor, """
                SELECT id, nome, fabricavel, compravel FROM skus
                WHERE ativo = 'Sim' AND excluido_em IS NULL ORDER BY nome
            """),
            "insumos": _todos(cursor, """
                SELECT id, descricao FROM almoxarifado_insumos WHERE ativo = 'Sim' ORDER BY descricao
            """),
            "etapas": _todos(cursor, "SELECT id, nome FROM etapas_catalogo WHERE ativo = 1 ORDER BY nome"),
            "unidades": UNIDADES,
            "regras": REGRAS,
            "classificacoes": CLASSIFICACOES,
        }
