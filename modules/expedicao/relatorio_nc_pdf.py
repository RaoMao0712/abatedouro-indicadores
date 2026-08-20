"""PDF executivo para verificação e autorização manual de descarte de PNC."""

from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, Spacer, Table, TableStyle

from config import EMPRESA_EMITENTE
from .relatorio_entregas import AZUL, CINZA, FUNDO, LINHA, TINTA, _Documento
from .relatorio_nc_service import UNIDADES_ROTULOS


def _numero(valor, casas=0):
    texto = f"{float(valor or 0):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def _valor(unidade, valor):
    return _numero(valor, 3 if unidade == "peso_kg" else 0) + (" kg" if unidade == "peso_kg" else "")


def _p(valor, estilo):
    return Paragraph(escape(str(valor or "-")), estilo)


def _secao(secao, estilos):
    dados = [[_p("Característica", estilos["cab"])] +
             [_p(UNIDADES_ROTULOS[u], estilos["cab"]) for u in secao["unidades"]]]
    for linha in secao["linhas"]:
        dados.append([_p(linha["caracteristica"], estilos["normal"])] + [
            Paragraph(_valor(u, linha["quantidades"][u]), estilos["direita"])
            for u in secao["unidades"]
        ])
    dados.append([Paragraph("<b>Total da seção</b>", estilos["normal"])] + [
        Paragraph(f"<b>{_valor(u, secao['totais'][u])}</b>", estilos["direita"])
        for u in secao["unidades"]
    ])
    largura_caracteristica = 137 * mm
    largura_quantidade = (277 * mm - largura_caracteristica) / len(secao["unidades"])
    tabela = Table(dados, colWidths=[largura_caracteristica] +
                  [largura_quantidade] * len(secao["unidades"]), repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), .35, LINHA), ("BACKGROUND", (0, -1), (-1, -1), FUNDO),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    titulo = f"{secao['produto']} - {secao['apresentacao']}"
    return KeepTogether([Paragraph(escape(titulo), estilos["secao"]), tabela, Spacer(1, 3 * mm)])


def gerar_relatorio_nc_pdf(relatorio, logo=None):
    snapshot = relatorio["snapshot"]
    emissao = str(relatorio["emitido_em"]).replace("T", " ")[:16]
    logo = logo or str(Path(__file__).resolve().parents[2] / "static" / "imagens" / "logo.png")
    buffer = BytesIO()
    doc = _Documento(buffer, emissao, relatorio["usuario"], logo,
                     "Relatório de Verificação e Autorização para Descarte de Produtos Não Conformes")
    base = getSampleStyleSheet()
    estilos = {
        "titulo": ParagraphStyle("rnc_titulo", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=14, leading=17, textColor=AZUL, alignment=TA_CENTER, spaceAfter=2 * mm),
        "sub": ParagraphStyle("rnc_sub", parent=base["Normal"], fontSize=8.5, leading=11,
            textColor=CINZA, alignment=TA_CENTER, spaceAfter=3 * mm),
        "normal": ParagraphStyle("rnc_normal", parent=base["Normal"], fontSize=8.5, leading=11, textColor=TINTA),
        "pequeno": ParagraphStyle("rnc_pequeno", parent=base["Normal"], fontSize=7.5, leading=9, textColor=TINTA),
        "direita": ParagraphStyle("rnc_direita", parent=base["Normal"], fontSize=8.5, leading=11,
            textColor=TINTA, alignment=TA_RIGHT),
        "cab": ParagraphStyle("rnc_cab", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8, leading=10, textColor=colors.white, alignment=TA_CENTER),
        "secao": ParagraphStyle("rnc_secao", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=10.5, leading=13, textColor=AZUL, spaceBefore=2 * mm, spaceAfter=1.5 * mm),
    }
    historia = [
        Paragraph("RELATÓRIO DE VERIFICAÇÃO E AUTORIZAÇÃO PARA DESCARTE<br/>DE PRODUTOS NÃO CONFORMES", estilos["titulo"]),
        Paragraph("Documento executivo para decisão da Diretoria", estilos["sub"]),
    ]
    meta = Table([
        [_p("Empresa", estilos["pequeno"]), _p(EMPRESA_EMITENTE, estilos["normal"]),
         _p("Número do relatório", estilos["pequeno"]), _p(relatorio["numero"], estilos["normal"])],
        [_p("Data e hora da emissão", estilos["pequeno"]), _p(emissao, estilos["normal"]),
         _p("Fuso horário", estilos["pequeno"]), _p("America/Manaus", estilos["normal"])],
        [_p("Emitido por", estilos["pequeno"]), _p(relatorio["usuario"], estilos["normal"]),
         _p("Registros verificados", estilos["pequeno"]), _p(snapshot["quantidade_registros"], estilos["normal"])],
    ], colWidths=[40 * mm, 96 * mm, 43 * mm, 98 * mm])
    meta.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .35, LINHA), ("BACKGROUND", (0, 0), (0, -1), FUNDO),
        ("BACKGROUND", (2, 0), (2, -1), FUNDO), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    historia += [meta, Spacer(1, 3 * mm), Paragraph(
        "Este documento apresenta o resultado da verificação física de produtos não conformes, "
        "para análise e decisão da Diretoria. Sua emissão não realiza descarte nem movimenta estoque.",
        estilos["normal"]), Spacer(1, 2 * mm)]
    for secao in snapshot["secoes"]:
        historia.append(_secao(secao, estilos))
    historia += [
        Paragraph("Observações", estilos["secao"]),
        Table([[""]], colWidths=[277 * mm], rowHeights=[18 * mm], style=TableStyle([("BOX", (0, 0), (-1, -1), .6, LINHA)])),
        Paragraph("Decisão da Diretoria", estilos["secao"]),
        Paragraph("(  ) Autorizado para descarte&nbsp;&nbsp;&nbsp;&nbsp; (  ) Não autorizado para descarte&nbsp;&nbsp;&nbsp;&nbsp; "
                  "(  ) Autorizado parcialmente&nbsp;&nbsp;&nbsp;&nbsp; (  ) Outra destinação determinada", estilos["normal"]),
        Spacer(1, 2 * mm),
        Paragraph("<b>Ressalvas, quantidades autorizadas parcialmente ou outra destinação:</b>", estilos["normal"]),
        Table([[""]], colWidths=[277 * mm], rowHeights=[18 * mm], style=TableStyle([("BOX", (0, 0), (-1, -1), .6, LINHA)])),
        Spacer(1, 5 * mm),
        Table([
            ["________________________________________", "________________________________________"],
            ["Responsável pela verificação", "Autorização da Diretoria"],
            ["Nome: _________________________________", "Nome: _________________________________"],
            ["Cargo: _________________________________", "Cargo: _________________________________"],
            ["Assinatura: _____________________________", "Assinatura: _____________________________"],
            ["Data: ____/____/________", "Data: ____/____/________"],
        ], colWidths=[138.5 * mm, 138.5 * mm], style=TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTNAME", (0, 2), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("LEADING", (0, 0), (-1, -1), 11), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])),
    ]
    doc.build(historia)
    return buffer.getvalue()
