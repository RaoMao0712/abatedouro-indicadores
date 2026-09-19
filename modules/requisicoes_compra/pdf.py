from io import BytesIO
from pathlib import Path
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle

VERDE=colors.HexColor("#173B2A")
def _pagina(canvas,doc):
    canvas.saveState(); canvas.setFillColor(VERDE); canvas.setFont("Helvetica-Bold",13); canvas.drawString(14*mm,282*mm,"FRIGODATTA")
    canvas.setFont("Helvetica-Bold",9); canvas.drawString(14*mm,276*mm,"REQUISIÇÃO DE COMPRA")
    canvas.setStrokeColor(VERDE); canvas.line(14*mm,272*mm,196*mm,272*mm)
    canvas.setFillColor(colors.grey); canvas.setFont("Helvetica",7); canvas.drawString(14*mm,9*mm,"Documento de necessidade de aquisição externa")
    canvas.drawRightString(196*mm,9*mm,f"Página {doc.page}"); canvas.restoreState()

def gerar_pdf(rc):
    b=BytesIO(); doc=SimpleDocTemplate(b,pagesize=A4,leftMargin=14*mm,rightMargin=14*mm,topMargin=30*mm,bottomMargin=18*mm,title=rc["numero"]); s=getSampleStyleSheet(); corpo=ParagraphStyle("rc-corpo",parent=s["BodyText"],fontSize=8,leading=10); nu_style=ParagraphStyle("rc-nu",parent=corpo,fontSize=7,leading=8,wordWrap="CJK"); p=lambda valor: Paragraph(escape(str(valor)),corpo); story=[Paragraph(f"<b>{escape(rc['numero'])}</b> — {escape(rc['status'])}",s["Heading2"]),Spacer(1,4*mm)]
    meta=[["Data",p(rc["criado_em"]),"Prioridade",p(rc["prioridade"])],["Solicitante",p(rc["solicitante_nome_snapshot"]),"Setor",p(rc["setor"])],["Origem",p(rc["tipo_origem"].replace("_"," ")),"Documento",p(rc["origem_numero_snapshot"] or "-")],["Contexto",p(rc["origem_descricao_snapshot"]),"Status",p(rc["status"])]]
    t=Table(meta,colWidths=[25*mm,65*mm,25*mm,65*mm]); t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.grey),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#E8F0EB")),("BACKGROUND",(2,0),(2,-1),colors.HexColor("#E8F0EB")),("VALIGN",(0,0),(-1,-1),"TOP")])) ; story += [t,Spacer(1,5*mm)]
    rows=[["Descrição","Un.","Quantidade","NU","Custo estimado","Cadastro"]]
    for i in rc["itens"]: rows.append([p(i["descricao_snapshot"]),i["unidade_snapshot"],str(i["quantidade_solicitada"]),Paragraph(escape(i.get("nu") or "—"),nu_style),("R$ "+str(i["custo_estimado_unitario"])) if i["custo_estimado_unitario"] is not None else "-","Pendente" if i["pendente_cadastro"] else "Cadastrado"])
    ti=Table(rows,repeatRows=1,colWidths=[60*mm,14*mm,24*mm,30*mm,28*mm,26*mm]); ti.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#173B2A")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,0),(-1,-1),8)])) ; story += [ti,Spacer(1,5*mm)]
    if rc.get("justificativa"): story.append(Paragraph("<b>Justificativa:</b> "+escape(rc["justificativa"]),s["BodyText"]))
    aprov="Aprovada em %s por usuário #%s"%(rc["aprovado_em"],rc["aprovado_por"]) if rc.get("aprovado_em") else "Aguardando decisão / não aprovada"
    story += [Spacer(1,12*mm),Paragraph("<b>Aprovação:</b> "+escape(aprov),s["BodyText"]),Spacer(1,14*mm),Table([["____________________________","","____________________________"],["Solicitante","","Aprovador"]],colWidths=[80*mm,20*mm,80*mm],style=[("ALIGN",(0,0),(-1,-1),"CENTER")]),Spacer(1,5*mm),Paragraph("Não movimenta estoque nem gera lançamento financeiro.",ParagraphStyle("nota",parent=s["Italic"],fontSize=8,textColor=VERDE))]
    doc.build(story,onFirstPage=_pagina,onLaterPages=_pagina); return b.getvalue()
