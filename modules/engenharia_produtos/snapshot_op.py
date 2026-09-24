"""Snapshot auditável da configuração sombra vigente na criação de uma OP."""

import json
from decimal import Decimal

from database import DATABASE_URL, q
from modules.producao.skus_legados import validar_sku_operacional

from . import representacao_legada


SCHEMA_VERSION = 1


def _json_carregado(valor, campo):
    try:
        return json.loads(valor or "{}")
    except (TypeError, ValueError) as erro:
        raise ValueError(f"Configuração sombra inválida em {campo}.") from erro


def _valor(valor):
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


def montar_snapshot(cursor, sku_nome):
    """Monta uma cópia autossuficiente após validar a paridade com o legado."""
    sku_nome = validar_sku_operacional(sku_nome)
    esperado = representacao_legada.ESPECIFICACOES[sku_nome]
    paridade = representacao_legada.comparar(sku_nome, cursor)
    if not paridade["paridade"]:
        raise ValueError(
            "Configuração sombra divergente do SKU legado; criação da OP bloqueada."
        )

    cursor.execute(q("""
        SELECT s.id AS sku_id,s.codigo AS sku_codigo,s.nome AS sku_nome,
               s.tipo_produto,s.unidade_venda,
               sv.id AS sku_versao_id,sv.versao AS sku_versao,
               sv.nome AS sku_versao_nome,sv.codigo AS sku_versao_codigo,
               sv.unidade_apresentacao,sv.apresentacao,
               sv.categoria_tipo,sv.status AS sku_versao_status,
               sv.vigencia_inicio AS sku_vigencia_inicio,
               sv.vigencia_fim AS sku_vigencia_fim,
               sv.parametros_json AS sku_parametros_json,
               rv.id AS roteiro_versao_id,rv.versao AS roteiro_versao,
               rv.status AS roteiro_status,rv.vigencia_inicio AS roteiro_vigencia_inicio,
               rv.vigencia_fim AS roteiro_vigencia_fim,
               rv.aprovado_por,rv.aprovado_em,rv.observacoes,
               rv.parametros_json AS roteiro_parametros_json
        FROM skus s
        JOIN sku_versoes sv ON sv.sku_id=s.id AND sv.status='ATIVA'
        JOIN roteiro_versoes rv ON rv.sku_versao_id=sv.id AND rv.status='ATIVO'
        WHERE s.nome=? AND s.codigo=? AND s.excluido_em IS NULL
    """), (sku_nome, esperado["codigo"]))
    configuracao = cursor.fetchone()
    if not configuracao:
        raise ValueError(
            "SKU legado sem versão e roteiro sombra ativos; criação da OP bloqueada."
        )

    sku_parametros = _json_carregado(
        configuracao["sku_parametros_json"], "sku_versoes.parametros_json"
    )
    roteiro_parametros = _json_carregado(
        configuracao["roteiro_parametros_json"], "roteiro_versoes.parametros_json"
    )
    if (sku_parametros.get("autoridade_operacional") != "LEGADO"
            or sku_parametros.get("modo") != "SOMBRA"):
        raise ValueError(
            "SKU sem autoridade LEGADO e modo SOMBRA; criação da OP bloqueada."
        )

    cursor.execute(q("""
        SELECT re.id,re.ordem,re.nome,re.obrigatoria,re.unidade_entrada,
               re.unidade_saida,re.gera_intermediario,re.controla_qualidade,
               re.parametros_json,ec.id AS etapa_catalogo_id,
               ec.codigo AS etapa_codigo,ec.nome AS etapa_catalogo_nome,
               ec.natureza AS etapa_natureza,ec.parametros_json AS catalogo_parametros_json
        FROM roteiro_etapas re
        LEFT JOIN etapas_catalogo ec ON ec.id=re.etapa_catalogo_id
        WHERE re.roteiro_versao_id=?
        ORDER BY re.ordem
    """), (configuracao["roteiro_versao_id"],))
    etapas = []
    for etapa in cursor.fetchall():
        cursor.execute(q("""
            SELECT rei.id,rei.insumo_id,ai.descricao AS insumo_descricao,
                   ai.categoria AS insumo_categoria,ai.unidade AS insumo_unidade_cadastro,
                   rei.unidade,
                   rei.quantidade_fator,rei.tipo_calculo,rei.tolerancia_perda,
                   rei.obrigatorio,rei.origem_baixa,rei.parametros_json
            FROM roteiro_etapa_insumos rei
            JOIN almoxarifado_insumos ai ON ai.id=rei.insumo_id
            WHERE rei.roteiro_etapa_id=? ORDER BY rei.id
        """), (etapa["id"],))
        insumos = [{
            "id_configuracao": item["id"],
            "insumo_id": item["insumo_id"],
            "descricao": item["insumo_descricao"],
            "categoria": item["insumo_categoria"],
            "unidade_cadastro": item["insumo_unidade_cadastro"],
            "unidade": item["unidade"],
            "quantidade_fator": _valor(item["quantidade_fator"]),
            "tipo_calculo": item["tipo_calculo"],
            "tolerancia_perda": _valor(item["tolerancia_perda"]),
            "obrigatorio": bool(item["obrigatorio"]),
            "origem_baixa": item["origem_baixa"],
            "parametros": _json_carregado(item["parametros_json"], "insumo.parametros_json"),
        } for item in cursor.fetchall()]
        etapas.append({
            "id_configuracao": etapa["id"],
            "ordem": etapa["ordem"],
            "codigo": etapa["etapa_codigo"],
            "nome": etapa["nome"],
            "obrigatoria": bool(etapa["obrigatoria"]),
            "unidade_entrada": etapa["unidade_entrada"],
            "unidade_saida": etapa["unidade_saida"],
            "gera_intermediario": bool(etapa["gera_intermediario"]),
            "controla_qualidade": bool(etapa["controla_qualidade"]),
            "catalogo": {
                "id": etapa["etapa_catalogo_id"],
                "nome": etapa["etapa_catalogo_nome"],
                "natureza": etapa["etapa_natureza"],
                "parametros": _json_carregado(
                    etapa["catalogo_parametros_json"], "etapa_catalogo.parametros_json"
                ) if etapa["etapa_catalogo_id"] else None,
            },
            "parametros": _json_carregado(etapa["parametros_json"], "etapa.parametros_json"),
            "insumos": insumos,
        })

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "autoridade_operacional": "LEGADO",
        "modo": "SOMBRA",
        "sku": {
            "id": configuracao["sku_id"],
            "codigo": configuracao["sku_codigo"],
            "nome": configuracao["sku_nome"],
            "tipo_produto": configuracao["tipo_produto"],
            "unidade_venda": configuracao["unidade_venda"],
        },
        "sku_versao": {
            "id": configuracao["sku_versao_id"],
            "versao": configuracao["sku_versao"],
            "nome": configuracao["sku_versao_nome"],
            "codigo": configuracao["sku_versao_codigo"],
            "unidade_apresentacao": configuracao["unidade_apresentacao"],
            "apresentacao": configuracao["apresentacao"],
            "categoria_tipo": configuracao["categoria_tipo"],
            "status": configuracao["sku_versao_status"],
            "vigencia_inicio": str(configuracao["sku_vigencia_inicio"]),
            "vigencia_fim": str(configuracao["sku_vigencia_fim"]) if configuracao["sku_vigencia_fim"] else None,
            "parametros": sku_parametros,
        },
        "roteiro": {
            "id": configuracao["roteiro_versao_id"],
            "versao": configuracao["roteiro_versao"],
            "status": configuracao["roteiro_status"],
            "vigencia_inicio": str(configuracao["roteiro_vigencia_inicio"]),
            "vigencia_fim": str(configuracao["roteiro_vigencia_fim"]) if configuracao["roteiro_vigencia_fim"] else None,
            "aprovado_por": configuracao["aprovado_por"],
            "aprovado_em": str(configuracao["aprovado_em"]) if configuracao["aprovado_em"] else None,
            "observacoes": configuracao["observacoes"],
            "parametros": roteiro_parametros,
            "etapas": etapas,
        },
    }
    return {
        "sku_id": configuracao["sku_id"],
        "sku_versao_id": configuracao["sku_versao_id"],
        "roteiro_versao_id": configuracao["roteiro_versao_id"],
        "snapshot": snapshot,
    }


