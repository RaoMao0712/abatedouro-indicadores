"""Indicadores auditáveis de prontidão por SKU, sem autoridade operacional."""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from database import DATABASE_URL, conectar, q
from modules.producao.skus_legados import SKUS_OPERACIONAIS_LEGADOS


ESTADOS = {
    "NAO_AVALIAVEL", "EM_OBSERVACAO", "BLOQUEADO_POR_DIVERGENCIA",
    "APTO_PARA_AVALIACAO",
}
DEFAULTS_CONFIGURAVEIS = {
    "minimo_ops_reconciliadas": 10,
    "janela_minima_dias": 30,
    "sequencia_minima_paridade": 5,
    "max_divergencias_media": 0,
    "max_divergencias_baixa": 0,
    "cobertura_critica_minima": 100.0,
}
DIMENSOES_CRITICAS_BASE = [
    "identidade_sku", "autoridade_modo", "roteiro_etapas", "ordem_etapas",
    "obrigatoriedade", "unidades_etapas", "apresentacoes", "unidade_operacional",
    "exigencia_peso", "regra_encerramento",
]
DIMENSOES_CRITICAS_SKU = {
    "Galinha Cortada": DIMENSOES_CRITICAS_BASE + ["bandejas_por_caixa", "tara_caixa_kg"],
    "Galinha Inteira": DIMENSOES_CRITICAS_BASE + ["fatores_conversao"],
}


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def criar_estrutura():
    nome = ("20260926_fase5_prontidao_sku.sql" if DATABASE_URL else
            "20260926_fase5_prontidao_sku_sqlite.sql")
    sql = (Path(__file__).resolve().parents[2] / "database" / nome).read_text(encoding="utf-8")
    conn = conectar()
    try:
        cursor = conn.cursor()
        for comando in [item.strip() for item in sql.replace("BEGIN;", "").replace("COMMIT;", "").split(";") if item.strip()]:
            cursor.execute(comando)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _parametros_padrao(sku):
    return {
        **DEFAULTS_CONFIGURAVEIS,
        "dimensoes_criticas": DIMENSOES_CRITICAS_SKU.get(sku, DIMENSOES_CRITICAS_BASE),
    }


def _validar_parametros(dados, sku):
    base = _parametros_padrao(sku)
    inteiros_positivos = ("minimo_ops_reconciliadas", "sequencia_minima_paridade")
    inteiros_nao_negativos = ("janela_minima_dias", "max_divergencias_media", "max_divergencias_baixa")
    for campo in inteiros_positivos:
        base[campo] = int(dados.get(campo, base[campo]))
        if base[campo] <= 0:
            raise ValueError(f"{campo} deve ser maior que zero.")
    for campo in inteiros_nao_negativos:
        base[campo] = int(dados.get(campo, base[campo]))
        if base[campo] < 0:
            raise ValueError(f"{campo} não pode ser negativo.")
    base["cobertura_critica_minima"] = float(
        dados.get("cobertura_critica_minima", base["cobertura_critica_minima"])
    )
    if not 0 <= base["cobertura_critica_minima"] <= 100:
        raise ValueError("cobertura_critica_minima deve estar entre 0 e 100.")
    dimensoes = dados.get("dimensoes_criticas", base["dimensoes_criticas"])
    if isinstance(dimensoes, str):
        try:
            dimensoes = json.loads(dimensoes)
        except ValueError:
            dimensoes = [item.strip() for item in dimensoes.split(",") if item.strip()]
    if not isinstance(dimensoes, list) or not dimensoes or any(not str(item).strip() for item in dimensoes):
        raise ValueError("dimensoes_criticas deve ser uma lista não vazia.")
    base["dimensoes_criticas"] = sorted(set(str(item).strip() for item in dimensoes))
    return base


def obter_parametros(sku, criar=False, usuario=None):
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM sku_prontidao_parametros WHERE sku=?"), (sku,))
    linha = cursor.fetchone()
    conn.close()
    if linha:
        resultado = dict(linha)
        resultado["dimensoes_criticas"] = json.loads(resultado.pop("dimensoes_criticas_json"))
        return resultado
    if not criar:
        return {"id": None, "sku": sku, "versao": 0, **_parametros_padrao(sku)}
    return salvar_parametros(sku, _parametros_padrao(sku), usuario or {})


