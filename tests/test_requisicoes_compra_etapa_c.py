"""Etapa C: casos adversariais de autorização, imutabilidade e integridade da RC."""
import sqlite3
import pytest
import database.connection as dbc
from modules.requisicoes_compra import services as svc
from modules.requisicoes_compra.origens import resolver_origem

@pytest.fixture()
def banco(tmp_path,monkeypatch):
    p=str(tmp_path/"rc_c.sqlite3"); monkeypatch.setattr(dbc,"DB_NAME",p); c=sqlite3.connect(p)
    c.executescript("""
    CREATE TABLE almoxarifado_insumos(id INTEGER PRIMARY KEY,descricao TEXT,categoria TEXT,unidade TEXT,ativo TEXT,origem_baixa TEXT);
    CREATE TABLE almoxarifado_lotes(id INTEGER PRIMARY KEY,insumo_id INTEGER,quantidade_atual REAL);
    CREATE TABLE almoxarifado_movimentacoes(id INTEGER PRIMARY KEY,insumo_id INTEGER,quantidade REAL);
    CREATE TABLE almoxarifado_requisicoes(id INTEGER PRIMARY KEY,status TEXT,ordem_servico_id INTEGER);
    CREATE TABLE almoxarifado_requisicao_itens(id INTEGER PRIMARY KEY,requisicao_id INTEGER,insumo_id INTEGER,quantidade_reservada REAL);
    CREATE TABLE almoxarifado_requisicao_alocacoes(id INTEGER PRIMARY KEY);
    CREATE TABLE manutencao_ordens(id INTEGER PRIMARY KEY,status TEXT,descricao TEXT,setor TEXT,sgi_nc_id INTEGER);
    CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,data TEXT,status TEXT,sku TEXT);
    CREATE TABLE sgi_verificacoes(id INTEGER PRIMARY KEY,formulario_codigo TEXT,formulario_nome TEXT,setor TEXT,vinculo_tipo TEXT,local_id INTEGER,equipamento_id INTEGER);
    CREATE TABLE sgi_nao_conformidades(id INTEGER PRIMARY KEY,verificacao_id INTEGER,descricao TEXT,criticidade TEXT,situacao TEXT);
    CREATE TABLE movimentacoes_financeiras(id INTEGER PRIMARY KEY);
    INSERT INTO almoxarifado_insumos VALUES(1,'Bandeja X','Embalagem','un','Sim','ORDEM_PRODUCAO');
    INSERT INTO almoxarifado_insumos VALUES(2,'Inativo','Manutenção','un','Nao','REQUISICAO_ALMOXARIFADO');
    INSERT INTO almoxarifado_insumos VALUES(3,'Peça oficial','Manutenção','un','Sim','REQUISICAO_ALMOXARIFADO');
    INSERT INTO almoxarifado_lotes VALUES(1,1,1200);
    INSERT INTO almoxarifado_requisicoes VALUES(1,'EMITIDA',NULL);
    INSERT INTO almoxarifado_requisicao_itens VALUES(1,1,1,200);
    INSERT INTO manutencao_ordens VALUES(10,'Aberta','Descrição original','Manutenção',NULL);
    INSERT INTO manutencao_ordens VALUES(11,'Aberta','OS ligada ao SGI','Qualidade',7);
    INSERT INTO manutencao_ordens VALUES(12,'Cancelada','OS cancelada','Manutenção',NULL);
    INSERT INTO ordens_producao VALUES(20,'2026-09-19','Aberta','Produto A');
    INSERT INTO ordens_producao VALUES(21,'2026-09-19','Cancelada','Produto B');
    INSERT INTO sgi_verificacoes VALUES(30,'PLM 02','Verificação','Qualidade','Equipamento',1,2);
    INSERT INTO sgi_nao_conformidades VALUES(31,30,'NC original','ALTA','Aberta');
    INSERT INTO sgi_nao_conformidades VALUES(32,30,'NC encerrada','BAIXA','Encerrada');
    """); c.commit(); c.close(); svc.criar_tabelas_requisicoes_compra(); return p

def usr(i,perfil): return {"id":i,"nome":f"U{i}","perfil":perfil}
def dados(tipo,oid=None,**kw):
    d={"tipo_origem":tipo,"origem_id":oid,"setor":"Setor","origem_descricao":"Descrição manual","origem_numero":"PRJ-1","prioridade":"NORMAL","justificativa":"Justificativa"}; d.update(kw); return d
def cadastrado(mid=1,q="1"): return {"material_id":str(mid),"quantidade_item":q,"descricao_item":"","unidade_item":"","custo_item":"","observacao_item":""}
def provis(desc="Peça especial",un="un",q="1"): return {"material_id":"","quantidade_item":q,"descricao_item":desc,"unidade_item":un,"custo_item":"","observacao_item":""}
def criar(tipo,oid,ator,chave="c",itens=None,**kw): return svc.criar_rascunho(dados(tipo,oid,**kw),itens or [cadastrado()],ator=ator,idempotency_key=chave)

