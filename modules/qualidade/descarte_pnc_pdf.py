"""PDF oficial do romaneio de saída para descarte, sempre baseado no snapshot."""

from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from config import EMPRESA_EMITENTE, ESTABELECIMENTO_DOCUMENTO, IDENTIFICACAO_TECNOLOGIA

AZUL = colors.HexColor("#184d69")
TINTA = colors.HexColor("#26343a")
FUNDO = colors.HexColor("#eef3f5")
LINHA = colors.HexColor("#cbd5d9")


def _texto(valor, padrao="Não informado"):
    return str(valor or "").strip() or padrao


def _data_hora(valor):
    try:
        return datetime.fromisoformat(str(valor)).strftime("%d/%m/%Y às %H:%M")
    except (TypeError, ValueError):
        return _texto(valor)


def _numero(valor, casas=0):
    texto = f"{float(valor or 0):,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


class _Documento(SimpleDocTemplate):
    def __init__(self, destino, snapshot, logo):
        super().__init__(destino, pagesize=A4, leftMargin=13*mm, rightMargin=13*mm,
                         topMargin=34*mm, bottomMargin=18*mm,
                         title="Romaneio de Saída para Descarte de Produto Não Conforme",
                         author=snapshot.get("usuario_emissor"))
        self.snapshot, self.logo = snapshot, logo

    def afterPage(self):
        canvas = self.canv; canvas.saveState()
        if self.logo and Path(self.logo).exists():
            canvas.drawImage(self.logo, 13*mm, 275*mm, width=14*mm, height=14*mm,
                             preserveAspectRatio=True, mask="auto")
        canvas.setFillColor(AZUL); canvas.setFont("Helvetica-Bold", 9.5)
        canvas.drawString(30*mm, 284*mm, ESTABELECIMENTO_DOCUMENTO)
        canvas.setFillColor(colors.HexColor("#607078")); canvas.setFont("Helvetica", 7.5)
        canvas.drawString(30*mm, 279.5*mm, EMPRESA_EMITENTE)
        canvas.setStrokeColor(AZUL); canvas.line(13*mm, 273*mm, 197*mm, 273*mm)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(13*mm, 8*mm, IDENTIFICACAO_TECNOLOGIA)
        canvas.drawCentredString(105*mm, 8*mm, f"Emitido por: {_texto(self.snapshot.get('usuario_emissor'))}")
        canvas.drawRightString(197*mm, 8*mm, f"Página {canvas.getPageNumber()}")
        canvas.restoreState()


