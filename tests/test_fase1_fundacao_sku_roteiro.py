import sqlite3
from pathlib import Path
import pytest
import database.connection as dbc
from modules.engenharia_produtos import repositories as legado
from modules.engenharia_produtos import fundacao as f
from modules.producao.services import setores_por_sku

USUARIO={"id":7,"nome":"PCP Teste"}

@pytest.fixture()
def banco(tmp_path,monkeypatch):
    monkeypatch.setattr(dbc,"DB_NAME",str(tmp_path/"fase1.db")); monkeypatch.setattr(dbc,"DATABASE_URL",None)
    legado.criar_estrutura(); f.criar_estrutura()
    c=dbc.conectar(); cur=c.cursor()
    cur.execute("INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES('T-1','Teste','PRODUTO_ACABADO','Kg','Sim')"); sku=cur.lastrowid
    cur.execute("INSERT INTO almoxarifado_insumos(descricao,categoria,unidade,ativo) VALUES('Filme','Embalagem','Un','Sim')"); insumo=cur.lastrowid
    cur.execute("CREATE TABLE IF NOT EXISTS ordens_producao(id INTEGER PRIMARY KEY,sku TEXT,status TEXT)")
    cur.execute("INSERT INTO ordens_producao(sku,status) VALUES('Galinha Cortada','Encerrada')"); op=cur.lastrowid
    c.commit(); c.close(); return sku,insumo,op

def sku_dados(v=1,status='RASCUNHO'):
 return {"versao":v,"nome":"Produto v"+str(v),"unidade_apresentacao":"Kg","categoria_tipo":"PRODUTO_ACABADO","status":status,"vigencia_inicio":"2026-09-22"}

def roteiro_dados(v=1,status='RASCUNHO'):
 return {"versao":v,"status":status,"vigencia_inicio":"2026-09-22","parametros_json":{"teste":True}}

def test_versionamento_unicidade_ativa_e_imutabilidade(banco):
 sku,_,_=banco; v1=f.criar_sku_versao(sku,sku_dados(1),USUARIO); f.ativar_sku_versao(v1,USUARIO)
 with pytest.raises(ValueError): f.criar_sku_versao(sku,sku_dados(2,'ATIVA'),USUARIO)
 with pytest.raises(ValueError,match='imutável'): f.atualizar_sku_versao(v1,sku_dados(1),USUARIO)

def test_etapa_livre_catalogada_ordem_insumo_e_roteiro_imutavel(banco):
 sku,insumo,_=banco; sv=f.criar_sku_versao(sku,sku_dados(),USUARIO); rv=f.criar_roteiro_versao(sv,roteiro_dados(),USUARIO)
 cat=f.criar_etapa_catalogo({"codigo":"CORTE","nome":"Corte","natureza":"TRANSFORMACAO"},USUARIO)
 livre=f.adicionar_etapa(rv,{"ordem":1,"nome":"Etapa livre","unidade_entrada":"AVE","unidade_saida":"Kg"})
 catalogada=f.adicionar_etapa(rv,{"etapa_catalogo_id":cat,"ordem":2,"nome":"Corte","unidade_entrada":"Kg","unidade_saida":"BANDEJA"})
 f.adicionar_insumo(catalogada,{"insumo_id":insumo,"unidade":"Un","quantidade_fator":1.5,"tipo_calculo":"POR_UNIDADE_SAIDA","origem_baixa":"MANUAL"})
 with pytest.raises(Exception): f.adicionar_etapa(rv,{"ordem":2,"nome":"Duplicada"})
 f.ativar_roteiro(rv,USUARIO)
 with pytest.raises(ValueError,match='imutável'): f.excluir_etapa(rv,livre)
 with pytest.raises(ValueError): f.criar_roteiro_versao(sv,roteiro_dados(2,'ATIVO'),USUARIO)

def test_novo_modelo_nao_retroage_nem_escreve_modulos_operacionais(banco):
 sku,_,op=banco; c=dbc.conectar(); cur=c.cursor()
 tabelas=['ordens_producao','estoque_produto_intermediario','pa_caixas','pa_nao_conformes','expedicoes','cmv_eventos','movimentacoes']
 antes={}
 for t in tabelas:
  try: antes[t]=cur.execute(f'SELECT COUNT(*) n FROM {t}').fetchone()['n']
  except Exception: pass
 c.close()
 sv=f.criar_sku_versao(sku,sku_dados(),USUARIO); f.criar_roteiro_versao(sv,roteiro_dados(),USUARIO)
 assert "Corte" in setores_por_sku("Galinha Cortada")
 assert "Corte" not in setores_por_sku("Galinha Inteira")
 c=dbc.conectar(); cur=c.cursor()
 assert cur.execute('SELECT sku,status FROM ordens_producao WHERE id=?',(op,)).fetchone()['sku']=='Galinha Cortada'
 assert cur.execute('SELECT COUNT(*) n FROM op_config_snapshots').fetchone()['n']==0
 for t,n in antes.items(): assert cur.execute(f'SELECT COUNT(*) n FROM {t}').fetchone()['n']==n
 c.close()

def test_migration_sqlite_apply_reapply_rollback_reapply_preserva_legado(tmp_path):
 db=sqlite3.connect(tmp_path/'migration.db'); db.executescript('CREATE TABLE skus(id INTEGER PRIMARY KEY); CREATE TABLE almoxarifado_insumos(id INTEGER PRIMARY KEY); CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,sku TEXT); INSERT INTO ordens_producao VALUES(1,"Galinha Inteira");')
 root=Path(__file__).resolve().parents[1]/'database'; apply=(root/'20260922_fase1_fundacao_sku_roteiro_sqlite.sql').read_text(); rollback=(root/'20260922_fase1_fundacao_sku_roteiro_sqlite_rollback.sql').read_text()
 db.executescript(apply); db.executescript(apply); db.executescript(rollback); db.executescript(apply)
 assert db.execute('SELECT sku FROM ordens_producao WHERE id=1').fetchone()[0]=='Galinha Inteira'; db.close()
