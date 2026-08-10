"""PDF oficial do Pedido de Venda Direta em A4 horizontal."""

from io import BytesIO
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle

from config import EMPRESA_EMITENTE, ESTABELECIMENTO_DOCUMENTO, IDENTIFICACAO_TECNOLOGIA
from .services import STATUS, decimal_centavos, decimal_milesimos


def _registrar_fonte():
    caminhos = [
        os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arial.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for caminho in caminhos:
        if os.path.exists(caminho):
            try:
                pdfmetrics.registerFont(TTFont("PedidoSans", caminho))
                return "PedidoSans"
            except Exception:
                pass
    return "Helvetica"


def _registrar_fonte_negrito():
    caminhos = [
        os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "arialbd.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for caminho in caminhos:
        if os.path.exists(caminho):
            try:
                pdfmetrics.registerFont(TTFont("PedidoSansBold", caminho))
                return "PedidoSansBold"
            except Exception:
                pass
    return "Helvetica-Bold"


def _moeda(centavos):
    valor = f"{decimal_centavos(centavos):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor}"


def _qtd(mil):
    return f"{decimal_milesimos(mil):,.3f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _qtd_resumo(mil, unidade):
    valor = decimal_milesimos(mil)
    casas = 0 if valor == valor.to_integral() else 3
    texto = f"{valor:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{texto} {unidade}"


def _totais_comerciais(pedido):
    totais = {}
    for item in pedido["itens"]:
        unidade = str(item.get("unidade_comercial") or item.get("unidade_exibicao") or "").upper()
        totais[unidade] = totais.get(unidade, 0) + int(item.get("quantidade_exibicao_mil") or 0)
    return totais


def _larguras_colunas_itens(largura_disponivel):
    percentuais = (0.15, 0.20, 0.10, 0.06, 0.11, 0.09, 0.11, 0.09)
    larguras = [largura_disponivel * percentual for percentual in percentuais]
    return larguras + [largura_disponivel - sum(larguras)]


def gerar_pdf_pedido(pedido):
    fonte = _registrar_fonte()
    fonte_negrito = _registrar_fonte_negrito()
    buffer = BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=landscape(A4), leftMargin=12*mm, rightMargin=12*mm,
                          topMargin=34*mm, bottomMargin=18*mm, title=f"Pedido {pedido['numero']}")
    estilos = getSampleStyleSheet()
    normal = ParagraphStyle("pedido-normal", parent=estilos["BodyText"], fontName=fonte,
                            fontSize=8.5, leading=11, wordWrap="LTR")
    pequeno = ParagraphStyle("pedido-pequeno", parent=normal, fontSize=7.3, leading=9)
    direita = ParagraphStyle("pedido-direita", parent=normal, alignment=TA_RIGHT)
    item_esquerda = ParagraphStyle("pedido-item-esquerda", parent=normal, splitLongWords=False)
    item_centro = ParagraphStyle("pedido-item-centro", parent=item_esquerda, alignment=TA_CENTER)
    item_direita = ParagraphStyle("pedido-item-direita", parent=item_esquerda, alignment=TA_RIGHT)
    cabecalho_esquerda = ParagraphStyle(
        "pedido-cabecalho-esquerda", parent=pequeno, fontName=fonte_negrito,
        textColor=colors.white,
        leading=8.5, splitLongWords=False)
    cabecalho_centro = ParagraphStyle(
        "pedido-cabecalho-centro", parent=cabecalho_esquerda, alignment=TA_CENTER)
    titulo = ParagraphStyle("pedido-titulo", parent=normal, fontSize=13, leading=15,
                            alignment=TA_CENTER, textColor=colors.HexColor("#123f35"))

    def cabecalho(canvas, documento):
        canvas.saveState(); largura, altura = landscape(A4)
        logo = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static", "imagens", "logo.png")
        if os.path.exists(logo):
            canvas.drawImage(logo, 13*mm, altura-28*mm, width=23*mm, height=18*mm,
                             preserveAspectRatio=True, mask="auto")
        canvas.setFont(fonte, 12); canvas.setFillColor(colors.HexColor("#123f35"))
        canvas.drawCentredString(largura/2, altura-14*mm, ESTABELECIMENTO_DOCUMENTO)
        canvas.setFont(fonte, 8); canvas.setFillColor(colors.black)
        canvas.drawCentredString(largura/2, altura-19*mm, EMPRESA_EMITENTE)
        canvas.drawCentredString(largura/2, altura-24*mm, "PEDIDO DE VENDA DIRETA")
        canvas.setStrokeColor(colors.HexColor("#cc9b2c")); canvas.line(12*mm, altura-29*mm, largura-12*mm, altura-29*mm)
        canvas.setFont(fonte, 7); canvas.setFillColor(colors.HexColor("#555555"))
        canvas.drawString(12*mm, 8*mm, IDENTIFICACAO_TECNOLOGIA)
        canvas.drawRightString(largura-12*mm, 8*mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()

    cliente = pedido["cliente_snapshot"]
    historia = []
    historia.append(Paragraph(f"<b>{pedido['numero']}</b> &nbsp; — &nbsp; {STATUS.get(pedido['status'], pedido['status'])}", titulo))
    historia.append(Spacer(1, 3*mm))
    condicao_detalhe = pedido["condicao_pagamento"]
    if condicao_detalhe == "PRAZO_UNICO":
        condicao_detalhe += f" — vencimento {pedido.get('vencimento_inicial') or '-'} / {pedido.get('prazo_dias') or '-'} dias"
    elif condicao_detalhe == "PARCELADO":
        condicao_detalhe += f" — {pedido.get('numero_parcelas') or '-'} parcelas; início {pedido.get('vencimento_inicial') or '-'}; intervalo {pedido.get('intervalo_dias') or '-'} dias"
    elif condicao_detalhe == "ENTRADA_MAIS_SALDO":
        condicao_detalhe += f" — entrada {_moeda(pedido.get('entrada_centavos') or 0)} / {decimal_milesimos(pedido.get('entrada_percentual_milesimos') or 0)}%; saldo: {pedido.get('condicao_saldo') or '-'}"
    elif pedido.get("descricao_condicao"):
        condicao_detalhe += f" — {pedido['descricao_condicao']}"
    dados = [
        [Paragraph("<b>Cliente</b>", pequeno), Paragraph(cliente.get("razao_social") or "-", normal),
         Paragraph("<b>Data</b>", pequeno), Paragraph(pedido["data_pedido"], normal),
         Paragraph("<b>Previsão</b>", pequeno), Paragraph(pedido.get("previsao_entrega") or "-", normal)],
        [Paragraph("<b>Destino</b>", pequeno), Paragraph(pedido["destino"], normal),
         Paragraph("<b>Responsável</b>", pequeno), Paragraph(pedido["responsavel"], normal),
         Paragraph("<b>Pagamento</b>", pequeno), Paragraph(f"{pedido['forma_pagamento']} / {condicao_detalhe}", normal)],
    ]
    tabela = Table(dados, colWidths=[18*mm, 66*mm, 20*mm, 42*mm, 20*mm, 75*mm])
    tabela.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.35,colors.HexColor("#b8c4c0")),
                               ("BACKGROUND",(0,0),(0,-1),colors.HexColor("#eef4f2")),
                               ("BACKGROUND",(2,0),(2,-1),colors.HexColor("#eef4f2")),
                               ("BACKGROUND",(4,0),(4,-1),colors.HexColor("#eef4f2")),
                               ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LEFTPADDING",(0,0),(-1,-1),4),
                               ("RIGHTPADDING",(0,0),(-1,-1),4), ("TOPPADDING",(0,0),(-1,-1),4),
                               ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    historia += [tabela, Spacer(1, 4*mm)]
    rotulos_cabecalho = (
        "SKU / produto", "Apresentação", "Quantidade", "Un.",
        "Preço/un. comercial", "Desconto", "Total", "Entregue", "Saldo")
    cabecalho_itens = [
        Paragraph(rotulo, cabecalho_esquerda if indice < 2 else cabecalho_centro)
        for indice, rotulo in enumerate(rotulos_cabecalho)
    ]
    linhas_itens = []
    for item in pedido["itens"]:
        produto = item["sku"]
        linhas_itens.append([
            Paragraph(produto, item_esquerda),
            Paragraph(item.get("apresentacao_snapshot") or "-", item_esquerda),
            Paragraph(_qtd(item["quantidade_exibicao_mil"]), item_direita),
            Paragraph(item.get("unidade_exibicao") or item["unidade_comercial"], item_centro),
            Paragraph(_moeda(item["preco_unitario_centavos"]), item_direita),
            Paragraph(_moeda(item["desconto_centavos"]), item_direita),
            Paragraph(_moeda(item["valor_liquido_centavos"]), item_direita),
            Paragraph(_qtd(item["quantidade_entregue_exibicao_mil"]), item_direita),
            Paragraph(_qtd(item["saldo_pendente_exibicao_mil"]), item_direita),
        ])
    def tabela_itens(linhas):
        tabela = Table([cabecalho_itens] + linhas, repeatRows=1, splitByRow=1,
                       colWidths=_larguras_colunas_itens(doc.width))
        tabela.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#123f35")),
            ("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#aeb9b5")),
            ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f7faf9")]),
            ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
        return tabela

    primeira = linhas_itens[:5]
    historia += [tabela_itens(primeira), Spacer(1, 4*mm)]
    restantes = linhas_itens[5:]
    ultimo_lote = primeira
    while restantes:
        lote, restantes = restantes[:9], restantes[9:]
        historia += [PageBreak(), tabela_itens(lote), Spacer(1, 4*mm)]
        ultimo_lote = lote
    if len(linhas_itens) > 5 and len(ultimo_lote) > 5:
        historia.append(PageBreak())
    linhas_quantidades = []
    rotulos = {"AVE": ("TOTAL DE AVES DO PEDIDO", "AVES"), "KG": ("TOTAL EM KG", "KG"),
               "CAIXA": ("TOTAL DE CAIXAS", "CAIXAS"), "PACOTE": ("TOTAL DE PACOTES", "PACOTES")}
    for unidade, quantidade in sorted(_totais_comerciais(pedido).items()):
        rotulo, unidade_saida = rotulos.get(unidade, (f"TOTAL EM {unidade}", unidade))
        linhas_quantidades.append([
            Paragraph(f"<b>{rotulo}</b>", normal),
            Paragraph(f"<b>{_qtd_resumo(quantidade, unidade_saida)}</b>", direita),
        ])
    if linhas_quantidades:
        resumo_quantidades = Table(linhas_quantidades, colWidths=[58*mm,38*mm], hAlign="LEFT")
        resumo_quantidades.setStyle(TableStyle([
            ("GRID",(0,0),(-1,-1),.45,colors.HexColor("#7f9992")),
            ("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#e8f1ee")),
            ("TEXTCOLOR",(0,0),(-1,-1),colors.HexColor("#123f35")),
            ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6),
            ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ]))
        historia += [resumo_quantidades, Spacer(1, 3*mm)]
    totais = Table([[Paragraph("Subtotal", normal), Paragraph(_moeda(pedido["subtotal_centavos"]), direita)],
                    [Paragraph("Desconto geral", normal), Paragraph(_moeda(pedido["desconto_centavos"]), direita)],
                    [Paragraph("<b>Valor total</b>", normal), Paragraph(f"<b>{_moeda(pedido['valor_total_centavos'])}</b>", direita)]],
                   colWidths=[38*mm,35*mm], hAlign="RIGHT")
    totais.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.35,colors.HexColor("#aeb9b5")),
                                ("BACKGROUND",(0,-1),(-1,-1),colors.HexColor("#e8f1ee")),
                                ("LEFTPADDING",(0,0),(-1,-1),5),("RIGHTPADDING",(0,0),(-1,-1),5)]))
    historia += [totais, Spacer(1, 3*mm)]
    if pedido.get("observacoes"):
        historia.append(Paragraph(f"<b>Observações:</b> {pedido['observacoes']}", normal))
    if pedido["romaneios"]:
        lista = ", ".join(f"{r['numero_romaneio']} ({r['status']})" for r in pedido["romaneios"])
        historia.append(Paragraph(f"<b>Romaneios vinculados:</b> {lista}", normal))
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="pedido-body")
    doc.addPageTemplates(PageTemplate(id="pedido", frames=[frame], onPage=cabecalho))
    doc.build(historia)
    return buffer.getvalue()
