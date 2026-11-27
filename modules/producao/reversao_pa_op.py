"""Reversão de caixa e PA após os adaptadores de dependências posteriores."""

from database import q
from modules.expedicao.estornos_embalagem import (
    _bloqueio_sql, _buscar_bloqueios, _carregar_contexto, _inserir_evento_estoque,
)
from modules.label_printing.services import invalidar_jobs_caixa_cursor


def reverter_caixa_cursor(cursor, op_id, caixa_id, *, operacao_id, usuario, perfil, motivo, agora,
                         documentos_revertidos=(), checkpoint=None):
    """Preserva a composição e compensa apenas a formação registrada."""
    _, caixa, _ = _carregar_contexto(cursor, op_id, caixa_id)
    bloqueios = _buscar_bloqueios(cursor, caixa, documentos_revertidos=documentos_revertidos)
    cursor.execute(q("SELECT pallet_id FROM pallet_caixas_atuais WHERE caixa_id=?" + _bloqueio_sql()),
                   (caixa_id,))
    for vinculo in cursor.fetchall():
        bloqueios.append(f"Pallet #{vinculo['pallet_id']} ainda vinculado.")
    if bloqueios:
        raise ValueError(f"Caixa #{caixa_id}: " + " ".join(bloqueios))
    cursor.execute(q("""SELECT e.* FROM estoque_eventos e
        WHERE e.caixa_id=? AND e.acao='FORMACAO_ESTOQUE' AND NOT EXISTS (
            SELECT 1 FROM estoque_eventos comp WHERE comp.evento_origem_id=e.id
        ) ORDER BY e.id""" + _bloqueio_sql()), (caixa_id,))
    formacoes = cursor.fetchall()
    if len(formacoes) > 1 or (not formacoes and caixa["estoque_operacional"]):
        raise ValueError(f"Caixa #{caixa_id}: formação de PA incompatível com o estado operacional.")
    formacao = formacoes[0] if formacoes else None
    if formacao:
        _inserir_evento_estoque(
            cursor, caixa, motivo, f"{operacao_id}:PA:{caixa_id}", usuario, perfil, formacao,
        )
    if checkpoint:
        checkpoint("apos_pa")
    cursor.execute(q("""UPDATE pa_caixas SET status='Estornada', disponibilidade='ESTORNADO',
        estoque_operacional=0, estornada_em=?, estornada_por=?, estorno_motivo=?,
        versao=COALESCE(versao,0)+1 WHERE id=?"""), (agora, usuario, motivo, caixa_id))
    if cursor.rowcount != 1:
        raise RuntimeError(f"Caixa #{caixa_id}: não foi possível invalidar a posição.")
    invalidar_jobs_caixa_cursor(cursor, caixa_id, motivo="REPROCESSAMENTO_OP")
    return {"caixa_id": caixa_id, "formacao_origem_id": formacao["id"] if formacao else None}
