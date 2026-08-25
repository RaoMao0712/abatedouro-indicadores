"""PDF A4 analítico para conferência e fechamento da Embalagem Secundária."""

from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle


def _texto(valor, padrao="-"):
    return escape(str(valor if valor not in (None, "") else padrao))


def _numero(valor, casas=3):
    try:
        return f"{float(valor or 0):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "0,000"


def gerar_relatorio_conferencia_embalagem_pdf(op, conferencia, usuario_emissao):
    buffer = BytesIO()
    pagina = landscape(A4)
    estilos = getSampleStyleSheet()
    normal = ParagraphStyle("normal-emb", parent=estilos["BodyText"], fontName="Helvetica", fontSize=7.2, leading=9)
    pequeno = ParagraphStyle("pequeno-emb", parent=normal, fontSize=6.2, leading=7.5, textColor=colors.HexColor("#475467"))
    titulo = ParagraphStyle("titulo-emb", parent=estilos["Title"], fontName="Helvetica-Bold", fontSize=15, leading=18,
                            textColor=colors.HexColor("#143D59"))
    subtitulo = ParagraphStyle("subtitulo-emb", parent=normal, fontSize=8.5, leading=11)
    direita = ParagraphStyle("direita-emb", parent=normal, alignment=TA_RIGHT)
    centro = ParagraphStyle("centro-emb", parent=normal, alignment=TA_CENTER)

    def rodape(canvas, documento):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D0D5DD"))
        canvas.line(10 * mm, 9 * mm, pagina[0] - 10 * mm, 9 * mm)
        canvas.setFont("Helvetica", 6.5)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(10 * mm, 5.5 * mm, f"FrigoDatta · Conferência analítica da OP #{op.get('id', '-')}")
        canvas.drawRightString(pagina[0] - 10 * mm, 5.5 * mm, f"Página {documento.page}")
        canvas.restoreState()

    frame = Frame(9 * mm, 12 * mm, pagina[0] - 18 * mm, pagina[1] - 20 * mm, id="conteudo")
    documento = BaseDocTemplate(buffer, pagesize=pagina, leftMargin=9 * mm, rightMargin=9 * mm,
                                topMargin=8 * mm, bottomMargin=12 * mm, title=f"Conferência OP {op.get('id', '')}")
    documento.addPageTemplates(PageTemplate(id="a4-paisagem", frames=[frame], onPage=rodape))

    ultima = conferencia.get("ultima_conferencia") or {}
    conferido_por = ultima.get("usuario") or usuario_emissao or "Não confirmada"
    confirmado_em = ultima.get("confirmado_em") or "Prévia ainda não confirmada"
    totais = conferencia["totais"]
    elementos = [
        Paragraph("Conferência Analítica das Caixas", titulo),
        Paragraph(
            f"<b>OP:</b> #{_texto(op.get('id'))} &nbsp;&nbsp; <b>Data:</b> {_texto(op.get('data'))} &nbsp;&nbsp; "
            f"<b>Produto:</b> {_texto(op.get('sku') or op.get('produto'))} &nbsp;&nbsp; "
            f"<b>Lote:</b> {_texto(op.get('lote') or op.get('codigo_lote'))}<br/>"
            f"<b>Conferência:</b> {_texto(conferido_por)} · {_texto(confirmado_em)} &nbsp;&nbsp; "
            f"<b>Versão:</b> {_texto(conferencia.get('hash'))}", subtitulo),
        Spacer(1, 3 * mm),
    ]

    dados = [[
        Paragraph("Caixa", centro), Paragraph("Hora", centro), Paragraph("Bruto", centro),
        Paragraph("Tara", centro), Paragraph("Líquido", centro), Paragraph("Bandejas", centro),
        Paragraph("Status", centro), Paragraph("Usuário", centro),
    ]]
    inativos = {"ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO"}
    for caixa in conferencia.get("caixas", []):
        alerta = "<br/><font color='#B54708'><b>Possível duplicidade</b></font>" if caixa.get("possivel_duplicidade") else ""
        metadados = (
            f"<br/><font size='6'>Fab. {_texto(caixa.get('data_fabricacao'))} · "
            f"Val. {_texto(caixa.get('data_validade'))} · "
            f"Lote {_texto(caixa.get('lote') or caixa.get('codigo_lote'))}</font>"
        )
        criado = str(caixa.get("criado_em") or "")
        status = str(caixa.get("status") or "-")
        if status.upper() in inativos:
            status = f"<font color='#B42318'><b>{_texto(status)}</b></font>"
        else:
            status = f"<b>{_texto(status)}</b>"
        dados.append([
            Paragraph(f"<b>{_texto(caixa.get('codigo_caixa') or caixa.get('id'))}</b>{metadados}{alerta}", pequeno),
            Paragraph(_texto(criado[11:16] if len(criado) >= 16 else criado), centro),
            Paragraph(_numero(caixa.get("peso_bruto")), direita),
            Paragraph(_numero(caixa.get("peso_tara")), direita),
            Paragraph(_numero(caixa.get("peso_liquido")), direita),
            Paragraph(_numero(caixa.get("quantidade_bandejas"), 0), direita),
            Paragraph(status, centro),
            Paragraph(_texto(caixa.get("usuario_lancamento")), normal),
        ])

    tabela = Table(dados, repeatRows=1, colWidths=[52 * mm, 18 * mm, 23 * mm, 20 * mm, 23 * mm, 21 * mm, 28 * mm, 43 * mm])
    estilo_tabela = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#143D59")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D0D5DD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for indice, caixa in enumerate(conferencia.get("caixas", []), start=1):
        if str(caixa.get("status") or "").upper() in inativos:
            estilo_tabela.append(("BACKGROUND", (0, indice), (-1, indice), colors.HexColor("#FEE4E2")))
    tabela.setStyle(TableStyle(estilo_tabela))
    elementos.extend([tabela, Spacer(1, 4 * mm)])

    resumo = [[Paragraph("Resumo para fechamento da OP", ParagraphStyle("resumo-t", parent=titulo, fontSize=11, leading=13)), ""],
              [Paragraph(
                  f"<b>Caixas ativas:</b> {totais['caixas_ativas']} &nbsp;&nbsp; "
                  f"<b>Estornadas:</b> {totais['caixas_estornadas']} &nbsp;&nbsp; "
                  f"<b>Bandejas:</b> {_numero(totais['bandejas'], 0)} &nbsp;&nbsp; "
                  f"<b>Possíveis duplicidades:</b> {len(conferencia.get('duplicidades', []))}<br/>"
                  f"<b>Peso bruto:</b> {_numero(totais['peso_bruto'])} kg &nbsp;&nbsp; "
                  f"<b>Tara:</b> {_numero(totais['peso_tara'])} kg &nbsp;&nbsp; "
                  f"<b>Peso líquido:</b> {_numero(totais['peso_liquido'])} kg &nbsp;&nbsp; "
                  f"<b>Saldo pendente:</b> {_numero(totais.get('saldo_pendente'), 0)} bandejas", subtitulo), ""],
              [Paragraph("Conferido por: ________________________________", subtitulo),
               Paragraph("Data: ____/____/________ &nbsp;&nbsp; Assinatura: ________________________________", subtitulo)]]
    bloco = Table(resumo, colWidths=[132 * mm, 132 * mm])
    bloco.setStyle(TableStyle([
        ("SPAN", (0, 0), (1, 0)),
        ("SPAN", (0, 1), (1, 1)),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#98A2B3")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2F8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elementos.append(bloco)
    documento.build(elementos)
    return buffer.getvalue()
