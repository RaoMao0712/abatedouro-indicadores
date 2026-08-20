"""Seleção, fotografia e persistência do relatório executivo de PNC."""

from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

from database import DATABASE_URL, conectar, q, transaction
from modules.qualidade.liberacoes import PENDENTE, TIPO_LEGADO, garantir_schema

from .consolidado_estoque import (
    ROTULOS_SITUACOES, _catalogo, _classificar_posicao, _grupos_obrigatorios,
    _inteiro, _linhas_legado, _situacao_pos_marco,
)
from .estoque_service import FUSO_MANAUS, criar_tabelas_estoque_confiavel


SITUACOES_RELATORIO = (
    "nao_conforme_bloqueado", "reprocessamento", "aguardando_liberacao",
)
UNIDADES_ROTULOS = {
    "caixas": "Caixas", "bandejas": "Bandejas", "peso_kg": "Peso",
    "galinhas": "Galinhas", "pacotes": "Pacotes",
}


def _agora():
    return datetime.now(FUSO_MANAUS)


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(valor):
    return hashlib.sha256(_json(valor).encode("utf-8")).hexdigest()


def _caracteristica(linha):
    motivo = str(linha.get("motivo") or "").strip()
    descricao = str(linha.get("descricao") or "").strip()
    if motivo.casefold() == "outro" and descricao:
        return descricao
    return motivo or descricao or "Característica não informada"


