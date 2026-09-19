import sqlite3
from io import BytesIO
import pytest

import database.connection as dbc
from modules.requisicoes_compra import services as svc
from modules.requisicoes_compra.pdf import gerar_pdf

@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho=str(tmp_path/"rc.sqlite3"); monkeypatch.setattr(dbc,"DB_NAME",caminho)
    conn=sqlite3.connect(caminho)
    conn.executescript("""
    CREATE TABLE almoxarifado_insumos(id INTEGER PRIMARY KEY,descricao TEXT,categoria TEXT,unidade TEXT,ativo TEXT,origem_baixa TEXT);
    CREATE TABLE almoxarifado_lotes(id INTEGER PRIMARY KEY,insumo_id INTEGER,quantidade_atual REAL);
    CREATE TABLE almoxarifado_movimentacoes(id INTEGER PRIMARY KEY,insumo_id INTEGER,quantidade REAL);
    CREATE TABLE almoxarifado_requisicoes(id INTEGER PRIMARY KEY,ordem_servico_id INTEGER);
    CREATE TABLE manutencao_ordens(id INTEGER PRIMARY KEY,equipamento_id INTEGER,tipo TEXT,prioridade TEXT,status TEXT,data_abertura TEXT,solicitante TEXT,responsavel TEXT,descricao TEXT,sgi_nc_id INTEGER,setor TEXT);
    CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,data TEXT,fornecedor TEXT,quantidade_aves INTEGER,peso_vivo REAL,peso_medio REAL,status TEXT,sku TEXT);
    CREATE TABLE sgi_verificacoes(id INTEGER PRIMARY KEY,formulario_codigo TEXT,formulario_nome TEXT,setor TEXT,vinculo_tipo TEXT,local_id INTEGER,equipamento_id INTEGER);
    CREATE TABLE sgi_nao_conformidades(id INTEGER PRIMARY KEY,verificacao_id INTEGER,descricao TEXT,criticidade TEXT,situacao TEXT);
    CREATE TABLE movimentacoes_financeiras(id INTEGER PRIMARY KEY);
    INSERT INTO almoxarifado_insumos VALUES(1,'Bandeja X','Embalagem','un','Sim','ORDEM_PRODUCAO');
    INSERT INTO almoxarifado_insumos VALUES(2,'Rolamento 6205','Manutenção','un','Sim','REQUISICAO_ALMOXARIFADO');
    INSERT INTO almoxarifado_insumos VALUES(3,'Graxa','Manutenção','kg','Sim','REQUISICAO_ALMOXARIFADO');
    INSERT INTO almoxarifado_lotes VALUES(1,1,1200);
    INSERT INTO manutencao_ordens VALUES(245,1,'Corretiva','Alta','Aberta','2026-09-19','Manutenção','Técnico','Substituição de rolamento da nória',NULL,'Abate');
    INSERT INTO ordens_producao VALUES(7,'2026-09-19','Fornecedor',100,200,2,'Aberta','Galinha Cortada');
    INSERT INTO sgi_verificacoes VALUES(9,'PLM 02','Verificação','Qualidade','Equipamento',1,1);
    INSERT INTO sgi_nao_conformidades VALUES(12,9,'Adequação sanitária','ALTA','Aberta');
    """); conn.commit(); conn.close(); svc.criar_tabelas_requisicoes_compra(); yield caminho

def u(id=1,perfil="admin",nome="Usuário"): return {"id":id,"perfil":perfil,"nome":nome}
def item(mid=1,q="5"): return {"material_id":str(mid),"quantidade_item":q,"descricao_item":"","unidade_item":"","custo_item":"","observacao_item":""}
def criar(tipo,oid,dados=None,itens=None,ator=None,chave="criar"):
    d={"tipo_origem":tipo,"origem_id":oid,"setor":"Setor","prioridade":"NORMAL","justificativa":"Necessidade","origem_descricao":"Necessidade manual","origem_numero":"PRJ-1"}; d.update(dados or {})
    return svc.criar_rascunho(d,itens or [item()],ator=ator or u(),idempotency_key=chave)

def contagens(caminho):
    c=sqlite3.connect(caminho); r=tuple(c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("almoxarifado_lotes","almoxarifado_movimentacoes","movimentacoes_financeiras")); c.close(); return r

def test_reposicao_snapshot_idempotencia_e_invariancia(banco):
    antes=contagens(banco); rc=criar("REPOSICAO_ESTOQUE",1,itens=[item(1,"5000")]); repetida=criar("REPOSICAO_ESTOQUE",1,itens=[item(1,"5000")])
    assert rc["id"]==repetida["id"] and rc["origem_dados"]["dados"]["saldo_fisico"]==1200
    assert "estoque_minimo" not in rc["origem_dados"]["dados"] and contagens(banco)==antes
    assert svc.listar(origem=("REPOSICAO_ESTOQUE",1))[0]["numero"]==rc["numero"]

