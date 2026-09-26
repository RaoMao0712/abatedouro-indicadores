from io import BytesIO
from pathlib import Path
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
from filters import formatar_moeda_br

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
    ajuste=bool(rc.get("tem_ajuste")); moeda=lambda v: formatar_moeda_br(v) if v is not None else "-"
    cab=["Descrição","Un.","Qtd. solicitada"]+(["Qtd. aprovada"] if ajuste else [])+["NU","Custo unit. estimado","Total estimado","Cadastro"]
    rows=[cab]
    for i in rc["itens"]:
        efetiva=i.get("quantidade_efetiva",i["quantidade_solicitada"]); total=i.get("total_estimado_aprovado") if ajuste else i.get("total_estimado_solicitado")
        rows.append([p(i["descricao_snapshot"]),i["unidade_snapshot"],str(i["quantidade_solicitada"])]+([str(efetiva)] if ajuste else [])+[Paragraph(escape(i.get("nu") or "—"),nu_style),(i.get("custo_unitario_formatado") or "-"),moeda(total),"Pendente" if i["pendente_cadastro"] else "Cadastrado"])
    larguras=[44,10,18,18,22,24,24,22] if ajuste else [50,11,20,28,26,26,21]
    ti=Table(rows,repeatRows=1,colWidths=[w*mm for w in larguras]); ti.setStyle(TableStyle([("GRID",(0,0),(-1,-1),.4,colors.grey),("BACKGROUND",(0,0),(-1,0),colors.HexColor("#173B2A")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,0),(-1,-1),8)])) ; story += [ti,Spacer(1,3*mm)]
    if ajuste and rc.get("ajuste_financeiro"): story.append(Paragraph("<b>Valor estimado solicitado"+(" (parcial)" if rc.get("total_parcial") else "")+":</b> "+moeda(rc.get("total_estimado_solicitado")),s["BodyText"]))
    story.append(Paragraph("<b>"+("Total geral aprovado" if ajuste else "Total geral estimado")+(" parcial" if rc.get("total_parcial") else "")+":</b> "+moeda(rc.get("total_estimado_aprovado") if ajuste else rc.get("total_estimado_solicitado")),s["BodyText"]))
    if rc.get("itens_sem_custo"): story.append(Paragraph(f"{rc['itens_sem_custo']} de {len(rc['itens'])} item(ns) sem custo estimado; não compõem o total (não são tratados como custo zero).",corpo))
    story += [Paragraph("Esta RC não movimenta estoque nem gera lançamento financeiro.",corpo),Spacer(1,3*mm)]
    if rc.get("justificativa"): story.append(Paragraph("<b>Justificativa:</b> "+escape(rc["justificativa"]),s["BodyText"]))
    aprov="Aprovada em %s por usuário #%s"%(rc["aprovado_em"],rc["aprovado_por"]) if rc.get("aprovado_em") else "Aguardando decisão / não aprovada"
    story += [Spacer(1,12*mm),Paragraph("<b>Aprovação:</b> "+escape(aprov),s["BodyText"]),Spacer(1,14*mm),Table([["____________________________","","____________________________"],["Solicitante","","Aprovador"]],colWidths=[80*mm,20*mm,80*mm],style=[("ALIGN",(0,0),(-1,-1),"CENTER")]),Spacer(1,5*mm),Paragraph("Não movimenta estoque nem gera lançamento financeiro.",ParagraphStyle("nota",parent=s["Italic"],fontSize=8,textColor=VERDE))]
    doc.build(story,onFirstPage=_pagina,onLaterPages=_pagina); return b.getvalue()
