from io import BytesIO
from pathlib import Path
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle

def gerar_pdf(rc):
    b=BytesIO(); doc=SimpleDocTemplate(b,pagesize=A4,leftMargin=14*mm,rightMargin=14*mm,topMargin=18*mm,bottomMargin=15*mm,title=rc["numero"]); s=getSampleStyleSheet(); story=[Paragraph("FRIGODATTA — REQUISIÇÃO DE COMPRA",s["Title"]),Paragraph(f"<b>{escape(rc['numero'])}</b> — {escape(rc['status'])}",s["Heading2"]),Spacer(1,4*mm)]
    meta=[["Data",str(rc["criado_em"]),"Prioridade",rc["prioridade"]],["Solicitante",rc["solicitante_nome_snapshot"],"Setor",rc["setor"]],["Origem",rc["tipo_origem"].replace("_"," "),"Documento",rc["origem_numero_snapshot"] or "-"],["Contexto",Paragraph(escape(rc["origem_descricao_snapshot"]),s["BodyText"]),"Status",rc["status"]]]
    t=Table(meta,colWidths=[25*mm,65*mm,25*mm,65*mm]); t.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.grey),("BACKGROUND",(0,0),(0,-1),colors.HexColor("#E8F0EB")),("BACKGROUND",(2,0),(2,-1),colors.HexColor("#E8F0EB")),("VALIGN",(0,0),(-1,-1),"TOP")])) ; story += [t,Spacer(1,5*mm)]
    rows=[["Descrição","Un.","Quantidade","Custo estimado","Cadastro"]]
    for i in rc["itens"]: rows.append([Paragraph(escape(i["descricao_snapshot"]),s["BodyText"]),i["unidade_snapshot"],str(i["quantidade_solicitada"]),("R$ "+str(i["custo_estimado_unitario"])) if i["custo_estimado_unitario"] is not None else "-","Pendente" if i["pendente_cadastro"] else "Cadastrado"])
    ti=Table(rows,repeatRows=1,colWidths=[76*mm,18*mm,28*mm,32*mm,28*mm]); ti.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#173B2A")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("VALIGN",(0,0),(-1,-1),"TOP")])) ; story += [ti,Spacer(1,5*mm)]
    if rc.get("justificativa"): story.append(Paragraph("<b>Justificativa:</b> "+escape(rc["justificativa"]),s["BodyText"]))
    aprov="Aprovada em %s por usuário #%s"%(rc["aprovado_em"],rc["aprovado_por"]) if rc.get("aprovado_em") else "Aguardando decisão / não aprovada"
    story += [Spacer(1,12*mm),Paragraph("<b>Aprovação:</b> "+escape(aprov),s["BodyText"]),Spacer(1,14*mm),Table([["____________________________","","____________________________"],["Solicitante","","Aprovador"]],colWidths=[80*mm,20*mm,80*mm],style=[("ALIGN",(0,0),(-1,-1),"CENTER")]),Spacer(1,5*mm),Paragraph("Documento de necessidade de aquisição externa. Não movimenta estoque nem gera lançamento financeiro.",ParagraphStyle("nota",parent=s["Italic"],fontSize=8,textColor=colors.HexColor("#173B2A")))]
    doc.build(story); return b.getvalue()
