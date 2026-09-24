"""Proteções conservadoras para mudança de SKU de uma OP existente."""

import json
from datetime import datetime
from uuid import uuid4

from database import DATABASE_URL, q


TABELAS_FATOS_OP = (
    "apontamentos_setor", "apontamentos_producao", "apontamentos_mao_obra",
    "apontamentos_paradas", "apontamentos_descartes", "apontamentos_tempos_setor",
    "estoque_produto_intermediario", "embalagem_primaria_apontamentos",
    "pa_caixa_composicao", "expedicao_itens", "pa_nao_conformes",
    "estoque_marcos", "embalagem_secundaria_estornos",
    "embalagem_secundaria_conferencias", "embalagem_secundaria_requisicoes",
    "almoxarifado_movimentacoes", "linha_performance_snapshots_op",
    "linha_performance_contagens", "linha_performance_reprocessos",
    "retrabalho_origens",
)


def _tabelas_existentes(cursor):
    if DATABASE_URL:
        cursor.execute("""SELECT table_name FROM information_schema.columns
                          WHERE table_schema=current_schema() AND column_name='op_id'""")
    else:
        cursor.execute("""SELECT m.name AS table_name FROM sqlite_master m
                          JOIN pragma_table_info(m.name) p ON p.name='op_id'
                          WHERE m.type='table'""")
    return {linha["table_name"] for linha in cursor.fetchall()}


def fatos_operacionais_op(cursor, op_id):
    encontrados = []
    existentes = _tabelas_existentes(cursor)
    for tabela in TABELAS_FATOS_OP:
        if tabela not in existentes:
            continue
        cursor.execute(q(f"SELECT 1 FROM {tabela} WHERE op_id=? LIMIT 1"), (op_id,))
        if cursor.fetchone():
            encontrados.append(tabela)
    return encontrados


def validar_alteracao_sku(cursor, op_id, sku_anterior, sku_novo):
    if sku_novo == sku_anterior:
        return []
    existentes = _tabelas_existentes(cursor)
    if "op_config_snapshots" in existentes:
        cursor.execute(q("SELECT 1 FROM op_config_snapshots WHERE op_id=? LIMIT 1"), (op_id,))
        if cursor.fetchone():
            erro = ValueError(
                "O SKU não pode ser alterado porque a OP possui snapshot de configuração imutável."
            )
            erro.fatos_operacionais = ["op_config_snapshots"]
            raise erro
    fatos = fatos_operacionais_op(cursor, op_id)
    if fatos:
        erro = ValueError(
            "O SKU não pode ser alterado porque a OP já possui fatos operacionais."
        )
        erro.fatos_operacionais = fatos
        raise erro
    return []


def auditar_tentativa_bloqueada(cursor, op_id, sku_anterior, sku_novo, fatos,
                                usuario, perfil, ip_origem=None):
    if "op_operacoes_auditoria" not in _tabelas_existentes(cursor):
        return
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    detalhe = {"sku_anterior": sku_anterior, "sku_novo": sku_novo, "fatos": fatos}
    serializado = json.dumps(detalhe, ensure_ascii=False, sort_keys=True)
    cursor.execute(q("""INSERT INTO op_operacoes_auditoria(
        op_id,tipo,idempotency_key,usuario,perfil,motivo,etapa_destino,
        status_anterior,status_posterior,preflight_json,efeitos_json,
        resultado_json,ip_origem,criado_em
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""), (
        op_id, "ALTERACAO_SKU_BLOQUEADA", f"sku-lock:{op_id}:{uuid4().hex}",
        usuario or "Usuario", perfil or "desconhecido",
        "OP possui fatos operacionais persistidos.", None, None, None,
        serializado, "{}", serializado, ip_origem, agora,
    ))