def salvar_parametros(sku, dados, usuario=None):
    if sku not in SKUS_OPERACIONAIS_LEGADOS:
        raise ValueError("SKU sem representação operacional legada homologada.")
    usuario = usuario or {}
    valores = _validar_parametros(dados, sku)
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM sku_prontidao_parametros WHERE sku=?"), (sku,))
        atual = cursor.fetchone()
        if atual:
            versao = int(atual["versao"]) + 1
            cursor.execute(q("""UPDATE sku_prontidao_parametros SET
                minimo_ops_reconciliadas=?,janela_minima_dias=?,sequencia_minima_paridade=?,
                max_divergencias_media=?,max_divergencias_baixa=?,cobertura_critica_minima=?,
                dimensoes_criticas_json=?,versao=?,usuario_id=?,usuario_nome=?,
                atualizado_em=CURRENT_TIMESTAMP WHERE sku=?"""), (
                valores["minimo_ops_reconciliadas"], valores["janela_minima_dias"],
                valores["sequencia_minima_paridade"], valores["max_divergencias_media"],
                valores["max_divergencias_baixa"], valores["cobertura_critica_minima"],
                _json(valores["dimensoes_criticas"]), versao, usuario.get("id"),
                usuario.get("nome"), sku,
            ))
        else:
            versao = 1
            sql = """INSERT INTO sku_prontidao_parametros(
                sku,minimo_ops_reconciliadas,janela_minima_dias,sequencia_minima_paridade,
                max_divergencias_media,max_divergencias_baixa,cobertura_critica_minima,
                dimensoes_criticas_json,versao,usuario_id,usuario_nome
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)"""
            cursor.execute(q(sql), (
                sku, valores["minimo_ops_reconciliadas"], valores["janela_minima_dias"],
                valores["sequencia_minima_paridade"], valores["max_divergencias_media"],
                valores["max_divergencias_baixa"], valores["cobertura_critica_minima"],
                _json(valores["dimensoes_criticas"]), versao, usuario.get("id"), usuario.get("nome"),
            ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return obter_parametros(sku)


def _evidencias_correntes(cursor, sku):
    cursor.execute(q("""SELECT * FROM op_config_reconciliacoes
        WHERE sku=? ORDER BY op_id,versao_comparacao DESC,revisao DESC,id DESC"""), (sku,))
    atuais = {}
    for linha in cursor.fetchall():
        item = dict(linha)
        atuais.setdefault(item["op_id"], item)
    return sorted(atuais.values(), key=lambda item: (item["executado_em"], item["op_id"]))


def _execucoes(cursor, sku, op_ids):
    if not op_ids:
        return 0, [] , 0
    placeholders = ",".join(["?"] * len(op_ids))
    cursor.execute(q(f"""SELECT * FROM op_config_reconciliacao_execucoes
        WHERE op_id IN ({placeholders}) ORDER BY op_id,id DESC"""), tuple(op_ids))
    todas = [dict(item) for item in cursor.fetchall()]
    ultimas = {}
    for item in todas:
        ultimas.setdefault(item["op_id"], item)
    abertas = [item for item in ultimas.values() if item["status"] in ("PENDENTE", "PROCESSANDO", "ERRO")]
    return sum(1 for item in todas if item["status"] == "ERRO"), abertas, max([item["id"] for item in todas] or [0])


def _sequencias(resultados):
    atual = maior = corrente = 0
    for resultado in resultados:
        corrente = corrente + 1 if resultado == "PARIDADE" else 0
        maior = max(maior, corrente)
    if resultados:
        for resultado in reversed(resultados):
            if resultado != "PARIDADE":
                break
            atual += 1
    return atual, maior


def _data(valor):
    if isinstance(valor, datetime):
        return valor
    return datetime.fromisoformat(str(valor).replace("Z", "+00:00"))


def calcular_metricas(sku, parametros, cursor):
    evidencias = _evidencias_correntes(cursor, sku)
    resultados = [item["resultado_geral"] for item in evidencias]
    sequencia_atual, maior_sequencia = _sequencias(resultados)
    severidades = {nome: 0 for nome in ("CRITICA", "ALTA", "MEDIA", "BAIXA")}
    cobertas = set()
    ultima_divergencia = None
    for evidencia in evidencias:
        dimensoes = json.loads(evidencia["dimensoes_json"])
        for dimensao in dimensoes:
            if dimensao.get("severidade") == "CRITICA" and dimensao.get("resultado") != "INCONCLUSIVO":
                cobertas.add(dimensao.get("dimensao"))
            if dimensao.get("resultado") == "DIVERGENCIA":
                severidade = dimensao.get("severidade", "BAIXA")
                severidades[severidade] = severidades.get(severidade, 0) + 1
        if evidencia["resultado_geral"] == "DIVERGENCIA":
            ultima_divergencia = evidencia["executado_em"]
    esperadas = set(parametros["dimensoes_criticas"])
    cobertura = round(100.0 * len(esperadas & cobertas) / len(esperadas), 2) if esperadas else 100.0
    total = len(evidencias)
    datas = [_data(item["executado_em"]) for item in evidencias]
    janela = (max(datas) - min(datas)).days if len(datas) > 1 else 0
    op_ids = {item["op_id"] for item in evidencias}
    cursor.execute(q("SELECT id FROM ordens_producao WHERE sku=?"), (sku,))
    op_ids.update(item["id"] for item in cursor.fetchall())
    erros, pendencias_tecnicas, fonte_execucao = _execucoes(cursor, sku, sorted(op_ids))
    return {
        "total_ops_reconciliadas": total,
        "total_paridade": resultados.count("PARIDADE"),
        "total_divergencia": resultados.count("DIVERGENCIA"),
        "total_inconclusivo": resultados.count("INCONCLUSIVO"),
        "total_erros_tecnicos": erros,
        "taxa_paridade": round(100.0 * resultados.count("PARIDADE") / total, 2) if total else 0.0,
        "sequencia_atual_paridade": sequencia_atual,
        "maior_sequencia_paridade": maior_sequencia,
        "janela_observada_dias": janela,
        "ultima_divergencia": str(ultima_divergencia) if ultima_divergencia else None,
        "divergencias_abertas": severidades,
        "dimensoes_criticas_cobertas": sorted(esperadas & cobertas),
        "dimensoes_criticas_pendentes": sorted(esperadas - cobertas),
        "cobertura_critica_percentual": cobertura,
        "pendencias_tecnicas_abertas": len(pendencias_tecnicas),
        "ops_com_pendencia_tecnica": sorted(item["op_id"] for item in pendencias_tecnicas),
        "fonte_reconciliacao_id": max([item["id"] for item in evidencias] or [0]),
        "fonte_execucao_id": fonte_execucao,
    }


def classificar(metricas, parametros):
    motivos = []
    if metricas["total_ops_reconciliadas"] == 0:
        return "NAO_AVALIAVEL", ["Nenhuma OP possui reconciliação válida para o SKU."]
    abertas = metricas["divergencias_abertas"]
    if abertas["CRITICA"] or abertas["ALTA"]:
        if abertas["CRITICA"]:
            motivos.append(f"Existem {abertas['CRITICA']} divergência(s) CRÍTICA(s) aberta(s).")
        if abertas["ALTA"]:
            motivos.append(f"Existem {abertas['ALTA']} divergência(s) ALTA(s) aberta(s).")
        return "BLOQUEADO_POR_DIVERGENCIA", motivos
    verificacoes = (
        (metricas["total_ops_reconciliadas"] >= parametros["minimo_ops_reconciliadas"],
         "Quantidade mínima de OPs reconciliadas ainda não atingida."),
        (metricas["janela_observada_dias"] >= parametros["janela_minima_dias"],
         "Janela mínima de observação ainda não atingida."),
        (metricas["sequencia_atual_paridade"] >= parametros["sequencia_minima_paridade"],
         "Sequência contínua mínima de PARIDADE ainda não atingida."),
        (abertas["MEDIA"] <= parametros["max_divergencias_media"],
         "Tolerância de divergências MÉDIAS excedida."),
        (abertas["BAIXA"] <= parametros["max_divergencias_baixa"],
         "Tolerância de divergências BAIXAS excedida."),
        (metricas["cobertura_critica_percentual"] >= parametros["cobertura_critica_minima"],
         "Cobertura mínima das dimensões críticas ainda não atingida."),
        (metricas["total_inconclusivo"] == 0, "Existem OPs com resultado INCONCLUSIVO."),
        (metricas["pendencias_tecnicas_abertas"] == 0, "Existem reconciliações pendentes ou com erro técnico."),
    )
    motivos.extend(motivo for passou, motivo in verificacoes if not passou)
    return ("EM_OBSERVACAO", motivos) if motivos else ("APTO_PARA_AVALIACAO", [])


def recalcular(sku, usuario=None):
    if sku not in SKUS_OPERACIONAIS_LEGADOS:
        raise ValueError("SKU sem representação operacional legada homologada.")
    usuario = usuario or {}
    parametros = obter_parametros(sku, criar=True, usuario=usuario)
    conn = conectar()
    try:
        metricas = calcular_metricas(sku, parametros, conn.cursor())
    finally:
        conn.close()
    estado, motivos = classificar(metricas, parametros)
    conteudo = {
        "sku": sku, "estado": estado, "autoridade_operacional": "LEGADO",
        "parametros": {chave: parametros[chave] for chave in DEFAULTS_CONFIGURAVEIS} |
                      {"dimensoes_criticas": parametros["dimensoes_criticas"], "versao": parametros["versao"]},
        "metricas": metricas, "motivos": motivos,
    }
    hash_avaliacao = hashlib.sha256(_json(conteudo).encode("utf-8")).hexdigest()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM sku_prontidao_avaliacoes WHERE sku=? AND hash_avaliacao=?"),
                       (sku, hash_avaliacao))
        existente = cursor.fetchone()
        if existente:
            return _desserializar(dict(existente))
        sql = """INSERT INTO sku_prontidao_avaliacoes(
            sku,parametro_id,estado,autoridade_operacional,parametros_json,metricas_json,
            motivos_json,fonte_reconciliacao_id,fonte_execucao_id,hash_avaliacao,
            usuario_id,usuario_nome
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"""
        valores = (
            sku, parametros["id"], estado, "LEGADO", _json(conteudo["parametros"]),
            _json(metricas), _json(motivos), metricas["fonte_reconciliacao_id"] or None,
            metricas["fonte_execucao_id"] or None, hash_avaliacao,
            usuario.get("id"), usuario.get("nome"),
        )
        if DATABASE_URL:
            cursor.execute(q(sql + " ON CONFLICT (sku,hash_avaliacao) DO NOTHING RETURNING id"), valores)
            inserido = cursor.fetchone()
            if not inserido:
                cursor.execute(q("SELECT * FROM sku_prontidao_avaliacoes WHERE sku=? AND hash_avaliacao=?"),
                               (sku, hash_avaliacao))
                resultado = cursor.fetchone()
                conn.commit()
                return _desserializar(dict(resultado))
            avaliacao_id = inserido["id"]
        else:
            cursor.execute(sql, valores)
            avaliacao_id = cursor.lastrowid
        conn.commit()
        cursor.execute(q("SELECT * FROM sku_prontidao_avaliacoes WHERE id=?"), (avaliacao_id,))
        return _desserializar(dict(cursor.fetchone()))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _desserializar(item):
    item["parametros"] = json.loads(item.pop("parametros_json"))
    item["metricas"] = json.loads(item.pop("metricas_json"))
    item["motivos"] = json.loads(item.pop("motivos_json"))
    return item


def listar_avaliacoes(filtros=None):
    filtros = filtros or {}
    conn = conectar(); cursor = conn.cursor()
    cursor.execute("SELECT * FROM sku_prontidao_avaliacoes ORDER BY sku,id DESC")
    historico = [_desserializar(dict(item)) for item in cursor.fetchall()]
    conn.close()
    ultimas = {}
    for item in historico:
        ultimas.setdefault(item["sku"], item)
    linhas = []
    for sku in sorted(SKUS_OPERACIONAIS_LEGADOS):
        item = ultimas.get(sku)
        if not item:
            item = {
                "id": None, "sku": sku, "estado": "NAO_AVALIAVEL",
                "autoridade_operacional": "LEGADO", "avaliado_em": None,
                "parametros": obter_parametros(sku), "metricas": {},
                "motivos": ["Avaliação ainda não executada."],
            }
        if filtros.get("sku") and sku != filtros["sku"]:
            continue
        if filtros.get("estado") and item["estado"] != filtros["estado"]:
            continue
        linhas.append(item)
    return linhas, historico
