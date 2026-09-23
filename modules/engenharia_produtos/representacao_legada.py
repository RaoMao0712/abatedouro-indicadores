"""Representação em sombra dos dois fluxos legados, sem integração operacional."""
import json
from database import DATABASE_URL, conectar, q, transaction
from . import fundacao

AUTORIDADE = "LEGADO"
MODO = "SOMBRA"

ESPECIFICACOES = {
 "Galinha Cortada": {
  "codigo":"LEG-1","tipo":"PRODUTO_ACABADO","unidade":"Kg",
  "apresentacoes":["BANDEJA","CAIXA"],"unidade_operacional":"BANDEJA",
  "exige_peso":True,"bandejas_por_caixa":12,"tara_caixa_kg":0.5,
  "encerramento":"EMBALAGEM_SECUNDARIA",
  "etapas":[
   ("RECEPCAO_PENDURA","Recepção e Pendura","AVE","AVE",False,False),
   ("ESCALDA_DEPENAGEM","Escalda e Depenagem","AVE","AVE",False,False),
   ("EVISCERACAO","Evisceração","AVE","AVE",False,True),
   ("CORTE","Corte","AVE","Kg",False,False),
   ("EMBALAGEM_PRODUCAO","Embalagem","Kg","BANDEJA",False,False),
   ("EMBALAGEM_PRIMARIA","Embalagem Primária","BANDEJA","BANDEJA",True,False),
   ("EMBALAGEM_SECUNDARIA","Embalagem Secundária","BANDEJA","CAIXA",False,True),
  ]},
 "Galinha Inteira": {
  "codigo":"LEG-2","tipo":"PRODUTO_ACABADO","unidade":"Un",
  "apresentacoes":["V1","V2"],"unidade_operacional":"PACOTE",
  "exige_peso":False,"aves_por_pacote":{"V1":1,"V2":2},
  "encerramento":"EMBALAGEM_PRIMARIA",
  "etapas":[
   ("RECEPCAO_PENDURA","Recepção e Pendura","AVE","AVE",False,False),
   ("ESCALDA_DEPENAGEM","Escalda e Depenagem","AVE","AVE",False,False),
   ("EVISCERACAO","Evisceração","AVE","AVE",False,True),
   ("EMBALAGEM_PRODUCAO","Embalagem","AVE","PACOTE",False,False),
   ("EMBALAGEM_PRIMARIA","Embalagem Primária","AVE","PACOTE",False,True),
  ]},
}


