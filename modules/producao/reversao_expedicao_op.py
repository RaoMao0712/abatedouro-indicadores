"""Estorno de itens de expedição sob a transação da recuperação."""

from database import DATABASE_URL, q
from modules.cmv.services import estornar_saida
from modules.expedicao.estoque_service import (
    compensar_estoque_item_romaneio_cursor, registrar_evento_romaneio,
)
from modules.pedidos_venda.services import estornar_atendimento_item_cursor


def eventos_cmv_item_cursor(cursor, item_id, documento, *, bloquear=False):
    lock = " FOR UPDATE" if bloquear and DATABASE_URL else ""
    cursor.execute(q("""SELECT id,origem_tipo,origem_id,quantidade,custo_total FROM cmv_eventos
        WHERE tipo='VENDA' AND (
            (origem_tipo='EXPEDICAO_ITEM' AND origem_id=?)
            OR (documento=? AND (origem_tipo IS NULL OR origem_tipo<>'EXPEDICAO_ITEM'))
        ) ORDER BY id""" + lock), (str(item_id), str(documento)))
    return [dict(evento) for evento in cursor.fetchall()]


def reverter_item_expedicao_cursor(cursor, op_id, item_id, *, operacao_id, usuario,
                                  motivo, agora, checkpoint=None):
    lock = " FOR UPDATE" if DATABASE_URL else ""
    cursor.execute(q("SELECT * FROM expedicao_itens WHERE id=?" + lock), (item_id,))
    item = cursor.fetchone()
    if not item or not item["ativo"]:
        raise ValueError(f"Item de expedição #{item_id} não está ativo.")
    expedicao_id = item["expedicao_id"]
    cursor.execute(q("SELECT * FROM expedicoes WHERE id=?" + lock), (expedicao_id,))
    romaneio = cursor.fetchone()
    if not romaneio or romaneio["status"] != "Concluído":
        raise ValueError(f"Item #{item_id}: somente baixas concluídas podem ser compensadas.")
    if romaneio["tipo_movimentacao"] not in {"TRANSFERENCIA", "VENDA_DIRETA"}:
        raise ValueError(f"Item #{item_id}: modalidade do romaneio sem adaptador de reversão.")
    cursor.execute(q("SELECT * FROM pa_caixas WHERE id=?" + lock), (item["caixa_id"],))
    caixa = cursor.fetchone()
    cursor.execute(q("SELECT op_id FROM pa_caixa_composicao WHERE caixa_id=?" + lock), (item["caixa_id"],))
    if not caixa or {linha["op_id"] for linha in cursor.fetchall()} != {op_id}:
        raise ValueError(f"Item #{item_id}: a OP de origem não é exclusiva na composição.")
    if item["origem_tipo"] == "INVENTARIO_LEGADO_AGREGADO":
        raise ValueError(f"Item #{item_id}: baixa de PNC agregado exige conciliação própria.")

    cmv_revertido = []
    if romaneio["tipo_movimentacao"] == "VENDA_DIRETA":
        numero_documento = str(romaneio["numero_romaneio"] or expedicao_id)
        for evento in eventos_cmv_item_cursor(cursor, item_id, numero_documento, bloquear=True):
            if evento["origem_tipo"] != "EXPEDICAO_ITEM":
                raise ValueError(
                    f"CMV #{evento['id']}: documento {numero_documento} sem atribuição ao item #{item_id}."
                )
            compensacao, _ = estornar_saida(
                evento["id"], data_evento=agora[:10], idempotency_key=f"{operacao_id}:CMV:{evento['id']}",
                justificativa=motivo, usuario=usuario, cursor=cursor,
            )
            cmv_revertido.append(compensacao["id"])
    pedido = estornar_atendimento_item_cursor(cursor, expedicao_id, item_id, motivo)
    if checkpoint:
        checkpoint("apos_venda")
    compensar_estoque_item_romaneio_cursor(cursor, expedicao_id, {
        **dict(item), "disponibilidade": caixa["disponibilidade"], "condicao": caixa["condicao"],
        "unidade_atual": caixa["unidade_estoque"],
        "pacotes_reservados_atuais": caixa["quantidade_pacotes_reservados"],
        "quantidade_bandejas": caixa["quantidade_bandejas"], "peso_liquido": caixa["peso_liquido"],
    }, motivo)
    cursor.execute(q("""UPDATE expedicao_itens SET ativo=0,removido_em=?,removido_por=?,motivo_remocao=?
        WHERE id=? AND COALESCE(ativo,1)=1"""), (agora, usuario, motivo, item_id))
    if cursor.rowcount != 1:
        raise ValueError(f"Item #{item_id}: vínculo operacional mudou durante a reversão.")
    dados = {"op_id": op_id, "item_id": item_id, "caixa_id": caixa["id"],
             "pedido_id": pedido, "cmv_compensado": cmv_revertido}
    registrar_evento_romaneio(
        cursor, expedicao_id, "ESTORNO_ITEM_REPROCESSAMENTO",
        estado_anterior=romaneio["status"], estado_novo=romaneio["status"],
        dados_alterados=dados, justificativa=motivo,
        idempotency_key=f"{operacao_id}:EXPEDICAO:{item_id}",
    )
    return dados
