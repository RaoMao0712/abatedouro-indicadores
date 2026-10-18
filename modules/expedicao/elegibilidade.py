"""Regra canônica de elegibilidade de posições para a Expedição."""

from decimal import Decimal, InvalidOperation


TIPOS_CONFORMES = {"TRANSFERENCIA", "VENDA_DIRETA"}
TIPOS_PNC = {"DESCARTE", "DEVOLUCAO", "TRANSFERENCIA_AUTORIZADA"}

MENSAGENS_BLOQUEIO = {
    "POSICAO_INEXISTENTE": "A posição de estoque não foi encontrada.",
    "NAO_OPERACIONAL": "O item está fora do estoque operacional.",
    "STATUS_INCOMPATIVEL": "O status físico do item não permite reserva.",
    "INDISPONIVEL": "Somente produto conforme e disponivel pode entrar em romaneio normal.",
    "RESERVADA_OUTRO_ROMANEIO": "O item está reservado por outro romaneio.",
    "SEM_SALDO": "A quantidade solicitada excede o saldo disponivel.",
    "ITEM_ATIVO_INCOMPATIVEL": "O item já participa de um romaneio ativo incompatível.",
    "CONDICAO_NAO_PERMITIDA": "A condição do produto não permite esta modalidade.",
    "OP_INCOMPATIVEL": "O item não pertence à OP informada.",
    "PNC_BLOQUEADO": "Somente Produto Nao Conforme bloqueado pode entrar neste romaneio.",
}


def _valor(posicao, nome, padrao=None):
    if posicao is None:
        return padrao
    try:
        valor = posicao[nome]
    except (KeyError, IndexError, TypeError):
        valor = getattr(posicao, nome, padrao)
    return padrao if valor is None else valor


def _inteiro(valor):
    try:
        return int(Decimal(str(valor or 0)))
    except (InvalidOperation, TypeError, ValueError):
        return 0


def _resultado(modalidade, codigo=None, saldo=0):
    return {
        "elegivel": codigo is None,
        "codigo_bloqueio": codigo,
        "motivo_bloqueio": MENSAGENS_BLOQUEIO.get(codigo) if codigo else None,
        "modalidade": modalidade,
        "saldo_elegivel": max(0, int(saldo or 0)),
    }


def avaliar_elegibilidade_expedicao(
    posicao, *, tipo_movimentacao, expedicao_id=None, op_compativel=True,
    item_ativo_incompativel=False, quantidade_propria=0, quantidade_solicitada=None,
    pnc_pendente=False,
):
    """Avalia uma posição já lida, inclusive após lock, sem realizar escrita."""
    unidade = str(_valor(posicao, "unidade_estoque", "CAIXA") or "CAIXA").upper()
    modalidade = "PACOTE" if unidade == "PACOTE" else "CAIXA"
    if posicao is None:
        return _resultado(modalidade, "POSICAO_INEXISTENTE")
    if _inteiro(_valor(posicao, "estoque_operacional")) != 1:
        return _resultado(modalidade, "NAO_OPERACIONAL")
    if str(_valor(posicao, "status", "")) != "Em estoque":
        return _resultado(modalidade, "STATUS_INCOMPATIVEL")
    if not op_compativel:
        return _resultado(modalidade, "OP_INCOMPATIVEL")
    if pnc_pendente:
        return _resultado(modalidade, "PNC_BLOQUEADO")

    tipo = str(tipo_movimentacao or "").upper()
    condicao = str(_valor(posicao, "condicao", "") or "").upper()
    disponibilidade = str(_valor(posicao, "disponibilidade", "") or "").upper()
    if tipo in TIPOS_CONFORMES:
        if condicao != "CONFORME":
            return _resultado(modalidade, "PNC_BLOQUEADO")
        disponibilidades = {"DISPONIVEL", "RESERVADO"} if modalidade == "PACOTE" else {"DISPONIVEL"}
    elif tipo in TIPOS_PNC:
        if condicao != "NAO_CONFORME":
            return _resultado(modalidade, "CONDICAO_NAO_PERMITIDA")
        if modalidade == "PACOTE":
            return _resultado(modalidade, "PNC_BLOQUEADO")
        disponibilidades = {"BLOQUEADO"}
    else:
        return _resultado(modalidade, "CONDICAO_NAO_PERMITIDA")
    if disponibilidade not in disponibilidades:
        return _resultado(modalidade, "PNC_BLOQUEADO" if tipo in TIPOS_PNC else "INDISPONIVEL")

    if modalidade == "CAIXA":
        reservado_por = _valor(posicao, "reservado_expedicao_id")
        if reservado_por not in (None, "", expedicao_id):
            return _resultado(modalidade, "RESERVADA_OUTRO_ROMANEIO")
        if item_ativo_incompativel:
            return _resultado(modalidade, "ITEM_ATIVO_INCOMPATIVEL")
        return _resultado(modalidade, saldo=1)

    total = _inteiro(_valor(posicao, "quantidade_pacotes"))
    reservados = _inteiro(_valor(posicao, "quantidade_pacotes_reservados"))
    saldo = total - reservados + _inteiro(quantidade_propria)
    if saldo <= 0:
        return _resultado(modalidade, "SEM_SALDO")
    if quantidade_solicitada is not None and _inteiro(quantidade_solicitada) > saldo:
        return _resultado(modalidade, "SEM_SALDO", saldo)
    return _resultado(modalidade, saldo=saldo)


def exigir_elegibilidade_expedicao(*args, **kwargs):
    resultado = avaliar_elegibilidade_expedicao(*args, **kwargs)
    if not resultado["elegivel"]:
        erro = ValueError(resultado["motivo_bloqueio"])
        erro.codigo_bloqueio = resultado["codigo_bloqueio"]
        raise erro
    return resultado

