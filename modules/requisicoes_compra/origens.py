"""Registry único das origens formais e documentais da Requisição de Compra."""
from datetime import datetime
from decimal import Decimal
from flask import url_for
from database import conectar, q

TIPOS = (
    "REPOSICAO_ESTOQUE", "ORDEM_SERVICO", "ORDEM_PRODUCAO",
    "NAO_CONFORMIDADE_SGI", "QUALIDADE", "ADMINISTRATIVO", "PROJETO", "OUTRO",
)
PERFIS = {
    "REPOSICAO_ESTOQUE": {"admin", "pcp"},
    "ORDEM_SERVICO": {"admin", "manutencao", "pcp", "gerencia"},
    "ORDEM_PRODUCAO": {"admin", "producao", "pcp", "gerencia"},
    "NAO_CONFORMIDADE_SGI": {"admin", "qualidade", "gerencia"},
    "QUALIDADE": {"admin", "qualidade", "gerencia"},
    "ADMINISTRATIVO": {"admin", "gerencia"},
    "PROJETO": {"admin", "gerencia"},
    "OUTRO": {"admin", "gerencia"},
}

def _one(sql, params):
    conn = conectar()
    try:
        cur = conn.cursor(); cur.execute(q(sql), params); row = cur.fetchone()
        return dict(row) if row else None
    finally: conn.close()

def _saldo(insumo_id):
    return _one("""SELECT i.*,COALESCE(SUM(l.quantidade_atual),0) saldo
        FROM almoxarifado_insumos i LEFT JOIN almoxarifado_lotes l ON l.insumo_id=i.id
        WHERE i.id=? GROUP BY i.id""", (insumo_id,))

def verificar_permissao_criacao(tipo, perfil, origem=None):
    if tipo not in TIPOS: raise ValueError("Tipo de origem inválido.")
    permitido = str(perfil or "").lower() in PERFIS[tipo]
    if tipo == "ORDEM_SERVICO" and str(perfil).lower() == "qualidade":
        permitido = bool(origem and origem.get("sgi_nc_id"))
    if not permitido: raise PermissionError("Perfil sem permissão para criar RC desta origem.")

def resolver_origem(tipo, origem_id, dados, perfil):
    tipo = str(tipo or "").upper().strip()
    origem = None
    if tipo not in TIPOS: raise ValueError("Tipo de origem inválido.")
    formal = tipo in {"REPOSICAO_ESTOQUE","ORDEM_SERVICO","ORDEM_PRODUCAO","NAO_CONFORMIDADE_SGI"}
    if formal:
        try: oid = int(origem_id or 0)
        except (TypeError, ValueError): oid = 0
        if oid <= 0: raise ValueError("A origem selecionada exige um documento válido.")
        if tipo == "REPOSICAO_ESTOQUE": origem = _saldo(oid)
        elif tipo == "ORDEM_SERVICO": origem = _one("SELECT * FROM manutencao_ordens WHERE id=?", (oid,))
        elif tipo == "ORDEM_PRODUCAO": origem = _one("SELECT * FROM ordens_producao WHERE id=?", (oid,))
        else:
            origem = _one("""SELECT n.*,v.formulario_codigo,v.formulario_nome,v.setor,
                v.vinculo_tipo,v.local_id,v.equipamento_id FROM sgi_nao_conformidades n
                JOIN sgi_verificacoes v ON v.id=n.verificacao_id WHERE n.id=?""", (oid,))
        if not origem: raise ValueError("Documento de origem não encontrado.")
        origem_id = oid
    else:
        origem_id = None
    verificar_permissao_criacao(tipo, perfil, origem)
    setor = str(dados.get("setor") or (origem or {}).get("setor") or "").strip()
    descricao_manual = str(dados.get("origem_descricao") or "").strip()
    justificativa = str(dados.get("justificativa") or "").strip()
    if tipo in {"QUALIDADE","ADMINISTRATIVO","PROJETO","OUTRO"}:
        if not setor or not descricao_manual or not justificativa:
            raise ValueError("Informe setor, descrição da necessidade e justificativa.")
    if tipo == "PROJETO" and not str(dados.get("origem_numero") or "").strip():
        raise ValueError("Informe o código ou nome do projeto.")
    snap = _snapshot(tipo, origem, dados, setor)
    return origem_id, snap

def _snapshot(tipo, o, dados, setor):
    o = o or {}; agora = datetime.now().replace(microsecond=0).isoformat(sep=" ")
    if tipo == "REPOSICAO_ESTOQUE":
        numero=str(o["id"]); desc=o["descricao"]; equip=""; extra={"unidade":o["unidade"],"saldo_fisico":float(o["saldo"] or 0),"capturado_em":agora}
    elif tipo == "ORDEM_SERVICO":
        numero=f"OS-{int(o['id']):06d}"; desc=o.get("descricao") or "Ordem de Serviço"; setor=setor or o.get("setor") or ""; equip=o.get("equipamento_nome") or o.get("objeto_nome") or ""; extra={"status":o.get("status"),"tipo":o.get("tipo")}
    elif tipo == "ORDEM_PRODUCAO":
        numero=f"OP-{int(o['id']):06d}"; desc=o.get("sku") or "Ordem de Produção"; equip=""; extra={"status":o.get("status"),"data":o.get("data")}
    elif tipo == "NAO_CONFORMIDADE_SGI":
        numero=f"NC-{int(o['id']):06d}"; desc=o.get("descricao") or "Não conformidade SGI"; setor=setor or o.get("setor") or ""; equip=str(o.get("equipamento_id") or ""); extra={"criticidade":o.get("criticidade"),"situacao":o.get("situacao"),"formulario":o.get("formulario_codigo")}
    else:
        numero=str(dados.get("origem_numero") or "").strip(); desc=str(dados.get("origem_descricao") or "").strip(); equip=""; extra={"capturado_em":agora}
    return {"numero":numero,"descricao":desc,"setor":setor,"equipamento":equip,"dados":extra,"rotulo":f"{numero} — {desc}" if numero else f"{tipo.replace('_',' ').title()} — {desc}"}

def obter_url(tipo, origem_id):
    if not origem_id: return None
    endpoints={"REPOSICAO_ESTOQUE":("saldo_almoxarifado",{}),"ORDEM_SERVICO":("visualizar_ordem_manutencao",{"ordem_id":origem_id}),"ORDEM_PRODUCAO":("consultar_op",{}),"NAO_CONFORMIDADE_SGI":("sgi_qualidade",{})}
    try:
        ep,args=endpoints[tipo]; return url_for(ep,**args)
    except Exception: return None
