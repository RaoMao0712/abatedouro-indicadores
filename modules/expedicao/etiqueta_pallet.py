"""Representação visual e fotografia de leitura da etiqueta logística do pallet."""

import base64

from reportlab.graphics import renderSVG
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing


def _svg_data(drawing):
    bruto = renderSVG.drawToString(drawing)
    if isinstance(bruto, str):
        bruto = bruto.encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(bruto).decode("ascii")


def codigo_barras_data_url(codigo):
    desenho = createBarcodeDrawing(
        "Code128", value=str(codigo), barHeight=44, barWidth=1.15,
        humanReadable=True, quiet=True,
    )
    return _svg_data(desenho)


def qr_data_url(payload):
    widget = QrCodeWidget(str(payload))
    limites = widget.getBounds()
    largura, altura = limites[2] - limites[0], limites[3] - limites[1]
    desenho = Drawing(110, 110, transform=[110 / largura, 0, 0, 110 / altura, 0, 0])
    desenho.add(widget)
    return _svg_data(desenho)


def montar_etiqueta(pallet, detalhe_url, versao):
    caixas = pallet.get("caixas", [])
    unidades = sorted({str(item.get("unidade_estoque") or "CAIXA") for item in caixas})
    produtos = []
    fatores_inteira = set()
    for item in caixas:
        produto = str(item.get("sku") or "-").strip()
        fator = int(item.get("galinhas_por_pacote") or 0)
        if produto.casefold() == "galinha inteira" and fator in {1, 2}:
            produto = f"{produto} V{fator}"
            fatores_inteira.add(fator)
        if produto not in produtos:
            produtos.append(produto)
    aves_inteiras = sum(
        int(item.get("quantidade_galinhas") or 0)
        for item in caixas
        if str(item.get("sku") or "").strip().casefold() == "galinha inteira"
    )
    caixas_equivalentes = aves_inteiras / 8 if aves_inteiras else None
    padrao_caixas = None
    if fatores_inteira == {2}:
        padrao_caixas = "Padrão: 8 aves por caixa (4 pacotes V2)"
    elif fatores_inteira:
        padrao_caixas = "Padrão: 8 aves por caixa"
    mistos = []
    if len(pallet.get("ops", [])) > 1:
        mistos.append("MISTO POR OP")
    if len(pallet.get("produtos", [])) > 1:
        mistos.append("MISTO POR PRODUTO")
    if len(pallet.get("condicoes", [])) > 1:
        mistos.append("MISTO POR CONDIÇÃO")
    peso_bruto = sum(float(item.get("peso_bruto") or item.get("peso_liquido") or 0) for item in caixas)
    return {
        "pallet": pallet,
        "versao": int(versao),
        "qr_payload": detalhe_url,
        "qr_data_url": qr_data_url(detalhe_url),
        "barcode_data_url": codigo_barras_data_url(pallet["codigo"]),
        "unidades_texto": " / ".join(unidades) or "-",
        "produtos_texto": " / ".join(produtos) or pallet.get("produtos_texto") or "-",
        "caixas_equivalentes": caixas_equivalentes,
        "padrao_caixas": padrao_caixas,
        "peso_bruto": peso_bruto,
        "mistos": mistos,
    }
