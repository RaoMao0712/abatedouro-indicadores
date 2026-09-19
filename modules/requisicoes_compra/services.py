"""Serviço transacional do MVP de Requisições de Compra."""
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from database import DATABASE_URL, conectar, q
from .origens import TIPOS, resolver_origem, verificar_permissao_origem_existente, obter_url, obter_situacao_atual

STATUS = ("RASCUNHO","ABERTA","APROVADA","REJEITADA","CANCELADA","ATENDIDA","PARCIALMENTE_ATENDIDA")
PRIORIDADES = ("NORMAL","URGENTE","CRITICA")
FINAIS = ("REJEITADA","CANCELADA","ATENDIDA")
UNIDADES = ("un","kg","g","L","mL","m","cm","mm","m²","m³","cx","pct","rolo","par","jogo")
class ConflitoRC(RuntimeError): pass

def agora(): return datetime.now().replace(microsecond=0).isoformat(sep=" ")
def usuario(u): return {"id":u.get("id") or u.get("usuario_id"),"nome":str(u.get("nome") or "Sistema"),"perfil":str(u.get("perfil") or "").lower()}
def _begin(c):
    if not DATABASE_URL: c.execute("BEGIN IMMEDIATE")
def _id(cur):
    if DATABASE_URL: cur.execute("SELECT LASTVAL() id"); return int(cur.fetchone()["id"])
    return int(cur.lastrowid)

def criar_tabelas_requisicoes_compra():
    """Bootstrap idempotente apenas no boot; migrations versionadas são a fonte oficial."""
    conn=conectar(); cur=conn.cursor(); pk="SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"; ts="TIMESTAMP" if DATABASE_URL else "TEXT"
    cur.execute(f"""CREATE TABLE IF NOT EXISTS requisicoes_compra (id {pk},numero TEXT UNIQUE,status TEXT NOT NULL,versao INTEGER NOT NULL DEFAULT 0,tipo_origem TEXT NOT NULL,origem_id INTEGER,origem_numero_snapshot TEXT,origem_descricao_snapshot TEXT NOT NULL,origem_setor_snapshot TEXT,origem_equipamento_snapshot TEXT,origem_dados_snapshot TEXT NOT NULL,setor TEXT NOT NULL,solicitante_id INTEGER,solicitante_nome_snapshot TEXT NOT NULL,responsavel_id INTEGER,responsavel_nome_snapshot TEXT,prioridade TEXT NOT NULL,justificativa TEXT,observacoes TEXT,chave_criacao TEXT NOT NULL UNIQUE,criado_por INTEGER,criado_em {ts} NOT NULL,enviado_por INTEGER,enviado_em {ts},aprovado_por INTEGER,aprovado_em {ts},rejeitado_por INTEGER,rejeitado_em {ts},motivo_rejeicao TEXT,cancelado_por INTEGER,cancelado_em {ts},motivo_cancelamento TEXT,atualizado_em {ts} NOT NULL)""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS requisicao_compra_itens (id {pk},requisicao_compra_id INTEGER NOT NULL,material_id INTEGER,descricao_snapshot TEXT NOT NULL,unidade_snapshot TEXT NOT NULL,quantidade_solicitada REAL NOT NULL,custo_estimado_unitario REAL,observacao TEXT,status TEXT NOT NULL DEFAULT 'SOLICITADO',pendente_cadastro INTEGER NOT NULL DEFAULT 0,criado_em {ts} NOT NULL,atualizado_em {ts} NOT NULL)""")
    cur.execute(f"""CREATE TABLE IF NOT EXISTS requisicao_compra_eventos (id {pk},requisicao_compra_id INTEGER NOT NULL,item_id INTEGER,evento TEXT NOT NULL,status_anterior TEXT,status_novo TEXT,dados_anteriores TEXT,dados_novos TEXT,justificativa TEXT,usuario_id INTEGER,usuario_nome TEXT NOT NULL,perfil TEXT NOT NULL,criado_em {ts} NOT NULL,idempotency_key TEXT NOT NULL UNIQUE)""")
    for sql in ("CREATE INDEX IF NOT EXISTS idx_rc_origem ON requisicoes_compra(tipo_origem,origem_id,status)","CREATE INDEX IF NOT EXISTS idx_rc_status_data ON requisicoes_compra(status,criado_em)","CREATE INDEX IF NOT EXISTS idx_rc_solicitante ON requisicoes_compra(solicitante_id)","CREATE INDEX IF NOT EXISTS idx_rc_item_material ON requisicao_compra_itens(material_id,requisicao_compra_id)"):
        cur.execute(sql)
    conn.commit(); conn.close()

