"""Servicos de etiqueta para caixas pesadas na OP.

Padrao inicial do codigo de barras:
FD-OP00001-CX001-LOTE-OP-00001

O conteudo inclui estabelecimento, OP, numero sequencial da caixa e lote.
Foi pensado para Code 128/Zebra e nao envia dados para impressora nesta sprint.
"""

from datetime import datetime


ESTABELECIMENTO_PADRAO = "FrigoDatta"


def _valor_linha(registro, chave, padrao=""):
    try:
        valor = registro[chave]
    except Exception:
        valor = None

    if valor is None:
        return padrao

    return valor


def formatar_peso(valor):
    try:
        numero = float(valor or 0)
    except Exception:
        numero = 0

    return f"{numero:.3f} kg"


def formatar_data(valor):
    texto = str(valor or "").strip()
    if not texto:
        return ""

    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            data = datetime.strptime(texto[:19], formato)
            if formato == "%Y-%m-%d":
                return data.strftime("%d/%m/%Y")
            return data.strftime("%d/%m/%Y %H:%M")
        except ValueError:
            pass

    return texto


def gerar_codigo_barras(op_id, numero_caixa, lote):
    return f"FD-OP{int(op_id):05d}-CX{int(numero_caixa or 0):03d}-LOTE-{lote}"


def escapar_zpl(texto):
    return str(texto or "").replace("^", "").replace("~", "").strip()


def gerar_zpl(payload):
    status_cancelada = "CANCELADA" if payload["cancelada"] else ""
    linhas = [
        "^XA",
        "^CI28",
        "^FO30,25^A0N,32,32^FDFRIGODATTA^FS",
        f"^FO30,65^A0N,26,26^FD{escapar_zpl(payload['produto'])}^FS",
        f"^FO30,105^A0N,24,24^FDOP {payload['op']}  CX {payload['numero_caixa']}^FS",
        f"^FO30,140^A0N,24,24^FDLote: {escapar_zpl(payload['lote'])}^FS",
        f"^FO30,175^A0N,24,24^FDFab: {payload['data_fabricacao_formatada']} Val: {payload['validade_formatada']}^FS",
        f"^FO30,210^A0N,28,28^FDPeso liq: {payload['peso_liquido_formatado']}^FS",
        f"^FO30,250^BY2^BCN,80,Y,N,N^FD{escapar_zpl(payload['codigo_barras'])}^FS",
    ]

    if status_cancelada:
        linhas.append("^FO30,350^A0N,36,36^FDCANCELADA^FS")

    linhas.append("^XZ")
    return "\n".join(linhas)


def montar_payload_etiqueta(op, caixa, estabelecimento=ESTABELECIMENTO_PADRAO):
    if not op or not caixa:
        return None

    op_id = _valor_linha(op, "id")
    produto = _valor_linha(op, "sku") or "Galinha Cortada"
    lote = f"OP-{int(op_id):05d}"
    numero_caixa = int(_valor_linha(caixa, "op_numero_caixa") or 0)
    status = _valor_linha(caixa, "status") or "Em estoque"
    cancelada = status == "Cancelada"
    data_fabricacao = _valor_linha(caixa, "data_fabricacao") or _valor_linha(op, "data")
    validade = _valor_linha(caixa, "data_validade") or ""
    peso_bruto = float(_valor_linha(caixa, "peso_bruto", 0) or 0)
    tara = float(_valor_linha(caixa, "peso_tara", 0) or 0)
    peso_liquido = float(_valor_linha(caixa, "peso_liquido", 0) or 0)
    data_hora_pesagem = _valor_linha(caixa, "data_hora_pesagem") or _valor_linha(caixa, "criado_em")

    payload = {
        "estabelecimento": estabelecimento,
        "produto": produto,
        "op": op_id,
        "lote": lote,
        "validade": validade,
        "validade_formatada": formatar_data(validade),
        "data_fabricacao": data_fabricacao,
        "data_fabricacao_formatada": formatar_data(data_fabricacao),
        "numero_caixa": numero_caixa,
        "codigo_caixa": _valor_linha(caixa, "codigo_caixa"),
        "peso_bruto": peso_bruto,
        "peso_bruto_formatado": formatar_peso(peso_bruto),
        "tara": tara,
        "tara_formatada": formatar_peso(tara),
        "peso_liquido": peso_liquido,
        "peso_liquido_formatado": formatar_peso(peso_liquido),
        "data_hora_pesagem": data_hora_pesagem,
        "data_hora_pesagem_formatada": formatar_data(data_hora_pesagem),
        "status": status,
        "cancelada": cancelada,
        "codigo_barras": gerar_codigo_barras(op_id, numero_caixa, lote),
    }
    payload["zpl"] = gerar_zpl(payload)
    return payload