def gerar_romaneio_descarte_pdf(snapshot, logo=None):
    logo = logo or str(Path(__file__).resolve().parents[2] / "static" / "imagens" / "logo.png")
    buffer = BytesIO(); doc = _Documento(buffer, snapshot, logo)
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=estilos["Title"], fontName="Helvetica-Bold",
        fontSize=13, leading=16, textColor=AZUL, alignment=TA_CENTER, spaceAfter=2*mm)
    normal = ParagraphStyle("normal", parent=estilos["Normal"], fontSize=8, leading=10, textColor=TINTA)
    pequeno = ParagraphStyle("pequeno", parent=normal, fontSize=7, leading=8.5)
    cabecalho = ParagraphStyle("cabecalho", parent=pequeno, fontName="Helvetica-Bold",
                               textColor=colors.white, alignment=TA_CENTER)
    alerta = ParagraphStyle("alerta", parent=normal, fontName="Helvetica-Bold", fontSize=9,
                            alignment=TA_CENTER, textColor=colors.HexColor("#8b1e1e"))
    p = lambda valor, estilo=normal: Paragraph(escape(_texto(valor)), estilo)
    pb = lambda valor, estilo=normal: Paragraph(f"<b>{escape(_texto(valor))}</b>", estilo)
    historia = [Paragraph("ROMANEIO DE SAÍDA PARA DESCARTE DE PRODUTO NÃO CONFORME", titulo),
                Paragraph(f"Nº {escape(_texto(snapshot.get('numero')))}", titulo), Spacer(1, 2*mm)]
    meta = [
        ["Emissão eletrônica", _data_hora(snapshot.get("lancado_em")), "Saída física", _data_hora(snapshot.get("saida_fisica_em"))],
        ["Produto não conforme", snapshot.get("pnc_numero"), "Origem", snapshot.get("origem")],
        ["Produto", snapshot.get("produto"), "Apresentação", snapshot.get("apresentacao")],
        ["Característica/motivo", snapshot.get("motivo"), "Destino", snapshot.get("destino")],
        ["Motorista", snapshot.get("motorista"), "CPF", snapshot.get("motorista_cpf")],
        ["Placa", snapshot.get("placa"), "Ref. documento manual", snapshot.get("referencia_manual")],
        ["Responsável pela entrega", snapshot.get("responsavel_entrega"), "Responsável pelo recebimento", snapshot.get("responsavel_recebimento")],
    ]
    tabela = Table([[pb(a),p(b),pb(c),p(d)] for a,b,c,d in meta],
                   colWidths=[34*mm,58*mm,34*mm,58*mm])
    tabela.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.35,LINHA),("BACKGROUND",(0,0),(0,-1),FUNDO),
        ("BACKGROUND",(2,0),(2,-1),FUNDO),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
        ("LEFTPADDING",(0,0),(-1,-1),4),("RIGHTPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    historia += [tabela, Spacer(1,3*mm)]
    saida=snapshot.get("saida",{}); anterior=snapshot.get("saldo_anterior",{}); restante=snapshot.get("saldo_remanescente",{})
    linhas=[[p("Quantidade",cabecalho),p("Saldo anterior",cabecalho),p("Baixa",cabecalho),p("Remanescente",cabecalho)]]
    for chave,rotulo,casas,divisor in (("caixas","Caixas",0,1),("bandejas","Bandejas",0,1),("galinhas","Galinhas",0,1),("pacotes","Pacotes",0,1),("peso_g","Peso (kg)",3,1000)):
        if any(int(x.get(chave,0) or 0) for x in (anterior,saida,restante)):
            linhas.append([p(rotulo),p(_numero(anterior.get(chave,0)/divisor,casas)),p(_numero(saida.get(chave,0)/divisor,casas)),p(_numero(restante.get(chave,0)/divisor,casas))])
    quant=Table(linhas,colWidths=[46*mm]*4,repeatRows=1)
    quant.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,LINHA),("BACKGROUND",(0,0),(-1,0),AZUL),
        ("TEXTCOLOR",(0,0),(-1,0),colors.white),("ALIGN",(1,1),(-1,-1),"RIGHT"),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
    historia += [quant,Spacer(1,3*mm),Paragraph("Produto impróprio para consumo — destinação exclusiva para descarte",alerta)]
    if snapshot.get("saida_ja_realizada"):
        historia += [Spacer(1,2*mm),Paragraph("SAÍDA FÍSICA REGISTRADA POSTERIORMENTE NO SISTEMA. A data eletrônica original foi preservada.",alerta)]
    historia += [Spacer(1,3*mm),Paragraph(f"<b>Observações:</b> {escape(_texto(snapshot.get('observacoes'),'-'))}", normal),Spacer(1,12*mm)]
    assinatura = lambda rotulo: Paragraph(f"________________________________<br/>{escape(rotulo)}", pequeno)
    assinaturas=[[assinatura("Responsável pela expedição/entrega"),assinatura("Motorista"),assinatura("Responsável pelo recebimento")],
                [assinatura("Qualidade"),"",assinatura("Gerência")]]
    ass=Table(assinaturas,colWidths=[61.3*mm]*3,rowHeights=[25*mm,25*mm])
    ass.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"BOTTOM")]))
    historia.append(ass); doc.build(historia); return buffer.getvalue()
