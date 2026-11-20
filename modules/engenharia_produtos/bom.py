"""Persistência e regras de versionamento da estrutura de materiais."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path

from database import DATABASE_URL, conectar, q, transaction
from .bom_calculo import REGRAS, UNIDADES, calcular_necessidades, explodir, numero
from .repositories import registrar_historico_cursor

ESTADO_PRODUTIVO = """
    CASE
        WHEN EXISTS (SELECT 1 FROM bom a WHERE a.produto_id = s.id AND a.status = 'ATIVA')
            THEN 'BOM_ATIVA'
        WHEN EXISTS (SELECT 1 FROM bom a WHERE a.produto_id = s.id AND a.status IN ('RASCUNHO', 'PUBLICADA'))
            THEN 'EM_CONFIGURACAO'
        ELSE 'LEGADO'
    END AS estado_produtivo
"""

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


def _presente(cursor, nome):
    if DATABASE_URL:
        return _um(cursor, "SELECT to_regclass(?) AS objeto", (nome,))["objeto"] is not None
    return _um(cursor, "SELECT name FROM sqlite_master WHERE name = ?", (nome,)) is not None


def _script(cursor, prefixo, reverter):
    motor = "" if DATABASE_URL else "_sqlite"
    operacao = "_rollback" if reverter else ""
    sql = (MIGRACOES / f"{prefixo}{motor}{operacao}.sql").read_text(encoding="utf-8").strip()
    sql = sql.removeprefix("PRAGMA foreign_keys = OFF;").strip()
    sql = sql.removeprefix("BEGIN;").removesuffix("COMMIT;").strip()
    if DATABASE_URL:
        cursor.execute(sql)
    else:
        comando = ""
        for linha in sql.splitlines(keepends=True):
            comando += linha
            if sqlite3.complete_statement(comando):
                cursor.execute(comando)
                comando = ""
        if comando.strip():
            raise RuntimeError("Migration SQLite contém SQL incompleto.")


def migrar(*, reverter=False, somente_producao=False):
    with transaction() as conn:
        cursor = conn.cursor()
        if not DATABASE_URL:
            cursor.execute("PRAGMA foreign_keys = OFF")
            cursor.execute("BEGIN IMMEDIATE")
        if not _presente(cursor, "bom"):
            if reverter or somente_producao:
                return
            if DATABASE_URL:
                cursor.execute("LOCK TABLE skus IN ACCESS EXCLUSIVE MODE")
            if not _presente(cursor, "bom"):
                _script(cursor, "20261118_bom", False)

        tem_producao = _presente(cursor, "uq_bom_ativa_produto")
        if tem_producao == reverter:
            if DATABASE_URL:
                cursor.execute("LOCK TABLE bom IN ACCESS EXCLUSIVE MODE")
            if _presente(cursor, "uq_bom_ativa_produto") == reverter:
                _script(cursor, "20261120_bom_producao", reverter)
        if reverter and not somente_producao:
            _script(cursor, "20261118_bom", True)
        elif not DATABASE_URL and cursor.execute("PRAGMA foreign_key_check(bom_item)").fetchone():
            raise RuntimeError("A migration da BOM encontrou itens sem versão correspondente.")


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


def _produto(cursor, produto_id, *, fabricavel=False, bloquear=True):
    bloqueio = " FOR SHARE" if DATABASE_URL and bloquear else ""
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
            cursor, "SELECT id FROM bom WHERE produto_id = ? AND status = 'ATIVA' LIMIT 1", (produto_id,)
        ):
            raise ValueError("Inative a BOM ativa antes de retirar a opção fabricável.")
        _executar(cursor, "UPDATE skus SET fabricavel = ?, compravel = ? WHERE id = ?",
                  (fabricavel, compravel, produto_id))


def _versao(cursor, bom_id):
    versao = _um(cursor, f"""
        SELECT b.*, s.nome AS produto, s.unidade_venda AS unidade_producao,
            {ESTADO_PRODUTIVO}
        FROM bom b JOIN skus s ON s.id = b.produto_id
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


