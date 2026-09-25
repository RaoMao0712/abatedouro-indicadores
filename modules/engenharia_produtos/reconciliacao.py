"""Reconciliação auditável entre regras legadas e snapshots em modo sombra."""

import hashlib
import json
from pathlib import Path

from database import DATABASE_URL, conectar, q, transaction

from .representacao_legada import ESPECIFICACOES


VERSAO_COMPARACAO = 1
RESULTADOS = {"PARIDADE", "DIVERGENCIA", "INCONCLUSIVO"}
SEVERIDADES = {"CRITICA", "ALTA", "MEDIA", "BAIXA"}


def criar_estrutura():
    nomes = (["20260924_fase4_reconciliacao_sombra.sql",
              "20260925_fase4_1_execucoes_reconciliacao.sql"] if DATABASE_URL else
             ["20260924_fase4_reconciliacao_sombra_sqlite.sql",
              "20260925_fase4_1_execucoes_reconciliacao_sqlite.sql"])
    conn = conectar()
    try:
        cursor = conn.cursor()
        for nome in nomes:
            sql = (Path(__file__).resolve().parents[2] / "database" / nome).read_text(encoding="utf-8")
            for comando in [item.strip() for item in sql.replace("BEGIN;", "").replace("COMMIT;", "").split(";") if item.strip()]:
                cursor.execute(comando)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalizar(valor):
    if isinstance(valor, dict):
        return {chave: _normalizar(valor[chave]) for chave in sorted(valor)}
    if isinstance(valor, list):
        return [_normalizar(item) for item in valor]
    return valor


def _dimensao(nome, legado, sombra, severidade="CRITICA", motivo_inconclusivo=None):
    if motivo_inconclusivo:
        return {
            "dimensao": nome, "resultado": "INCONCLUSIVO", "severidade": severidade,
            "valor_legado": legado, "valor_sombra": sombra, "motivo": motivo_inconclusivo,
        }
    resultado = "PARIDADE" if _normalizar(legado) == _normalizar(sombra) else "DIVERGENCIA"
    return {
        "dimensao": nome, "resultado": resultado, "severidade": severidade,
        "valor_legado": legado, "valor_sombra": sombra,
    }


