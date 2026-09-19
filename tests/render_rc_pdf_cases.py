"""Gera amostras descartáveis para a auditoria visual da Etapa C."""
from pathlib import Path
from modules.requisicoes_compra.pdf import gerar_pdf

DESTINO=Path("tmp/pdfs"); DESTINO.mkdir(parents=True,exist_ok=True)
def rc(nome,origem,descricao,itens,status="ABERTA",prioridade="NORMAL",justificativa="Necessidade operacional auditada."):
    return {"numero":nome,"status":status,"prioridade":prioridade,"criado_em":"2026-09-19 12:00:00","solicitante_nome_snapshot":"João da Manutenção","setor":"Manutenção","tipo_origem":origem,"origem_numero_snapshot":"DOC-000245","origem_descricao_snapshot":descricao,"justificativa":justificativa,"aprovado_em":"2026-09-19 13:00:00" if status=="APROVADA" else None,"aprovado_por":9 if status=="APROVADA" else None,"itens":itens}
def item(i,provisorio=False): return {"descricao_snapshot":f"Item {i:03d} — descrição com acentuação, conexão & segurança", "unidade_snapshot":"un","quantidade_solicitada":i+1,"custo_estimado_unitario":"12.34" if i%2 else None,"pendente_cadastro":1 if provisorio else 0}
casos={
 "01-os":rc("RC-000001","ORDEM_SERVICO","Substituição de rolamento da nória",[item(1),item(2)],"APROVADA","URGENTE","Parada crítica da linha; aquisição necessária."),
 "02-reposicao":rc("RC-000002","REPOSICAO_ESTOQUE","Bandeja X — saldo 1.200 un; disponível 1.000 un",[item(3)]),
 "03-administrativa":rc("RC-000003","ADMINISTRATIVO","Aquisição de material para arquivo administrativo",[item(4)],prioridade="NORMAL"),
 "04-provisorio":rc("RC-000004","PROJETO","Projeto de melhoria PRJ-2026-01",[item(5,True)],prioridade="CRITICA",justificativa="Marco do projeto depende do componente específico."),
 "05-muitos-itens":rc("RC-000005","ORDEM_SERVICO","Revisão geral com grande quantidade de componentes",[item(i,i%9==0) for i in range(1,76)]),
 "06-origem-longa":rc("RC-000006","QUALIDADE","Adequação sanitária com descrição extensa: "+("área de manipulação, controles, barreiras e materiais especiais; "*12),[item(6),item(7,True)])
}
for nome,dados in casos.items(): (DESTINO/f"{nome}.pdf").write_bytes(gerar_pdf(dados))
print("PDF_CASES",len(casos))