def gravar_snapshot(cursor, op_id, sku_nome, usuario_id=None, usuario_nome="Sistema"):
    """Grava exatamente um snapshot usando a transação já aberta pelo chamador."""
    cursor.execute(q("SELECT * FROM op_config_snapshots WHERE op_id=?"), (op_id,))
    existente = cursor.fetchone()
    if existente:
        congelado = _json_carregado(existente["snapshot_json"], "op_config_snapshots.snapshot_json")
        if congelado.get("sku", {}).get("nome") != validar_sku_operacional(sku_nome):
            raise ValueError("A OP já possui snapshot imutável para outro SKU.")
        return dict(existente)

    dados = montar_snapshot(cursor, sku_nome)
    serializado = json.dumps(
        dados["snapshot"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    sql = """INSERT INTO op_config_snapshots(
        op_id,sku_id,sku_versao_id,roteiro_versao_id,schema_version,
        snapshot_json,usuario_id,usuario_nome
    ) VALUES(?,?,?,?,?,?,?,?)"""
    parametros = (
        op_id, dados["sku_id"], dados["sku_versao_id"],
        dados["roteiro_versao_id"], SCHEMA_VERSION, serializado,
        usuario_id, usuario_nome or "Sistema",
    )
    if DATABASE_URL:
        cursor.execute(q(sql + " ON CONFLICT (op_id) DO NOTHING RETURNING id,snapshot_json"), parametros)
        inserido = cursor.fetchone()
        if inserido:
            snapshot_id = inserido["id"]
        else:
            cursor.execute(q("SELECT * FROM op_config_snapshots WHERE op_id=?"), (op_id,))
            existente = cursor.fetchone()
            congelado = _json_carregado(existente["snapshot_json"], "op_config_snapshots.snapshot_json")
            if congelado.get("sku", {}).get("nome") != sku_nome:
                raise ValueError("A OP já possui snapshot imutável para outro SKU.")
            return dict(existente)
    else:
        cursor.execute(sql.replace("INSERT INTO", "INSERT OR IGNORE INTO", 1), parametros)
        cursor.execute(q("SELECT * FROM op_config_snapshots WHERE op_id=?"), (op_id,))
        existente = cursor.fetchone()
        congelado = _json_carregado(existente["snapshot_json"], "op_config_snapshots.snapshot_json")
        if congelado.get("sku", {}).get("nome") != sku_nome:
            raise ValueError("A OP já possui snapshot imutável para outro SKU.")
        return dict(existente)
    return {"id": snapshot_id, "op_id": op_id, "snapshot_json": serializado}