def test_os_multiplos_itens_link_reverso_e_sem_mutacao(banco):
    rc=criar("ORDEM_SERVICO",245,itens=[item(2,"2"),item(3,"1")],ator=u(2,"manutencao"))
    assert len(rc["itens"])==2 and "rolamento" in rc["origem_descricao_snapshot"].lower()
    assert len(svc.listar(origem=("ORDEM_SERVICO",245)))==1
    c=sqlite3.connect(banco); assert c.execute("SELECT status FROM manutencao_ordens WHERE id=245").fetchone()[0]=="Aberta"; c.close()

def test_qualidade_formal_e_livre(banco):
    formal=criar("NAO_CONFORMIDADE_SGI",12,ator=u(4,"qualidade"),chave="nc")
    assert formal["origem_dados"]["dados"]["criticidade"]=="ALTA"
    livre=criar("QUALIDADE",None,ator=u(4,"qualidade"),chave="ql")
    assert livre["origem_id"] is None
    with pytest.raises(ValueError): criar("QUALIDADE",None,dados={"justificativa":""},ator=u(4,"qualidade"),chave="ql2")

def test_administrativo_permissao_e_prioridade(banco):
    with pytest.raises(PermissionError): criar("ADMINISTRATIVO",None,ator=u(8,"pcp"),chave="a1")
    assert criar("ADMINISTRATIVO",None,ator=u(1,"admin"),chave="a2")["tipo_origem"]=="ADMINISTRATIVO"
    with pytest.raises(ValueError): criar("PROJETO",None,dados={"prioridade":"URGENTE","justificativa":""},chave="p1")

def test_item_provisorio_vinculo_preserva_snapshot(banco):
    provis={"material_id":"","descricao_item":"Peça especial","unidade_item":"un","quantidade_item":"2","custo_item":"10","observacao_item":"Teste"}
    rc=criar("ORDEM_SERVICO",245,itens=[provis],ator=u(2,"manutencao"),chave="prov"); it=rc["itens"][0]
    assert it["material_id"] is None and it["pendente_cadastro"]==1
    rc=svc.vincular_material(rc["id"],it["id"],2,ator=u(8,"pcp"),idempotency_key="vinc")
    assert rc["itens"][0]["material_id"]==2 and rc["itens"][0]["descricao_snapshot"]=="Peça especial"
    assert any(e["evento"]=="VINCULO_MATERIAL" for e in rc["eventos"])

def test_fluxo_segregacao_idempotencia_e_concorrencia(banco):
    rc=criar("ADMINISTRATIVO",None,ator=u(1,"admin"),chave="fluxo")
    rc=svc.enviar(rc["id"],ator=u(1,"admin"),versao=0,idempotency_key="env")
    assert svc.enviar(rc["id"],ator=u(1,"admin"),versao=0,idempotency_key="env")["status"]=="ABERTA"
    with pytest.raises(PermissionError): svc.aprovar(rc["id"],ator=u(1,"admin"),versao=1,idempotency_key="auto")
    rc=svc.aprovar(rc["id"],ator=u(9,"gerencia"),versao=1,idempotency_key="apr")
    assert rc["status"]=="APROVADA"
    with pytest.raises(svc.ConflitoRC): svc.cancelar(rc["id"],ator=u(9,"gerencia"),versao=1,idempotency_key="cancel-old",motivo="Fim")
    assert sum(e["evento"]=="APROVACAO" for e in rc["eventos"])==1

def test_edicao_somente_rascunho_e_eventos(banco):
    rc=criar("ORDEM_SERVICO",245,itens=[item(2,"2")],ator=u(2,"manutencao"),chave="ed")
    rc=svc.editar_rascunho(rc["id"],{"prioridade":"NORMAL","justificativa":"ok","observacoes":"x"},[item(2,"3")],ator=u(2,"manutencao"),versao=0,idempotency_key="edit")
    assert rc["itens"][0]["quantidade_solicitada"]==3 and {e["evento"] for e in rc["eventos"]}>={"EDICAO","ALTERACAO_QUANTIDADE"}
    rc=svc.enviar(rc["id"],ator=u(2,"manutencao"),versao=1,idempotency_key="send-ed")
    with pytest.raises(ValueError): svc.editar_rascunho(rc["id"],{"prioridade":"NORMAL"},[item(2,"4")],ator=u(2,"manutencao"),versao=2,idempotency_key="edit2")

def test_origens_invalidas_duplicatas_pdf(banco):
    for tipo,oid in (("ORDEM_SERVICO",999),("ORDEM_PRODUCAO",999),("REPOSICAO_ESTOQUE",999),("NAO_CONFORMIDADE_SGI",999),("ORDEM_SERVICO",None),("INVALIDA",1)):
        with pytest.raises(ValueError): criar(tipo,oid,chave=f"bad-{tipo}-{oid}")
    with pytest.raises(ValueError): criar("ORDEM_SERVICO",245,itens=[item(2),item(2)],ator=u(2,"manutencao"),chave="dup")
    rc=criar("ORDEM_SERVICO",245,itens=[item(2),{"material_id":"","descricao_item":"Peça provisória longa","unidade_item":"un","quantidade_item":"1","custo_item":"","observacao_item":""}],ator=u(2,"manutencao"),chave="pdf")
    pdf=gerar_pdf(rc); assert pdf.startswith(b"%PDF") and len(pdf)>1500