def criar_tabelas_relatorios_nc():
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS relatorios_nc_verificacao (
            id {id_type}, numero TEXT UNIQUE NOT NULL, emitido_em {timestamp_type} NOT NULL,
            usuario TEXT NOT NULL, perfil TEXT NOT NULL, filtros_json TEXT NOT NULL,
            selecao_json TEXT NOT NULL, snapshot_json TEXT NOT NULL, totais_json TEXT NOT NULL,
            integridade_hash TEXT NOT NULL, resultado TEXT NOT NULL
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS relatorios_nc_verificacao_eventos (
            id {id_type}, relatorio_id INTEGER NOT NULL, acao TEXT NOT NULL,
            usuario TEXT NOT NULL, perfil TEXT NOT NULL, detalhes_json TEXT NOT NULL,
            criado_em {timestamp_type} NOT NULL
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relatorios_nc_emissao ON relatorios_nc_verificacao(emitido_em)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_relatorios_nc_eventos ON relatorios_nc_verificacao_eventos(relatorio_id)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def garantir_schema_relatorio_nc():
    criar_tabelas_estoque_confiavel()
    garantir_schema(criar_local=False)
    criar_tabelas_relatorios_nc()


def _linhas_pos_marco(cursor):
    cursor.execute(q("""SELECT nc.id AS registro_id,nc.motivo,nc.descricao,
            cx.sku,cx.apresentacao,cx.unidade_estoque,cx.galinhas_por_pacote,
            cx.condicao,cx.disponibilidade,cx.status,cx.estoque_operacional,
            cx.quantidade_bandejas,cx.peso_liquido,cx.quantidade_pacotes,
            cx.quantidade_galinhas,
            CASE WHEN EXISTS (
                SELECT 1 FROM pa_nao_conforme_solicitacoes s
                WHERE s.pa_nao_conforme_id=nc.id AND s.status=?
            ) THEN 1 ELSE 0 END AS liberacao_pendente
        FROM pa_nao_conformes nc JOIN pa_caixas cx ON cx.id=nc.caixa_id
        WHERE nc.tipo_registro<>?
          AND UPPER(COALESCE(nc.status,'')) NOT IN ('CANCELADO','CANCELADA','ESTORNADO')
          AND COALESCE(cx.estoque_operacional,0)=1
          AND UPPER(COALESCE(cx.status,'')) NOT IN ('CANCELADO','CANCELADA','ESTORNADO')
          AND UPPER(COALESCE(cx.disponibilidade,'')) NOT IN
              ('TRANSFERIDO','EXPEDIDO','DESCARTADO','DEVOLVIDO','CANCELADO','ESTORNADO')
        ORDER BY nc.id"""), (PENDENTE, TIPO_LEGADO))
    return [dict(item) for item in cursor.fetchall()]


def _item_pos_marco(grupos, catalogo, linha):
    grupo = _classificar_posicao(grupos, catalogo, linha)
    situacao = _situacao_pos_marco(linha)
    if situacao not in SITUACOES_RELATORIO:
        return None
    pacote = str(linha.get("unidade_estoque") or "").upper() == "PACOTE"
    if pacote:
        pacotes = max(0, _inteiro(linha.get("quantidade_pacotes")))
        fator = max(0, _inteiro(linha.get("galinhas_por_pacote")))
        galinhas = max(0, _inteiro(linha.get("quantidade_galinhas"))) or pacotes * fator
        quantidades = {"galinhas": galinhas, "pacotes": pacotes}
    else:
        bandejas = max(0, _inteiro(linha.get("quantidade_bandejas")))
        peso = max(Decimal("0"), Decimal(str(linha.get("peso_liquido") or 0)))
        quantidades = {"caixas": 1, "bandejas": bandejas, "peso_kg": peso}
    if not any(quantidades.values()):
        return None
    return {
        "chave": f"caixa:{linha['registro_id']}", "registro_id": linha["registro_id"],
        "origem_tipo": "CAIXA_RASTREADA", "produto": grupo["produto"],
        "apresentacao": grupo["apresentacao"], "grupo_chave": grupo["chave"],
        "unidades": grupo["unidades"], "caracteristica": _caracteristica(linha),
        "situacao": situacao, "situacao_rotulo": ROTULOS_SITUACOES[situacao],
        "quantidades": quantidades,
    }


def _itens_legado(grupos, linhas):
    itens = []
    grupo = grupos["galinha_cortada"]
    for linha in linhas:
        if str(linha.get("status") or "").upper() in {"CANCELADO", "CANCELADA", "ESTORNADO"}:
            continue
        pendente_g = max(0, _inteiro(linha.get("saldo_pendente_g")))
        bloqueado_g = max(0, _inteiro(linha.get("saldo_bloqueado_g")) - pendente_g)
        pendente_caixas = min(max(0, _inteiro(linha.get("caixas_bloqueadas"))),
                              max(0, _inteiro(linha.get("pendente_caixas"))))
        pendente_bandejas = min(max(0, _inteiro(linha.get("bandejas_bloqueadas"))),
                                max(0, _inteiro(linha.get("pendente_bandejas"))))
        bloqueado_caixas = max(0, _inteiro(linha.get("caixas_bloqueadas")) - pendente_caixas)
        bloqueado_bandejas = max(0, _inteiro(linha.get("bandejas_bloqueadas")) - pendente_bandejas)
        if str(linha.get("condicao_inicial") or "").upper() == "CONFORME_AGUARDANDO_LIBERACAO":
            pendente_g += bloqueado_g
            pendente_caixas += bloqueado_caixas
            pendente_bandejas += bloqueado_bandejas
            bloqueado_g = bloqueado_caixas = bloqueado_bandejas = 0
        partes = []
        situacao_bloqueado = (
            "reprocessamento" if str(linha.get("status") or "").upper() == "REPROCESSO"
            else "nao_conforme_bloqueado"
        )
        partes.append((situacao_bloqueado, bloqueado_caixas, bloqueado_bandejas, bloqueado_g))
        partes.append(("aguardando_liberacao", pendente_caixas, pendente_bandejas, pendente_g))
        for situacao, caixas, bandejas, peso_g in partes:
            quantidades = {
                "caixas": caixas, "bandejas": bandejas,
                "peso_kg": Decimal(peso_g) / Decimal(1000),
            }
            if not any(quantidades.values()):
                continue
            itens.append({
                "chave": f"legado:{linha['id']}:{situacao}", "registro_id": linha["id"],
                "origem_tipo": TIPO_LEGADO, "produto": grupo["produto"],
                "apresentacao": grupo["apresentacao"], "grupo_chave": grupo["chave"],
                "unidades": grupo["unidades"], "caracteristica": _caracteristica(linha),
                "situacao": situacao, "situacao_rotulo": ROTULOS_SITUACOES[situacao],
                "quantidades": quantidades,
            })
    return itens


def _serializavel(item):
    copia = dict(item)
    copia["quantidades"] = {k: str(v) if isinstance(v, Decimal) else v
                              for k, v in item["quantidades"].items()}
    return copia


def _itens_atuais(cursor):
    catalogo = _catalogo(cursor)
    grupos = _grupos_obrigatorios(catalogo)
    itens = [
        item for linha in _linhas_pos_marco(cursor)
        if (item := _item_pos_marco(grupos, catalogo, linha))
    ]
    itens.extend(_itens_legado(grupos, _linhas_legado(cursor)))
    return itens


def _normalizar_filtros(filtros=None):
    filtros = filtros or {}
    return {nome: str(filtros.get(nome) or "").strip() for nome in (
        "produto", "apresentacao", "caracteristica", "situacao", "busca",
    )}


def listar_saldos_nc(filtros=None):
    garantir_schema_relatorio_nc()
    filtros = _normalizar_filtros(filtros)
    conn = conectar()
    try:
        itens = _itens_atuais(conn.cursor())
    finally:
        conn.close()
    def aceita(item):
        exatos = ("produto", "apresentacao", "caracteristica", "situacao")
        if any(filtros[n] and str(item[n]).casefold() != filtros[n].casefold() for n in exatos):
            return False
        busca = filtros["busca"].casefold()
        return not busca or busca in f"{item['caracteristica']} {item['produto']} {item['apresentacao']}".casefold()
    filtrados = [item for item in itens if aceita(item)]
    opcoes = {
        campo: sorted({str(item[campo]) for item in itens}, key=str.casefold)
        for campo in ("produto", "apresentacao", "caracteristica", "situacao")
    }
    return filtrados, opcoes, filtros


def consolidar_selecao(chaves, *, cursor=None):
    chaves = sorted(set(str(item) for item in (chaves or []) if str(item).strip()))
    if not chaves:
        raise ValueError("Selecione ao menos um saldo não conforme.")
    proprio = cursor is None
    conn = conectar() if proprio else None
    try:
        cursor = cursor or conn.cursor()
        por_chave = {item["chave"]: item for item in _itens_atuais(cursor)}
        faltantes = [chave for chave in chaves if chave not in por_chave]
        if faltantes:
            raise ValueError("Um ou mais saldos foram alterados. Atualize a conferência antes de gerar.")
        selecionados = [por_chave[chave] for chave in chaves]
        agrupados = OrderedDict()
        for item in selecionados:
            chave_grupo = (item["grupo_chave"], item["produto"], item["apresentacao"])
            secao = agrupados.setdefault(chave_grupo, {
                "grupo_chave": item["grupo_chave"], "produto": item["produto"],
                "apresentacao": item["apresentacao"], "unidades": item["unidades"],
                "linhas": OrderedDict(),
            })
            linha = secao["linhas"].setdefault(item["caracteristica"], {
                "caracteristica": item["caracteristica"],
                "quantidades": {u: Decimal("0") if u == "peso_kg" else 0 for u in item["unidades"]},
            })
            for unidade in item["unidades"]:
                linha["quantidades"][unidade] += item["quantidades"][unidade]
        secoes = []
        for secao in agrupados.values():
            secao["linhas"] = list(secao["linhas"].values())
            secao["totais"] = {
                unidade: sum(linha["quantidades"][unidade] for linha in secao["linhas"])
                for unidade in secao["unidades"]
            }
            secoes.append(secao)
        bruto = [_serializavel(item) for item in selecionados]
        token = _hash(bruto)
        return {"selecionados": selecionados, "secoes": secoes, "token": token,
                "quantidade_registros": len(selecionados)}
    finally:
        if conn:
            conn.close()


def _snapshot_serializavel(preview):
    secoes = []
    for secao in preview["secoes"]:
        copia = {k: v for k, v in secao.items() if k not in {"linhas", "totais"}}
        copia["linhas"] = [
            {"caracteristica": linha["caracteristica"],
             "quantidades": {k: str(v) if isinstance(v, Decimal) else v for k, v in linha["quantidades"].items()}}
            for linha in secao["linhas"]
        ]
        copia["totais"] = {k: str(v) if isinstance(v, Decimal) else v for k, v in secao["totais"].items()}
        secoes.append(copia)
    return {"secoes": secoes, "quantidade_registros": preview["quantidade_registros"]}


def emitir_relatorio_nc(chaves, token_previa, filtros, *, usuario, perfil):
    garantir_schema_relatorio_nc()
    with transaction() as conn:
        preview = consolidar_selecao(chaves, cursor=conn.cursor())
        if not token_previa or token_previa != preview["token"]:
            raise ValueError("Os saldos mudaram após a prévia. Atualize a conferência antes de gerar.")
        agora = _agora()
        numero = f"RNC-{agora:%Y%m%d}-{uuid4().hex[:8].upper()}"
        snapshot = _snapshot_serializavel(preview)
        selecao = [_serializavel(item) for item in preview["selecionados"]]
        totais = [{"produto": s["produto"], "apresentacao": s["apresentacao"],
                   "totais": s["totais"]} for s in snapshot["secoes"]]
        integridade = _hash({"numero": numero, "snapshot": snapshot, "selecao": selecao})
        cursor = conn.cursor()
        params = (numero, agora.isoformat(), usuario, perfil, _json(_normalizar_filtros(filtros)),
                  _json(selecao), _json(snapshot), _json(totais), integridade, "GERADO")
        sql = """INSERT INTO relatorios_nc_verificacao (
            numero,emitido_em,usuario,perfil,filtros_json,selecao_json,snapshot_json,
            totais_json,integridade_hash,resultado) VALUES (?,?,?,?,?,?,?,?,?,?)"""
        if DATABASE_URL:
            cursor.execute(q(sql + " RETURNING id"), params)
            relatorio_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q(sql), params)
            relatorio_id = cursor.lastrowid
        cursor.execute(q("""INSERT INTO relatorios_nc_verificacao_eventos
            (relatorio_id,acao,usuario,perfil,detalhes_json,criado_em)
            VALUES (?,?,?,?,?,?)"""),
            (relatorio_id, "GERACAO", usuario, perfil,
             _json({"numero": numero, "filtros": _normalizar_filtros(filtros),
                    "chaves": list(chaves), "totais": totais, "resultado": "GERADO",
                    "token": preview["token"], "integridade": integridade}), agora.isoformat()))
    return obter_relatorio_nc(relatorio_id)


def obter_relatorio_nc(relatorio_id):
    criar_tabelas_relatorios_nc()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM relatorios_nc_verificacao WHERE id=?"), (relatorio_id,))
        linha = cursor.fetchone()
        if not linha:
            return None
        resultado = dict(linha)
        for campo in ("filtros_json", "selecao_json", "snapshot_json", "totais_json"):
            resultado[campo.removesuffix("_json")] = json.loads(resultado[campo])
        integridade = _hash({
            "numero": resultado["numero"], "snapshot": resultado["snapshot"],
            "selecao": resultado["selecao"],
        })
        if integridade != resultado["integridade_hash"]:
            raise ValueError("A integridade do relatório armazenado não pôde ser confirmada.")
        return resultado
    finally:
        conn.close()


def listar_relatorios_nc(limite=20):
    criar_tabelas_relatorios_nc()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT id,numero,emitido_em,usuario,perfil,integridade_hash
            FROM relatorios_nc_verificacao ORDER BY id DESC LIMIT ?"""), (int(limite),))
        return cursor.fetchall()
    finally:
        conn.close()
