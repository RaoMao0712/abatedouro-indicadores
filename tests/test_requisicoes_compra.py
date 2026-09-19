import sqlite3
from io import BytesIO
from pathlib import Path
import pytest

import database.connection as dbc
from modules.requisicoes_compra import services as svc
from modules.requisicoes_compra.pdf import gerar_pdf
from modules.requisicoes_compra.origens import listar_opcoes_origem

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

def aprovada(itens=None,chave="nu-base"):
    rc=criar("ADMINISTRATIVO",None,itens=itens,ator=u(1,"admin"),chave=chave)
    rc=svc.enviar(rc["id"],ator=u(1,"admin"),versao=0,idempotency_key=chave+"-env")
    return svc.aprovar(rc["id"],ator=u(2,"gerencia"),versao=1,idempotency_key=chave+"-apr")

def test_reposicao_bloqueia_item_incoerente(banco):
    with pytest.raises(ValueError,match="somente o material"):
        criar("REPOSICAO_ESTOQUE",1,itens=[item(3)])

def test_formulario_oferece_origens_formais_e_ux_sem_id_tecnico(banco):
    opcoes=listar_opcoes_origem()
    assert opcoes["materiais"][0]["descricao"]=="Bandeja X"
    assert opcoes["ordens_servico"][0]["id"]==245
    assert opcoes["ordens_producao"][0]["id"]==7
    assert opcoes["nao_conformidades"][0]["id"]==12
    base=Path(__file__).resolve().parents[1]/"templates"
    nova=(base/"requisicao_compra_nova.html").read_text(encoding="utf-8")
    lista=(base/"requisicoes_compra.html").read_text(encoding="utf-8")
    detalhe=(base/"requisicao_compra_detalhe.html").read_text(encoding="utf-8")
    assert "ID do documento" not in nova
    assert all(x in nova for x in ("Material que originou a reposição","Selecionar Ordem de Serviço","Selecionar Ordem de Produção","Selecionar Não Conformidade","Item não cadastrado"))
    assert all(x in lista for x in ("Data inicial","Data final","Limpar","rc-status","<th>NU</th>"))
    assert all(x in detalhe for x in ("Aplicar aos selecionados","Aplicar a todos os itens","Selecionar todos os itens visíveis","Sem NU","Com NU"))

@pytest.mark.parametrize("valor",["ABC","12A34","12 34","12.34","-123","","@123"])
def test_nu_rejeita_formato_invalido(banco,valor):
    rc=aprovada(chave="fmt-"+repr(valor))
    with pytest.raises(ValueError,match="somente dígitos"):
        svc.aplicar_nu(rc["id"],[rc["itens"][0]["id"]],valor,ator=u(8,"pcp"),versao=2,idempotency_key="x-"+repr(valor))

def test_nu_preserva_zero_esquerda_idempotencia_e_permissao(banco):
    rc=aprovada(chave="zeros"); iid=rc["itens"][0]["id"]
    rc=svc.aplicar_nu(rc["id"],[iid],"001234",ator=u(8,"pcp"),versao=2,idempotency_key="nu-zero")
    retry=svc.aplicar_nu(rc["id"],[iid],"001234",ator=u(8,"pcp"),versao=2,idempotency_key="nu-zero")
    assert retry["itens"][0]["nu"]=="001234" and sum(e["evento"]=="NU_APLICADA" for e in retry["eventos"])==1
    with pytest.raises(PermissionError): svc.aplicar_nu(rc["id"],[iid],"9",ator=u(9,"manutencao"),versao=3,idempotency_key="nu-negada")

def test_nu_somente_aprovada_item_externo_e_versao(banco):
    rasc=criar("ADMINISTRATIVO",None,chave="rasc"); iid=rasc["itens"][0]["id"]
    with pytest.raises(ValueError,match="aprovada"): svc.aplicar_nu(rasc["id"],[iid],"123",ator=u(),versao=0,idempotency_key="nu-rasc")
    rc=aprovada(chave="fora")
    with pytest.raises(ValueError,match="pertencer"): svc.aplicar_nu(rc["id"],[iid],"123",ator=u(),versao=2,idempotency_key="nu-fora")
    with pytest.raises(svc.ConflitoRC): svc.aplicar_nu(rc["id"],[rc["itens"][0]["id"]],"123",ator=u(),versao=1,idempotency_key="nu-stale")

@pytest.mark.parametrize("estado",["RASCUNHO","ABERTA","REJEITADA","CANCELADA"])
def test_nu_bloqueada_em_cada_estado_nao_aprovado(banco,estado):
    rc=criar("ADMINISTRATIVO",None,chave="estado-"+estado)
    conn=sqlite3.connect(banco); conn.execute("UPDATE requisicoes_compra SET status=? WHERE id=?",(estado,rc["id"])); conn.commit(); conn.close()
    with pytest.raises(ValueError,match="aprovada"):
        svc.aplicar_nu(rc["id"],[rc["itens"][0]["id"]],"123",ator=u(),versao=0,idempotency_key="nu-"+estado)

def test_nu_cinquenta_itens_subconjuntos_resumo_pdf_e_invariantes(banco):
    itens=[{"material_id":"","descricao_item":f"Item {n}","unidade_item":"un","quantidade_item":"1","custo_item":"","observacao_item":""} for n in range(50)]
    antes=contagens(banco); rc=aprovada(itens=itens,chave="volume-nu"); ids=[x["id"] for x in rc["itens"]]
    rc=svc.aplicar_nu(rc["id"],ids,"111111",ator=u(8,"pcp"),versao=2,idempotency_key="todos",modo="todos")
    rc=svc.aplicar_nu(rc["id"],ids[20:35],"222222",ator=u(8,"pcp"),versao=3,idempotency_key="sub1")
    rc=svc.aplicar_nu(rc["id"],ids[35:45],"333333",ator=u(8,"pcp"),versao=4,idempotency_key="sub2")
    rc=svc.aplicar_nu(rc["id"],ids[45:50],"444444",ator=u(8,"pcp"),versao=5,idempotency_key="sub3")
    grupos={x["nu"]:x["total"] for x in rc["resumo_nu"]}
    assert grupos=={"111111":20,"222222":15,"333333":10,"444444":5}
    assert any(e["evento"]=="NU_ALTERADA" for e in rc["eventos"])
    assert gerar_pdf(rc).startswith(b"%PDF") and contagens(banco)==antes