def _decimal(v,campo,zero=False):
    try: n=Decimal(str(v or "").replace(",","."))
    except (InvalidOperation,ValueError): raise ValueError(f"{campo} inválido.") from None
    if not n.is_finite() or n<0 or (not zero and n==0): raise ValueError(f"{campo} deve ser maior que zero.")
    return n

def _limitar(texto, campo, limite):
    valor=str(texto or "").strip()
    if len(valor)>limite: raise ValueError(f"{campo} excede {limite} caracteres.")
    return valor

def normalizar_itens(dados):
    if hasattr(dados,"getlist"):
        keys=("material_id","descricao_item","unidade_item","quantidade_item","custo_item","observacao_item"); vals={k:dados.getlist(k) for k in keys}; total=max([len(v) for v in vals.values()] or [0]); return [{k:(vals[k][i] if i<len(vals[k]) else "") for k in keys} for i in range(total) if any(str(vals[k][i] if i<len(vals[k]) else "").strip() for k in keys)]
    return list(dados or [])

def _preparar_itens(cur,itens):
    saida=[]; materiais=set(); provis=[]
    for raw in itens:
        mid=str(raw.get("material_id") or "").strip(); qtd=_decimal(raw.get("quantidade_item") or raw.get("quantidade"),"Quantidade"); custo=raw.get("custo_item") or raw.get("custo_estimado_unitario"); custo=str(_decimal(custo,"Custo estimado",True)) if str(custo or "").strip() else None
        if mid:
            mid=int(mid)
            if mid in materiais: raise ValueError("Não repita o mesmo material na RC.")
            materiais.add(mid); cur.execute(q("SELECT * FROM almoxarifado_insumos WHERE id=?"),(mid,)); m=cur.fetchone()
            if not m or m["ativo"]!="Sim": raise ValueError("Material cadastrado inexistente ou inativo.")
            desc,unidade,pend=m["descricao"],m["unidade"],0
        else:
            desc=_limitar(raw.get("descricao_item") or raw.get("descricao"),"Descrição",500); unidade=str(raw.get("unidade_item") or raw.get("unidade") or "").strip()
            if not desc or unidade not in UNIDADES: raise ValueError("Item provisório exige descrição e unidade válida.")
            chave=(" ".join(desc.lower().split()),unidade.lower())
            if chave in provis: raise ValueError("Não repita item provisório com mesma descrição e unidade.")
            provis.append(chave); mid=None; pend=1
        saida.append({"material_id":mid,"descricao":desc,"unidade":unidade,"quantidade":str(qtd),"custo":custo,"observacao":_limitar(raw.get("observacao_item") or raw.get("observacao"),"Observação do item",2000),"pendente":pend})
    if not saida: raise ValueError("Inclua ao menos um item.")
    return saida

def _evento(cur,rid,nome,ant,novo,u,chave,just=None,antes=None,depois=None,item_id=None):
    cur.execute(q("""INSERT INTO requisicao_compra_eventos(requisicao_compra_id,item_id,evento,status_anterior,status_novo,dados_anteriores,dados_novos,justificativa,usuario_id,usuario_nome,perfil,criado_em,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"""),(rid,item_id,nome,ant,novo,json.dumps(antes,ensure_ascii=False,default=str) if antes else None,json.dumps(depois,ensure_ascii=False,default=str) if depois else None,just,u["id"],u["nome"],u["perfil"],agora(),chave))