def _json(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _id(cur, sql, args):
 if DATABASE_URL:
  cur.execute(q(sql+" RETURNING id"),args); return cur.fetchone()["id"]
 cur.execute(q(sql),args); return cur.lastrowid


def _parametros_sku(e):
 return {"autoridade_operacional":AUTORIDADE,"modo":MODO,"codigo":e["codigo"],
         "apresentacoes":e["apresentacoes"],"unidade_operacional":e["unidade_operacional"]}

def _parametros_roteiro(e):
 return {k:e[k] for k in e if k not in {"codigo","tipo","unidade","etapas"}}

def _etapa_parametros(codigo,e):
 p={"autoridade_operacional":AUTORIDADE,"modo":MODO}
 if codigo=="EMBALAGEM_SECUNDARIA": p.update({"bandejas_por_caixa":e["bandejas_por_caixa"],"tara_caixa_kg":e["tara_caixa_kg"]})
 if codigo=="EMBALAGEM_PRIMARIA" and "aves_por_pacote" in e: p["aves_por_pacote"]=e["aves_por_pacote"]
 return p


def aplicar(usuario_nome="Sistema - Fase 2"):
 fundacao.criar_estrutura(); ambiguidades=[]; criados=[]
 with transaction() as conn:
  cur=conn.cursor()
  for nome,e in ESPECIFICACOES.items():
   cur.execute(q("SELECT * FROM skus WHERE nome=? AND excluido_em IS NULL"),(nome,)); sku=cur.fetchone()
   if not sku: raise ValueError(f"SKU legado ausente: {nome}.")
   if sku["codigo"]!=e["codigo"] or sku["tipo_produto"]!=e["tipo"] or sku["unidade_venda"]!=e["unidade"]:
    raise ValueError(f"Cadastro legado divergente para {nome}; nenhuma representação foi gravada.")
   cur.execute(q("SELECT * FROM sku_versoes WHERE sku_id=? AND versao=1"),(sku["id"],)); sv=cur.fetchone()
   if not sv:
    sv_id=_id(cur,"""INSERT INTO sku_versoes(sku_id,versao,nome,unidade_apresentacao,categoria_tipo,status,
      vigencia_inicio,usuario_nome,codigo,apresentacao,parametros_json)
      VALUES(?,?,?,?,?,'ATIVA',CURRENT_DATE,?,?,?,?)""",
      (sku["id"],1,nome,e["unidade"],e["tipo"],usuario_nome,e["codigo"],
       ", ".join(e["apresentacoes"]),_json(_parametros_sku(e)))); criados.append(f"sku_versao:{nome}:1")
   else: sv_id=sv["id"]
   cur.execute(q("SELECT * FROM roteiro_versoes WHERE sku_versao_id=? AND versao=1"),(sv_id,)); rv=cur.fetchone()
   if not rv:
    rv_id=_id(cur,"""INSERT INTO roteiro_versoes(sku_versao_id,versao,status,vigencia_inicio,aprovado_por,
      aprovado_em,observacoes,parametros_json,usuario_nome) VALUES(?,1,'ATIVO',CURRENT_DATE,?,CURRENT_TIMESTAMP,?,?,?)""",
      (sv_id,usuario_nome,"Representação em sombra do fluxo legado; sem autoridade operacional.",_json(_parametros_roteiro(e)),usuario_nome)); criados.append(f"roteiro:{nome}:1")
    for ordem,(codigo,etapa_nome,entrada,saida,intermediario,qualidade) in enumerate(e["etapas"],1):
     cur.execute(q("SELECT id,nome FROM etapas_catalogo WHERE codigo=?"),(codigo,)); cat=cur.fetchone()
     if not cat:
      cat_id=_id(cur,"""INSERT INTO etapas_catalogo(codigo,nome,natureza,ativo,parametros_json,usuario_nome)
        VALUES(?,?,?,1,?,?)""",(codigo,etapa_nome,"PRODUTIVA",_json({"origem":"LEGADO"}),usuario_nome))
     else: cat_id=cat["id"]
     _id(cur,"""INSERT INTO roteiro_etapas(roteiro_versao_id,etapa_catalogo_id,ordem,nome,obrigatoria,
       unidade_entrada,unidade_saida,gera_intermediario,controla_qualidade,parametros_json)
       VALUES(?,?,?,?,1,?,?,?,?,?)""",(rv_id,cat_id,ordem,etapa_nome,entrada,saida,int(intermediario),int(qualidade),_json(_etapa_parametros(codigo,e))))
   cur.execute(q("""SELECT r.*,i.descricao FROM receitas_sku r JOIN almoxarifado_insumos i ON i.id=r.insumo_id
     WHERE r.sku_id=? AND COALESCE(r.status,'Ativo')='Ativo' AND r.removido_em IS NULL"""),(sku["id"],))
   for item in cur.fetchall():
    ambiguidades.append({"classificacao":"DECISAO_DE_NEGOCIO_NECESSARIA","sku":nome,"receita_sku_id":item["id"],
      "insumo_id":item["insumo_id"],"insumo":item["descricao"],"motivo":"Etapa de consumo não é informada por receitas_sku."})
  resultado=comparar_todos(cur)
  if not resultado["paridade"]: raise ValueError("Divergência estrutural: "+_json(resultado["divergencias"]))
 return {"criados":criados,"ambiguidades":ambiguidades,"comparacao":resultado}


def comparar(nome, cursor=None):
 if nome not in ESPECIFICACOES: raise ValueError("SKU fora do escopo legado.")
 e=ESPECIFICACOES[nome]; conn=None; cur=cursor; divergencias=[]
 if cur is None:
  conn=conectar();cur=conn.cursor()
 try:
  cur.execute(q("""SELECT s.codigo codigo_legado,s.tipo_produto,s.unidade_venda,sv.id sv_id,sv.nome,
    sv.codigo,sv.apresentacao,sv.parametros_json,sv.unidade_apresentacao,sv.categoria_tipo,sv.status
    FROM skus s LEFT JOIN sku_versoes sv ON sv.sku_id=s.id AND sv.versao=1 WHERE s.nome=?"""),(nome,)); row=cur.fetchone()
  if not row: return {"sku":nome,"paridade":False,"divergencias":["representação ausente"]}
  for campo,esperado in (("codigo_legado",e["codigo"]),("codigo",e["codigo"]),("tipo_produto",e["tipo"]),("unidade_venda",e["unidade"]),("nome",nome),("unidade_apresentacao",e["unidade"]),("apresentacao",", ".join(e["apresentacoes"])),("categoria_tipo",e["tipo"]),("status","ATIVA")):
   if row[campo]!=esperado: divergencias.append({"campo":campo,"esperado":esperado,"atual":row[campo]})
  if json.loads(row["parametros_json"]) != _parametros_sku(e): divergencias.append("snapshot do SKU divergente")
  cur.execute(q("SELECT id,status,parametros_json FROM roteiro_versoes WHERE sku_versao_id=? AND versao=1"),(row["sv_id"],)); rv=cur.fetchone()
  if not rv: divergencias.append("roteiro versão 1 ausente"); return {"sku":nome,"paridade":False,"divergencias":divergencias}
  if rv["status"]!="ATIVO": divergencias.append({"campo":"roteiro.status","esperado":"ATIVO","atual":rv["status"]})
  if json.loads(rv["parametros_json"])!=_parametros_roteiro(e): divergencias.append("parametros críticos divergentes")
  cur.execute(q("SELECT ordem,nome,unidade_entrada,unidade_saida,gera_intermediario,controla_qualidade,parametros_json FROM roteiro_etapas WHERE roteiro_versao_id=? ORDER BY ordem"),(rv["id"],)); atuais=cur.fetchall()
  esperadas=e["etapas"]
  if len(atuais)!=len(esperadas): divergencias.append({"campo":"quantidade_etapas","esperado":len(esperadas),"atual":len(atuais)})
  for ordem,(atual,esp) in enumerate(zip(atuais,esperadas),1):
   codigo,nm,entrada,saida,inter,qual=esp
   esperado=(ordem,nm,entrada,saida,int(inter),int(qual),_etapa_parametros(codigo,e))
   obtido=(atual["ordem"],atual["nome"],atual["unidade_entrada"],atual["unidade_saida"],atual["gera_intermediario"],atual["controla_qualidade"],json.loads(atual["parametros_json"]))
   if obtido!=esperado: divergencias.append({"etapa":ordem,"esperado":esperado,"atual":obtido})
  return {"sku":nome,"paridade":not divergencias,"divergencias":divergencias}
 finally:
  if conn is not None: conn.close()


def comparar_todos(cursor=None):
 itens=[comparar(nome, cursor) for nome in ESPECIFICACOES]
 return {"paridade":all(x["paridade"] for x in itens),"itens":itens,"divergencias":[x for x in itens if not x["paridade"]]}