@pytest.mark.parametrize("tipo,oid,permitidos,negado",[
    ("REPOSICAO_ESTOQUE",1,("admin","pcp"),"gerencia"),("ORDEM_SERVICO",10,("admin","manutencao","pcp","gerencia"),"producao"),("ORDEM_PRODUCAO",20,("admin","producao","pcp","gerencia"),"qualidade"),("NAO_CONFORMIDADE_SGI",31,("admin","qualidade","gerencia"),"pcp"),("ADMINISTRATIVO",None,("admin","gerencia"),"pcp")])
def test_matriz_permissao_service(banco,tipo,oid,permitidos,negado):
    for n,p in enumerate(permitidos): assert criar(tipo,oid,usr(100+n,p),chave=f"{tipo}-{p}")["tipo_origem"]==tipo
    with pytest.raises(PermissionError): criar(tipo,oid,usr(999,negado),chave=f"{tipo}-x")

def test_qualidade_so_cria_os_com_sgi(banco):
    with pytest.raises(PermissionError): criar("ORDEM_SERVICO",10,usr(1,"qualidade"),chave="sem-sgi")
    assert criar("ORDEM_SERVICO",11,usr(1,"qualidade"),chave="com-sgi")["origem_id"]==11

def test_envio_exige_autoria_e_permissao_atual_da_origem(banco):
    rc=criar("ORDEM_SERVICO",10,usr(1,"manutencao"),chave="autor-envio")
    with pytest.raises(PermissionError):
        svc.enviar(rc["id"],ator=usr(2,"manutencao"),versao=0,idempotency_key="envio-terceiro")
    with pytest.raises(PermissionError):
        svc.enviar(rc["id"],ator=usr(1,"qualidade"),versao=0,idempotency_key="envio-perfil-alterado")
    assert svc.enviar(rc["id"],ator=usr(9,"admin"),versao=0,idempotency_key="envio-gestao")["status"]=="ABERTA"

def test_origens_formais_canceladas_inativas_e_sem_id(banco):
    for tipo,oid in (("REPOSICAO_ESTOQUE",2),("ORDEM_SERVICO",12),("ORDEM_PRODUCAO",21),("NAO_CONFORMIDADE_SGI",32)):
        with pytest.raises(ValueError): resolver_origem(tipo,oid,dados(tipo,oid),"admin")
    for tipo in ("REPOSICAO_ESTOQUE","ORDEM_SERVICO","ORDEM_PRODUCAO","NAO_CONFORMIDADE_SGI"):
        with pytest.raises(ValueError): resolver_origem(tipo,None,dados(tipo),"admin")

def test_snapshot_imutavel_e_situacao_atual(banco):
    rc=criar("ORDEM_SERVICO",10,usr(1,"admin"),chave="snap")
    c=sqlite3.connect(banco); c.execute("UPDATE manutencao_ordens SET descricao='Descrição alterada',status='Concluida' WHERE id=10"); c.commit(); c.close()
    atual=svc.buscar_rc(rc["id"]); assert atual["origem_descricao_snapshot"]=="Descrição original" and atual["origem_situacao_atual"]=="Concluida"
    svc.editar_rascunho(rc["id"],{"tipo_origem":"OUTRO","origem_id":None,"prioridade":"NORMAL","justificativa":"ok"},[cadastrado()],ator=usr(1,"admin"),versao=0,idempotency_key="edit-snap")
    assert svc.buscar_rc(rc["id"])["tipo_origem"]=="ORDEM_SERVICO"

def test_reposicao_snapshot_reserva_disponivel_sem_minimo(banco):
    rc=criar("REPOSICAO_ESTOQUE",1,usr(1,"admin"),chave="saldo"); x=rc["origem_dados"]["dados"]
    assert x["saldo_fisico"]==1200 and x["reservado"]==200 and x["disponivel"]==1000 and "estoque_minimo" not in x

def test_autoaprovacao_admin_gerencia_retry_e_payload_ignorado(banco):
    for perfil,n in (("admin",1),("gerencia",2)):
        rc=criar("ADMINISTRATIVO",None,usr(n,perfil),chave=f"auto-{n}",solicitante_id=999)
        rc=svc.enviar(rc["id"],ator=usr(n,perfil),versao=0,idempotency_key=f"env-{n}")
        for _ in range(2):
            with pytest.raises(PermissionError): svc.aprovar(rc["id"],ator=usr(n,perfil),versao=1,idempotency_key=f"apr-auto-{n}")
        assert svc.aprovar(rc["id"],ator=usr(n+10,perfil),versao=1,idempotency_key=f"apr-ok-{n}")["status"]=="APROVADA"

def test_item_provisorio_adversarial_e_xss_preservado_com_escape_no_template(banco):
    for item in (provis("",q="1"),provis(un="INVALIDA"),provis(q="0"),provis(q="-1"),provis("x"*501)):
        with pytest.raises(ValueError): criar("ADMINISTRATIVO",None,usr(1,"admin"),chave=str(item),itens=[item])
    rc=criar("ADMINISTRATIVO",None,usr(1,"admin"),chave="xss",itens=[provis("<script>alert('x')</script> & peça")])
    assert "<script>" in rc["itens"][0]["descricao_snapshot"]
    template=open("templates/requisicao_compra_detalhe.html",encoding="utf-8").read(); assert "|safe" not in template and "innerHTML" not in template