def comparar_snapshot(op, snapshot):
    sku = str(op.get("sku") or "").strip()
    legado = ESPECIFICACOES.get(sku)
    if not legado:
        return {
            "resultado_geral": "INCONCLUSIVO",
            "dimensoes": [_dimensao(
                "identidade_sku", None, snapshot.get("sku"), "CRITICA",
                "SKU da OP não possui resolução no motor legado homologado.",
            )],
        }

    roteiro = snapshot.get("roteiro")
    sku_snapshot = snapshot.get("sku")
    if not isinstance(roteiro, dict) or not isinstance(sku_snapshot, dict):
        return {
            "resultado_geral": "INCONCLUSIVO",
            "dimensoes": [_dimensao(
                "estrutura_snapshot", "sku e roteiro presentes", snapshot, "CRITICA",
                "Snapshot sem identidade ou roteiro suficiente para comparação.",
            )],
        }

    parametros = roteiro.get("parametros") if isinstance(roteiro.get("parametros"), dict) else None
    etapas = roteiro.get("etapas") if isinstance(roteiro.get("etapas"), list) else None
    dimensoes = [
        _dimensao("schema_snapshot", 1, snapshot.get("schema_version"), "ALTA"),
        _dimensao("identidade_sku", {"nome": sku, "codigo": legado["codigo"]},
                  {"nome": sku_snapshot.get("nome"), "codigo": sku_snapshot.get("codigo")}),
        _dimensao("autoridade_modo", {"autoridade_operacional": "LEGADO", "modo": "SOMBRA"},
                  {"autoridade_operacional": snapshot.get("autoridade_operacional"), "modo": snapshot.get("modo")}),
    ]
    if parametros is None or etapas is None:
        dimensoes.append(_dimensao(
            "roteiro_etapas", "roteiro e etapas disponíveis", roteiro, "CRITICA",
            "Roteiro ou parâmetros ausentes no snapshot.",
        ))
    else:
        esperado_etapas = [{
            "ordem": ordem, "codigo": item[0], "nome": item[1],
            "unidade_entrada": item[2], "unidade_saida": item[3], "obrigatoria": True,
        } for ordem, item in enumerate(legado["etapas"], 1)]
        atual_etapas = [{
            "ordem": item.get("ordem"), "codigo": item.get("codigo"), "nome": item.get("nome"),
            "unidade_entrada": item.get("unidade_entrada"), "unidade_saida": item.get("unidade_saida"),
            "obrigatoria": item.get("obrigatoria"),
        } for item in etapas]
        dimensoes.extend([
            _dimensao("roteiro_etapas", [x[0] for x in legado["etapas"]], [x.get("codigo") for x in etapas]),
            _dimensao("ordem_etapas", list(range(1, len(legado["etapas"]) + 1)), [x.get("ordem") for x in etapas]),
            _dimensao("obrigatoriedade", [True] * len(legado["etapas"]), [x.get("obrigatoria") for x in etapas]),
            _dimensao("unidades_etapas",
                      [{"entrada": x[2], "saida": x[3]} for x in legado["etapas"]],
                      [{"entrada": x.get("unidade_entrada"), "saida": x.get("unidade_saida")} for x in etapas]),
            _dimensao("detalhes_etapas", esperado_etapas, atual_etapas, "ALTA"),
            _dimensao("apresentacoes", legado["apresentacoes"], parametros.get("apresentacoes")),
            _dimensao("unidade_operacional", legado["unidade_operacional"], parametros.get("unidade_operacional")),
            _dimensao("exigencia_peso", legado["exige_peso"], parametros.get("exige_peso")),
            _dimensao("regra_encerramento", legado["encerramento"], parametros.get("encerramento")),
        ])
        fatores_legado = legado.get("aves_por_pacote")
        fatores_sombra = parametros.get("aves_por_pacote")
        if fatores_legado is not None or fatores_sombra is not None:
            dimensoes.append(_dimensao("fatores_conversao", fatores_legado, fatores_sombra))
        if sku == "Galinha Cortada":
            dimensoes.extend([
                _dimensao("bandejas_por_caixa", 12, parametros.get("bandejas_por_caixa")),
                _dimensao("tara_caixa_kg", 0.5, parametros.get("tara_caixa_kg")),
            ])
        insumos = [item for etapa in etapas for item in (etapa.get("insumos") or [])]
        if insumos:
            dimensoes.append(_dimensao(
                "insumos", None, insumos, "ALTA",
                "Motor legado não resolve etapa de consumo para os insumos configurados.",
            ))
        else:
            dimensoes.append(_dimensao("insumos", [], [], "ALTA"))

    resultados = {item["resultado"] for item in dimensoes}
    geral = "DIVERGENCIA" if "DIVERGENCIA" in resultados else (
        "INCONCLUSIVO" if "INCONCLUSIVO" in resultados else "PARIDADE"
    )
    return {"resultado_geral": geral, "dimensoes": dimensoes}


def reconciliar_op(cursor, op_id, versao_comparacao=VERSAO_COMPARACAO):
    cursor.execute(q("SELECT id,sku FROM ordens_producao WHERE id=?"), (op_id,))
    op = cursor.fetchone()
    cursor.execute(q("SELECT id,snapshot_json FROM op_config_snapshots WHERE op_id=?"), (op_id,))
    snapshot_row = cursor.fetchone()
    if not op or not snapshot_row:
        raise ValueError("OP ou snapshot indisponível para reconciliação.")
    try:
        snapshot = json.loads(snapshot_row["snapshot_json"])
    except (TypeError, ValueError) as erro:
        snapshot = {}
        comparacao = {
            "resultado_geral": "INCONCLUSIVO",
            "dimensoes": [_dimensao(
                "snapshot_json", "JSON válido", snapshot_row["snapshot_json"], "CRITICA",
                "Snapshot não contém JSON válido.",
            )],
        }
    else:
        comparacao = comparar_snapshot(dict(op), snapshot)

    divergencias = [item for item in comparacao["dimensoes"] if item["resultado"] != "PARIDADE"]
    evidencia = {
        "op_id": op_id, "snapshot_id": snapshot_row["id"], "sku": op["sku"],
        "versao_comparacao": versao_comparacao,
        "resultado_geral": comparacao["resultado_geral"],
        "dimensoes": comparacao["dimensoes"], "divergencias": divergencias,
    }
    hash_comparacao = hashlib.sha256(_json(evidencia).encode("utf-8")).hexdigest()
    cursor.execute(q("""SELECT * FROM op_config_reconciliacoes
        WHERE snapshot_id=? AND versao_comparacao=? AND hash_comparacao=?"""),
                   (snapshot_row["id"], versao_comparacao, hash_comparacao))
    existente = cursor.fetchone()
    if existente:
        return dict(existente)
    cursor.execute(q("""SELECT COALESCE(MAX(revisao),0)+1 AS proxima
        FROM op_config_reconciliacoes WHERE snapshot_id=? AND versao_comparacao=?"""),
                   (snapshot_row["id"], versao_comparacao))
    revisao = cursor.fetchone()["proxima"]
    sql = """INSERT INTO op_config_reconciliacoes(
        op_id,snapshot_id,sku,resultado_geral,dimensoes_json,divergencias_json,
        versao_comparacao,revisao,hash_comparacao
    ) VALUES(?,?,?,?,?,?,?,?,?)"""
    parametros_insert = (
        op_id, snapshot_row["id"], op["sku"], comparacao["resultado_geral"],
        _json(comparacao["dimensoes"]), _json(divergencias), versao_comparacao,
        revisao, hash_comparacao,
    )
    if DATABASE_URL:
        cursor.execute(q(sql + " ON CONFLICT (snapshot_id,versao_comparacao,hash_comparacao) DO NOTHING RETURNING id"), parametros_insert)
        inserido = cursor.fetchone()
        if not inserido:
            cursor.execute(q("""SELECT * FROM op_config_reconciliacoes
                WHERE snapshot_id=? AND versao_comparacao=? AND hash_comparacao=?"""),
                           (snapshot_row["id"], versao_comparacao, hash_comparacao))
            return dict(cursor.fetchone())
        reconciliacao_id = inserido["id"]
    else:
        cursor.execute(sql, parametros_insert)
        reconciliacao_id = cursor.lastrowid
    cursor.execute(q("SELECT * FROM op_config_reconciliacoes WHERE id=?"), (reconciliacao_id,))
    return dict(cursor.fetchone())