def _componente(cursor, produto_id, insumo_id, *, bloquear=True):
    if produto_id:
        return _produto(cursor, produto_id, bloquear=bloquear)
    bloqueio = " FOR SHARE" if DATABASE_URL and bloquear else ""
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


def _hoje():
    return datetime.now(ZoneInfo("America/Manaus")).date()


def _vigente(versao, hoje):
    return (
        _data(versao["data_inicio_vigencia"]) <= hoje
        and (not versao["data_fim_vigencia"] or hoje <= _data(versao["data_fim_vigencia"]))
    )


def _mudar_status(cursor, bom_id, status, usuario_id):
    _executar(cursor, """
        UPDATE bom SET status = ?, atualizado_em = CURRENT_TIMESTAMP, atualizado_por = ? WHERE id = ?
    """, (status, usuario_id, bom_id))


def publicar(bom_id, usuario_id):
    with _escrita() as cursor:
        versao = _rascunho(cursor, bom_id)
        _validar_componentes(cursor, bom_id)
        _validar_ciclos(cursor, bom_id)
        _cabecalho(versao)
        calcular_necessidades(versao["produto_id"], _carregar_itens(cursor, versao), 1)
        _mudar_status(cursor, bom_id, "PUBLICADA", usuario_id)


def _ativa(cursor, produto_id):
    return _um(cursor, "SELECT * FROM bom WHERE produto_id = ? AND status = 'ATIVA'", (produto_id,))


def _auditar_transicao(cursor, versao, anterior, acao, usuario_id, usuario_nome, origem, motivo):
    def chave(dados):
        return {"id": dados["id"], "numero": dados["numero_versao"]} if dados else None

    registrar_historico_cursor(
        cursor, "bom_producao", versao["produto_id"], acao, usuario_id, usuario_nome,
        {"versao": chave(anterior)},
        {"versao": chave(versao), "origem": origem, "motivo": (motivo or "").strip()},
    )


def ativar(bom_id, usuario_id, *, ativa_esperada, usuario_nome=None, origem="ENGENHARIA", motivo=None):
    with _escrita() as cursor:
        versao = _versao(cursor, bom_id)
        if versao["status"] != "PUBLICADA":
            raise ValueError("Apenas uma BOM publicada pode ser ativada.")
        produto_id = versao["produto_id"]
        _produto(cursor, produto_id, fabricavel=True)
        anterior = _ativa(cursor, produto_id)
        if (anterior["id"] if anterior else None) != ativa_esperada:
            raise ValueError("A versão ativa mudou. Atualize a página e revise a substituição.")
        if not _vigente(versao, _hoje()):
            raise ValueError("A versão está fora da vigência.")
        _cabecalho(versao)
        _validar_ciclos(cursor, bom_id)
        _simular(cursor, _carregar_itens(cursor, versao), 1, validar=True)
        if anterior:
            _mudar_status(cursor, anterior["id"], "INATIVA", usuario_id)
        _mudar_status(cursor, bom_id, "ATIVA", usuario_id)
        _auditar_transicao(cursor, versao, anterior, "ativar", usuario_id, usuario_nome, origem, motivo)


def inativar(bom_id, usuario_id, *, usuario_nome=None, origem="ENGENHARIA", motivo=None):
    with _escrita() as cursor:
        versao = _versao(cursor, bom_id)
        if versao["status"] not in ("PUBLICADA", "ATIVA"):
            raise ValueError("Selecione uma BOM publicada ou ativa.")
        _mudar_status(cursor, bom_id, "INATIVA", usuario_id)
        _auditar_transicao(cursor, versao, versao, "inativar", usuario_id, usuario_nome, origem, motivo)


def estado_produtivo(produto_id):
    with transaction() as conn:
        registro = _um(conn.cursor(), f"SELECT {ESTADO_PRODUTIVO} FROM skus s WHERE s.id = ?", (produto_id,))
        if not registro:
            raise LookupError("Produto não encontrado.")
        return registro["estado_produtivo"]