def test_vinculo_material_adversarial_e_retry(banco):
    rc=criar("ADMINISTRATIVO",None,usr(1,"admin"),chave="prov",itens=[provis()]); item=rc["itens"][0]
    with pytest.raises(PermissionError): svc.vincular_material(rc["id"],item["id"],3,ator=usr(8,"gerencia"),idempotency_key="v0")
    with pytest.raises(ValueError): svc.vincular_material(rc["id"],item["id"],2,ator=usr(8,"pcp"),idempotency_key="v1")
    ok=svc.vincular_material(rc["id"],item["id"],3,ator=usr(8,"pcp"),idempotency_key="v2"); retry=svc.vincular_material(rc["id"],item["id"],3,ator=usr(8,"pcp"),idempotency_key="v2")
    assert ok["itens"][0]["descricao_snapshot"]=="Peça especial" and retry["itens"][0]["material_id"]==3
    with pytest.raises(ValueError): svc.vincular_material(rc["id"],item["id"],3,ator=usr(8,"pcp"),idempotency_key="v3")

def test_duplicidade_alerta_e_terminal_nao_alerta(banco):
    rc=criar("ORDEM_SERVICO",10,usr(1,"admin"),chave="dup-1",itens=[cadastrado(3)])
    assert rc["numero"] in svc.alertas_duplicidade("ORDEM_SERVICO",10,[3])[0]
    segunda=criar("ORDEM_SERVICO",10,usr(1,"admin"),chave="dup-2",itens=[cadastrado(3)]); assert segunda["id"]!=rc["id"]
    svc.cancelar(rc["id"],ator=usr(1,"admin"),versao=0,idempotency_key="can-dup",motivo="Fim")
    assert all(rc["numero"] not in x for x in svc.alertas_duplicidade("ORDEM_SERVICO",10,[3]))

def test_estados_cancelamento_rejeicao_e_stale_version(banco):
    rc=criar("ADMINISTRATIVO",None,usr(1,"admin"),chave="estado"); aberta=svc.enviar(rc["id"],ator=usr(1,"admin"),versao=0,idempotency_key="env-est")
    with pytest.raises(ValueError): svc.rejeitar(rc["id"],ator=usr(2,"gerencia"),versao=1,idempotency_key="rej-sem",motivo=" ")
    rejeitada=svc.rejeitar(rc["id"],ator=usr(2,"gerencia"),versao=1,idempotency_key="rej",motivo="Não aprovada"); assert rejeitada["status"]=="REJEITADA"
    with pytest.raises(ValueError): svc.cancelar(rc["id"],ator=usr(2,"gerencia"),versao=2,idempotency_key="can-rej",motivo="Fim")
    outro=criar("ADMINISTRATIVO",None,usr(3,"admin"),chave="conc"); svc.editar_rascunho(outro["id"],{"prioridade":"NORMAL","justificativa":"ok"},[cadastrado(3,"2")],ator=usr(3,"admin"),versao=0,idempotency_key="edit-conc")
    with pytest.raises(svc.ConflitoRC): svc.enviar(outro["id"],ator=usr(3,"admin"),versao=0,idempotency_key="send-stale")

def test_performance_volume_busca_filtros_e_sql_injection(banco):
    ids=[]
    for n in range(100): ids.append(criar("ADMINISTRATIVO",None,usr(1,"admin"),chave=f"vol-{n}",origem_descricao=f"Necessidade volume {n}")["id"])
    dbc.iniciar_metricas_sql(); encontrados=svc.listar({"status":"RASCUNHO","tipo_origem":"ADMINISTRATIVO","setor":"Setor","prioridade":"NORMAL","termo":"volume 42","data_inicio":"2026-01-01","data_fim":"2026-12-31"}); metricas=dbc.finalizar_metricas_sql()
    assert len(encontrados)==1 and metricas["sql_count"]==1
    dbc.iniciar_metricas_sql(); detalhe=svc.buscar_rc(ids[0]); metricas=dbc.finalizar_metricas_sql(); assert detalhe and metricas["sql_count"]<=4
    assert svc.listar({"termo":"%' OR 1=1 --"})==[]

def test_estados_futuros_e_campos_de_compra_nao_entram_por_payload(banco):
    rc=svc.criar_rascunho({**dados("ADMINISTRATIVO"),"status":"ATENDIDA","fornecedor":"Fornecedor X","numero_nf":"123","pedido_id":77,"conta_financeira_id":9},[cadastrado()],ator=usr(1,"admin"),idempotency_key="futuro")
    assert rc["status"]=="RASCUNHO" and not any(k in rc for k in ("fornecedor","numero_nf","pedido_id","conta_financeira_id"))