def _registrar_execucao_pendente(op_id, gatilho, versao_comparacao):
    with transaction() as conn:
        cursor = conn.cursor()
        sql_snapshot = "SELECT id FROM op_config_snapshots WHERE op_id=?"
        if DATABASE_URL:
            sql_snapshot += " FOR UPDATE"
        cursor.execute(q(sql_snapshot), (op_id,))
        snapshot = cursor.fetchone()
        if not snapshot:
            raise ValueError("Snapshot indisponível para agendar reconciliação.")
        cursor.execute(q("""SELECT COALESCE(MAX(tentativa),0)+1 AS proxima
            FROM op_config_reconciliacao_execucoes
            WHERE snapshot_id=? AND versao_comparacao=? AND gatilho=?"""),
                       (snapshot["id"], versao_comparacao, gatilho))
        tentativa = cursor.fetchone()["proxima"]
        sql = """INSERT INTO op_config_reconciliacao_execucoes(
            op_id,snapshot_id,versao_comparacao,gatilho,tentativa,status
        ) VALUES(?,?,?,?,?,'PENDENTE')"""
        parametros = (op_id, snapshot["id"], versao_comparacao, gatilho, tentativa)
        if DATABASE_URL:
            cursor.execute(q(sql + " RETURNING id"), parametros)
            return cursor.fetchone()["id"]
        cursor.execute(sql, parametros)
        return cursor.lastrowid