def criar_rascunho(dados,itens,*,ator,idempotency_key):
    u=usuario(ator); chave=str(idempotency_key or "").strip()
    if not chave: raise ValueError("Chave de criação obrigatória.")
    prioridade=str(dados.get("prioridade") or "NORMAL").upper(); justificativa=str(dados.get("justificativa") or "").strip()
    if prioridade not in PRIORIDADES: raise ValueError("Prioridade inválida.")
    if prioridade!="NORMAL" and not justificativa: raise ValueError("Urgente ou crítica exige justificativa.")
    oid,snap=resolver_origem(dados.get("tipo_origem"),dados.get("origem_id"),dados,u["perfil"])
    conn=conectar()
    try:
        _begin(conn); cur=conn.cursor(); cur.execute(q("SELECT id FROM requisicoes_compra WHERE chave_criacao=?"),(chave,)); old=cur.fetchone()
        if old: conn.rollback(); return buscar_rc(old["id"])
        preparados=_preparar_itens(cur,itens); t=agora()
        cur.execute(q("""INSERT INTO requisicoes_compra(numero,status,tipo_origem,origem_id,origem_numero_snapshot,origem_descricao_snapshot,origem_setor_snapshot,origem_equipamento_snapshot,origem_dados_snapshot,setor,solicitante_id,solicitante_nome_snapshot,responsavel_id,responsavel_nome_snapshot,prioridade,justificativa,observacoes,chave_criacao,criado_por,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),(None,"RASCUNHO",str(dados.get("tipo_origem")).upper(),oid,snap["numero"],snap["descricao"],snap["setor"],snap["equipamento"],json.dumps(snap,ensure_ascii=False,default=str),str(dados.get("setor") or snap["setor"]),u["id"],u["nome"],dados.get("responsavel_id") or None,str(dados.get("responsavel_nome") or "").strip() or None,prioridade,justificativa or None,str(dados.get("observacoes") or "").strip() or None,chave,u["id"],t,t)); rid=_id(cur); numero=f"RC-{rid:06d}"; cur.execute(q("UPDATE requisicoes_compra SET numero=? WHERE id=?"),(numero,rid))
        for x in preparados: cur.execute(q("""INSERT INTO requisicao_compra_itens(requisicao_compra_id,material_id,descricao_snapshot,unidade_snapshot,quantidade_solicitada,custo_estimado_unitario,observacao,pendente_cadastro,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?)"""),(rid,x["material_id"],x["descricao"],x["unidade"],x["quantidade"],x["custo"],x["observacao"] or None,x["pendente"],t,t))
        _evento(cur,rid,"CRIACAO_RASCUNHO",None,"RASCUNHO",u,f"{chave}:criacao",depois={"numero":numero,"origem":snap}); conn.commit(); return buscar_rc(rid)
    except Exception:
        conn.rollback()
        cur=conn.cursor(); cur.execute(q("SELECT id FROM requisicoes_compra WHERE chave_criacao=?"),(chave,)); repetida=cur.fetchone()
        if repetida: return buscar_rc(repetida["id"])
        raise
    finally: conn.close()

def editar_rascunho(rid,dados,itens,*,ator,versao,idempotency_key):
    u=usuario(ator); chave=str(idempotency_key or "").strip(); prioridade=str(dados.get("prioridade") or "NORMAL").upper(); justificativa=str(dados.get("justificativa") or "").strip()
    if not chave: raise ValueError("Chave idempotente obrigatória.")
    if prioridade not in PRIORIDADES or (prioridade!="NORMAL" and not justificativa): raise ValueError("Prioridade urgente/crítica exige justificativa.")
    conn=conectar()
    try:
        _begin(conn); cur=conn.cursor(); cur.execute(q("SELECT id FROM requisicao_compra_eventos WHERE idempotency_key=?"),(chave,))
        if cur.fetchone(): conn.rollback(); return buscar_rc(rid)
        cur.execute(q("SELECT * FROM requisicoes_compra WHERE id=?"),(rid,)); rc=cur.fetchone()
        if not rc or rc["status"]!="RASCUNHO": raise ValueError("Somente rascunho pode ser editado.")
        if str(rc["solicitante_id"])!=str(u["id"]) and u["perfil"] not in {"admin","gerencia"}: raise PermissionError("Sem permissão para editar este rascunho.")
        if int(rc["versao"])!=int(versao): raise ConflitoRC("A RC foi alterada por outro usuário.")
        preparados=_preparar_itens(cur,itens); cur.execute(q("SELECT material_id,descricao_snapshot,unidade_snapshot,quantidade_solicitada,custo_estimado_unitario,observacao,pendente_cadastro FROM requisicao_compra_itens WHERE requisicao_compra_id=? ORDER BY id"),(rid,)); antes=[dict(x) for x in cur.fetchall()]
        cur.execute(q("DELETE FROM requisicao_compra_itens WHERE requisicao_compra_id=?"),(rid,)); t=agora()
        for x in preparados: cur.execute(q("""INSERT INTO requisicao_compra_itens(requisicao_compra_id,material_id,descricao_snapshot,unidade_snapshot,quantidade_solicitada,custo_estimado_unitario,observacao,pendente_cadastro,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?,?)"""),(rid,x["material_id"],x["descricao"],x["unidade"],x["quantidade"],x["custo"],x["observacao"] or None,x["pendente"],t,t))
        cur.execute(q("UPDATE requisicoes_compra SET prioridade=?,justificativa=?,observacoes=?,versao=versao+1,atualizado_em=? WHERE id=? AND versao=?"),(prioridade,justificativa or None,str(dados.get("observacoes") or "").strip() or None,t,rid,int(versao)))
        if cur.rowcount!=1: raise ConflitoRC("A RC foi alterada por outro usuário.")
        depois=[{"material_id":x["material_id"],"descricao_snapshot":x["descricao"],"unidade_snapshot":x["unidade"],"quantidade_solicitada":float(x["quantidade"]),"custo_estimado_unitario":float(x["custo"]) if x["custo"] is not None else None,"observacao":x["observacao"] or None,"pendente_cadastro":x["pendente"]} for x in preparados]; _evento(cur,rid,"EDICAO",rc["status"],rc["status"],u,chave,antes=antes,depois=depois)
        if antes!=depois: _evento(cur,rid,"ALTERACAO_QUANTIDADE",rc["status"],rc["status"],u,chave+":quantidades",antes=antes,depois=depois)
        conn.commit(); return buscar_rc(rid)
    except Exception: conn.rollback(); raise
    finally: conn.close()

def _acao(rid,*,ator,versao,idempotency_key,acao,motivo=None):
    u=usuario(ator); chave=str(idempotency_key or "").strip()
    if not chave: raise ValueError("Chave idempotente obrigatória.")
    conn=conectar()
    try:
        _begin(conn); cur=conn.cursor(); cur.execute(q("SELECT evento FROM requisicao_compra_eventos WHERE idempotency_key=?"),(chave,)); evento_existente=cur.fetchone()
        if evento_existente:
            conn.rollback()
            if evento_existente["evento"]=="TENTATIVA_AUTOAPROVACAO": raise PermissionError("Solicitante não pode aprovar a própria RC.")
            return buscar_rc(rid)
        suf=" FOR UPDATE" if DATABASE_URL else ""; cur.execute(q(f"SELECT * FROM requisicoes_compra WHERE id=?{suf}"),(rid,)); rc=cur.fetchone()
        if not rc: raise ValueError("RC não encontrada.")
        if int(rc["versao"])!=int(versao): raise ConflitoRC("A RC foi alterada por outro usuário.")
        ant=rc["status"]
        if acao=="ENVIO":
            verificar_permissao_origem_existente(rc["tipo_origem"],rc["origem_id"],u["perfil"])
            if str(u["id"])!=str(rc["solicitante_id"]) and u["perfil"] not in {"admin","gerencia"}: raise PermissionError("Somente o autor ou gestão pode enviar a RC.")
            permitido=ant=="RASCUNHO"; novo="ABERTA"; campos=("enviado_por",u["id"],"enviado_em",agora())
        elif acao in {"APROVACAO","REJEICAO"}:
            if u["perfil"] not in {"admin","gerencia"}: raise PermissionError("Somente admin ou gerência pode decidir.")
            if acao=="APROVACAO" and u["id"] is not None and str(u["id"])==str(rc["solicitante_id"]):
                _evento(cur,rid,"TENTATIVA_AUTOAPROVACAO",ant,ant,u,chave,"Solicitante não pode aprovar a própria RC."); conn.commit(); raise PermissionError("Solicitante não pode aprovar a própria RC.")
            permitido=ant=="ABERTA"; novo="APROVADA" if acao=="APROVACAO" else "REJEITADA"
            if acao=="REJEICAO" and not str(motivo or "").strip(): raise ValueError("Informe o motivo da rejeição.")
            campos=(("aprovado_por",u["id"],"aprovado_em",agora()) if acao=="APROVACAO" else ("rejeitado_por",u["id"],"rejeitado_em",agora()))
        elif acao=="CANCELAMENTO":
            if ant not in {"RASCUNHO","ABERTA","APROVADA"}: raise ValueError("Estado não permite cancelamento.")
            if ant=="APROVADA" and u["perfil"] not in {"admin","gerencia"}: raise PermissionError("RC aprovada só pode ser cancelada por admin ou gerência.")
            if ant!="APROVADA" and u["perfil"] not in {"admin","gerencia"} and str(u["id"])!=str(rc["solicitante_id"]): raise PermissionError("Somente o autor ou gestão pode cancelar.")
            if u["perfil"] not in {"admin","gerencia"}: verificar_permissao_origem_existente(rc["tipo_origem"],rc["origem_id"],u["perfil"])
            if not str(motivo or "").strip(): raise ValueError("Informe o motivo do cancelamento.")
            permitido=True; novo="CANCELADA"; campos=("cancelado_por",u["id"],"cancelado_em",agora())
        else: raise ValueError("Ação inválida.")
        if not permitido: raise ValueError("Estado atual não permite esta ação.")
        extras=""; params=[novo,campos[1],campos[3]]
        if acao=="REJEICAO": extras=",motivo_rejeicao=?"; params.append(str(motivo).strip())
        if acao=="CANCELAMENTO": extras=",motivo_cancelamento=?"; params.append(str(motivo).strip())
        params += [agora(),rid,int(versao)]
        cur.execute(q(f"UPDATE requisicoes_compra SET status=?,{campos[0]}=?,{campos[2]}=?,versao=versao+1{extras},atualizado_em=? WHERE id=? AND versao=?"),tuple(params))
        if cur.rowcount!=1: raise ConflitoRC("A RC foi alterada por outro usuário.")
        _evento(cur,rid,acao,ant,novo,u,chave,str(motivo or "").strip() or None); conn.commit(); return buscar_rc(rid)
    except PermissionError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        cur=conn.cursor(); cur.execute(q("SELECT requisicao_compra_id FROM requisicao_compra_eventos WHERE idempotency_key=?"),(chave,)); repetido=cur.fetchone()
        if repetido: return buscar_rc(repetido["requisicao_compra_id"])
        raise
    finally: conn.close()

def enviar(rid,**kw): return _acao(rid,acao="ENVIO",**kw)
def aprovar(rid,**kw): return _acao(rid,acao="APROVACAO",**kw)
def rejeitar(rid,**kw): return _acao(rid,acao="REJEICAO",**kw)
def cancelar(rid,**kw): return _acao(rid,acao="CANCELAMENTO",**kw)

def vincular_material(rid,item_id,material_id,*,ator,idempotency_key):
    u=usuario(ator)
    if u["perfil"] not in {"admin","pcp"}: raise PermissionError("Somente admin ou PCP pode vincular material.")
    chave=str(idempotency_key or "").strip()
    if not chave: raise ValueError("Chave idempotente obrigatória.")
    conn=conectar()
    try:
        _begin(conn); cur=conn.cursor(); cur.execute(q("SELECT id FROM requisicao_compra_eventos WHERE idempotency_key=?"),(chave,))
        if cur.fetchone(): conn.rollback(); return buscar_rc(rid)
        suf=" FOR UPDATE" if DATABASE_URL else ""
        cur.execute(q(f"SELECT * FROM requisicoes_compra WHERE id=?{suf}"),(rid,)); rc=cur.fetchone(); cur.execute(q(f"SELECT * FROM requisicao_compra_itens WHERE id=? AND requisicao_compra_id=?{suf}"),(item_id,rid)); item=cur.fetchone(); cur.execute(q("SELECT * FROM almoxarifado_insumos WHERE id=? AND ativo='Sim'"),(material_id,)); mat=cur.fetchone()
        if not rc or not item or not mat: raise ValueError("RC, item ou material inválido.")
        if rc["status"]=="ATENDIDA" or not item["pendente_cadastro"]: raise ValueError("Item não pode ser vinculado.")
        if str(item["unidade_snapshot"]).lower()!=str(mat["unidade"]).lower(): raise ValueError("Unidade do cadastro incompatível com o snapshot.")
        cur.execute(q("SELECT 1 FROM requisicao_compra_itens WHERE requisicao_compra_id=? AND material_id=? AND id<>?"),(rid,material_id,item_id))
        if cur.fetchone(): raise ValueError("Material já existe nesta RC.")
        cur.execute(q("UPDATE requisicao_compra_itens SET material_id=?,pendente_cadastro=0,atualizado_em=? WHERE id=?"),(material_id,agora(),item_id)); _evento(cur,rid,"VINCULO_MATERIAL",rc["status"],rc["status"],u,chave,item_id=item_id,antes={"material_id":None},depois={"material_id":material_id}); conn.commit(); return buscar_rc(rid)
    except Exception:
        conn.rollback()
        cur=conn.cursor(); cur.execute(q("SELECT requisicao_compra_id FROM requisicao_compra_eventos WHERE idempotency_key=?"),(chave,)); repetido=cur.fetchone()
        if repetido: return buscar_rc(repetido["requisicao_compra_id"])
        raise
    finally: conn.close()

def buscar_rc(rid):
    conn=conectar()
    try:
        cur=conn.cursor(); cur.execute(q("SELECT * FROM requisicoes_compra WHERE id=?"),(rid,)); row=cur.fetchone()
        if not row:return None
        rc=dict(row); rc["origem_dados"]=json.loads(rc["origem_dados_snapshot"] or "{}"); rc["origem_url"]=obter_url(rc["tipo_origem"],rc["origem_id"]); rc["origem_situacao_atual"]=obter_situacao_atual(rc["tipo_origem"],rc["origem_id"])
        cur.execute(q("SELECT * FROM requisicao_compra_itens WHERE requisicao_compra_id=? ORDER BY id"),(rid,)); rc["itens"]=[dict(x) for x in cur.fetchall()]
        cur.execute(q("SELECT * FROM requisicao_compra_eventos WHERE requisicao_compra_id=? ORDER BY id"),(rid,)); rc["eventos"]=[dict(x) for x in cur.fetchall()]
        return rc
    finally: conn.close()

def listar(filtros=None,origem=None):
    f=filtros or {}; cond=["1=1"]; p=[]
    if origem: cond += ["r.tipo_origem=?","r.origem_id=?"]; p += list(origem)
    for k,col in (("status","r.status"),("tipo_origem","r.tipo_origem"),("setor","r.setor"),("prioridade","r.prioridade")):
        v=str(f.get(k) or "").strip()
        if v and v!="Todos": cond.append(f"{col}=?"); p.append(v)
    if f.get("data_inicio"):cond.append("r.criado_em>=?");p.append(f["data_inicio"])
    if f.get("data_fim"):cond.append("r.criado_em<?");p.append(f["data_fim"]+" 23:59:59")
    termo=str(f.get("termo") or "").lower().strip()
    if termo: cond.append("(LOWER(r.numero) LIKE ? OR LOWER(r.origem_descricao_snapshot) LIKE ? OR LOWER(r.solicitante_nome_snapshot) LIKE ? OR EXISTS(SELECT 1 FROM requisicao_compra_itens i WHERE i.requisicao_compra_id=r.id AND LOWER(i.descricao_snapshot) LIKE ?))");p += [f"%{termo}%"]*4
    conn=conectar()
    try:
        cur=conn.cursor(); cur.execute(q(f"""SELECT r.*,(SELECT COUNT(*) FROM requisicao_compra_itens i WHERE i.requisicao_compra_id=r.id) total_itens FROM requisicoes_compra r WHERE {' AND '.join(cond)} ORDER BY r.id DESC LIMIT 500"""),tuple(p)); return [dict(x) for x in cur.fetchall()]
    finally:conn.close()

def listar_por_origens(tipo, ids):
    ids=[int(x) for x in ids]
    if not ids:return {}
    marcas=','.join('?' for _ in ids); conn=conectar()
    try:
        cur=conn.cursor(); cur.execute(q(f"""SELECT r.*,(SELECT COUNT(*) FROM requisicao_compra_itens i WHERE i.requisicao_compra_id=r.id) total_itens FROM requisicoes_compra r WHERE r.tipo_origem=? AND r.origem_id IN ({marcas}) ORDER BY r.id DESC"""),tuple([tipo,*ids])); resultado={x:[] for x in ids}
        for row in cur.fetchall(): resultado.setdefault(int(row["origem_id"]),[]).append(dict(row))
        return resultado
    finally:conn.close()

def alertas_duplicidade(tipo,origem_id,material_ids):
    if not origem_id or not material_ids:return []
    conn=conectar()
    try:
        cur=conn.cursor(); marks=','.join('?' for _ in material_ids); cur.execute(q(f"""SELECT DISTINCT r.numero,i.descricao_snapshot FROM requisicoes_compra r JOIN requisicao_compra_itens i ON i.requisicao_compra_id=r.id WHERE r.tipo_origem=? AND r.origem_id=? AND r.status NOT IN ('REJEITADA','CANCELADA','ATENDIDA') AND i.material_id IN ({marks})"""),tuple([tipo,origem_id,*material_ids])); return [f"Já existe a {x['numero']} aberta para {x['descricao_snapshot']} nesta origem." for x in cur.fetchall()]
    finally:conn.close()