def listar():
    with transaction() as conn:
        return _todos(conn.cursor(), f"""
            SELECT b.*, s.nome AS produto,
                {ESTADO_PRODUTIVO},
                (SELECT COUNT(*) FROM bom_item i WHERE i.bom_id = b.id AND i.ativo) AS quantidade_itens
            FROM bom b JOIN skus s ON s.id = b.produto_id
            ORDER BY s.nome, b.numero_versao DESC
        """)


def _carregar_itens(cursor, versao):
    return {**versao, "itens": _todos(cursor, """
        SELECT i.*, COALESCE(s.nome, a.descricao) AS componente, p.nome AS etapa
        FROM bom_item i LEFT JOIN skus s ON s.id = i.componente_produto_id
        LEFT JOIN almoxarifado_insumos a ON a.id = i.componente_insumo_id
        LEFT JOIN etapas_catalogo p ON p.id = i.etapa_id
        WHERE i.bom_id = ? ORDER BY i.sequencia
    """, (versao["id"],))}


def _simular(cursor, versao, quantidade, *, validar=False):
    hoje = _hoje()
    resolvidas = {}

    def verificar(atual):
        if validar:
            _produto(cursor, atual["produto_id"], fabricavel=True)
            _cabecalho(atual)
        if not any(item["ativo"] for item in atual["itens"]):
            raise ValueError(f"A BOM de {atual['produto']} não possui componentes ativos.")

    def resolver(item):
        chave = (item["componente_produto_id"], item["componente_insumo_id"])
        if chave not in resolvidas:
            resolvidas[chave] = resolver_componente(*chave)
        return resolvidas[chave]

    def resolver_componente(produto_id, insumo_id):
        componente = _componente(cursor, produto_id, insumo_id, bloquear=validar)
        if produto_id is None:
            return None
        if not componente["fabricavel"]:
            if not componente["compravel"]:
                raise ValueError(f"{componente['nome']} não possui forma de aquisição válida.")
            return None
        ativa = _ativa(cursor, componente["id"])
        if not ativa or not _vigente(ativa, hoje):
            raise ValueError(f"Estrutura produtiva incompleta: {componente['nome']} não possui BOM ativa vigente.")
        filha = _versao(cursor, ativa["id"])
        filha["unidade_producao"] = _unidade(filha["unidade_producao"])
        return _carregar_itens(cursor, filha)

    return explodir(versao, quantidade, resolver, verificar)


def simular(bom_id, quantidade):
    with transaction() as conn:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        else:
            cursor.execute("BEGIN")
        versao = _versao(cursor, bom_id)
        if versao["status"] == "INATIVA":
            raise ValueError("Versões inativas são apenas históricas.")
        versao = _carregar_itens(cursor, versao)
        diretos = calcular_necessidades(versao["produto_id"], versao, quantidade)
        try:
            return {"diretos": diretos, **_simular(cursor, versao, quantidade)}
        except ValueError as erro:
            return {"diretos": diretos, "erro": str(erro)}


def detalhar(bom_id):
    with transaction() as conn:
        cursor = conn.cursor()
        versao = _carregar_itens(cursor, _versao(cursor, bom_id))
        ativa = _ativa(cursor, versao["produto_id"])
        versao["ativa_producao"] = ativa
        versao["pode_ativar"] = versao["status"] == "PUBLICADA" and _vigente(versao, _hoje())
        versao["historico"] = _todos(cursor, """
            SELECT * FROM engenharia_produtos_historico
            WHERE entidade = 'bom_producao' AND entidade_id = ?
            ORDER BY criado_em DESC, id DESC
        """, (versao["produto_id"],))
        for evento in versao["historico"]:
            evento["antes"] = json.loads(evento["valores_anteriores"] or "{}")
            evento["depois"] = json.loads(evento["valores_novos"] or "{}")
        return versao


def opcoes():
    with transaction() as conn:
        cursor = conn.cursor()
        return {
            "produtos": _todos(cursor, f"""
                SELECT id, nome, fabricavel, compravel, {ESTADO_PRODUTIVO} FROM skus s
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