def executar_reconciliacao_segura(op_id, gatilho="MANUAL", versao_comparacao=VERSAO_COMPARACAO):
    """Executa fora da transação operacional e nunca propaga falha ao chamador."""
    try:
        execucao_id = _registrar_execucao_pendente(op_id, gatilho, versao_comparacao)
    except Exception as erro:
        return {
            "status": "ERRO", "registrado": False,
            "erro_tipo": type(erro).__name__, "erro_mensagem": str(erro)[:1000],
        }
    try:
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(q("""UPDATE op_config_reconciliacao_execucoes
                SET status='PROCESSANDO',iniciado_em=CURRENT_TIMESTAMP,
                    atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""), (execucao_id,))
            registro = reconciliar_op(cursor, op_id, versao_comparacao)
            cursor.execute(q("""UPDATE op_config_reconciliacao_execucoes
                SET status='SUCESSO',reconciliacao_id=?,concluido_em=CURRENT_TIMESTAMP,
                    atualizado_em=CURRENT_TIMESTAMP WHERE id=?"""),
                           (registro["id"], execucao_id))
        return {"status": "SUCESSO", "execucao_id": execucao_id, "reconciliacao": registro}
    except Exception as erro:
        try:
            with transaction() as conn:
                conn.cursor().execute(q("""UPDATE op_config_reconciliacao_execucoes
                    SET status='ERRO',erro_tipo=?,erro_mensagem=?,
                        concluido_em=CURRENT_TIMESTAMP,atualizado_em=CURRENT_TIMESTAMP
                    WHERE id=?"""), (type(erro).__name__, str(erro)[:1000], execucao_id))
        except Exception:
            pass
        return {
            "status": "ERRO", "registrado": True, "execucao_id": execucao_id,
            "erro_tipo": type(erro).__name__, "erro_mensagem": str(erro)[:1000],
        }


def reprocessar_pendentes(limite=50):
    criar_estrutura()
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("""SELECT e.op_id FROM op_config_reconciliacao_execucoes e
        WHERE e.id IN (SELECT MAX(id) FROM op_config_reconciliacao_execucoes GROUP BY op_id)
          AND e.status IN ('PENDENTE','ERRO')
        ORDER BY e.id LIMIT ?"""), (int(limite),))
    ops = [item["op_id"] for item in cursor.fetchall()]
    conn.close()
    return [executar_reconciliacao_segura(op_id, "RETRY") for op_id in ops]


def listar_execucoes_tecnicas(filtros=None):
    filtros = filtros or {}
    criar_estrutura()
    condicoes, parametros = [], []
    if filtros.get("op_id"):
        condicoes.append("op_id=?"); parametros.append(int(filtros["op_id"]))
    if filtros.get("estado_tecnico"):
        condicoes.append("status=?"); parametros.append(filtros["estado_tecnico"])
    where = " WHERE " + " AND ".join(condicoes) if condicoes else ""
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM op_config_reconciliacao_execucoes" + where +
                     " ORDER BY id DESC"), tuple(parametros))
    registros = [dict(item) for item in cursor.fetchall()]
    cursor.execute("""SELECT
        COUNT(CASE WHEN status='PENDENTE' THEN 1 END) AS pendentes,
        COUNT(CASE WHEN status='ERRO' THEN 1 END) AS erros
        FROM op_config_reconciliacao_execucoes
        WHERE id IN (SELECT MAX(id) FROM op_config_reconciliacao_execucoes GROUP BY op_id)""")
    resumo = dict(cursor.fetchone())
    conn.close()
    return registros, resumo


def listar_reconciliacoes(filtros=None):
    filtros = filtros or {}
    criar_estrutura()
    condicoes, parametros = [], []
    if filtros.get("op_id"):
        condicoes.append("r.op_id=?"); parametros.append(int(filtros["op_id"]))
    if filtros.get("sku"):
        condicoes.append("r.sku=?"); parametros.append(filtros["sku"])
    if filtros.get("resultado"):
        condicoes.append("r.resultado_geral=?"); parametros.append(filtros["resultado"])
    if filtros.get("inicio"):
        condicoes.append("r.executado_em>=?"); parametros.append(filtros["inicio"])
    if filtros.get("fim"):
        condicoes.append("r.executado_em<=?"); parametros.append(filtros["fim"] + " 23:59:59")
    where = " WHERE " + " AND ".join(condicoes) if condicoes else ""
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("""SELECT r.*,o.status AS op_status FROM op_config_reconciliacoes r
        LEFT JOIN ordens_producao o ON o.id=r.op_id""" + where + " ORDER BY r.executado_em DESC,r.id DESC"), tuple(parametros))
    registros = [dict(item) for item in cursor.fetchall()]
    cursor.execute("""SELECT COUNT(DISTINCT op_id) AS reconciliadas,
        COUNT(DISTINCT CASE WHEN resultado_geral='PARIDADE' THEN op_id END) AS paridade,
        COUNT(DISTINCT CASE WHEN resultado_geral='DIVERGENCIA' THEN op_id END) AS divergencias,
        COUNT(DISTINCT CASE WHEN resultado_geral='INCONCLUSIVO' THEN op_id END) AS inconclusivos,
        MAX(CASE WHEN resultado_geral='DIVERGENCIA' THEN executado_em END) AS ultima_divergencia
        FROM op_config_reconciliacoes
        WHERE id IN (SELECT MAX(id) FROM op_config_reconciliacoes GROUP BY op_id)""")
    resumo = dict(cursor.fetchone())
    cursor.execute("""SELECT op_id,resultado_geral FROM op_config_reconciliacoes
        WHERE id IN (SELECT MAX(id) FROM op_config_reconciliacoes GROUP BY op_id)
        ORDER BY op_id DESC""")
    sequencia = 0
    for item in cursor.fetchall():
        if item["resultado_geral"] != "PARIDADE":
            break
        sequencia += 1
    resumo["sequencia_paridade"] = sequencia
    conn.close()
    return registros, resumo
