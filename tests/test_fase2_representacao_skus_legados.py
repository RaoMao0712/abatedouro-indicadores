import json
import pytest
import database.connection as dbc
from modules.engenharia_produtos import repositories as repo
from modules.engenharia_produtos import representacao_legada as rl

@pytest.fixture()
def banco(tmp_path,monkeypatch):
 monkeypatch.setattr(dbc,"DB_NAME",str(tmp_path/"fase2.db")); monkeypatch.setattr(dbc,"DATABASE_URL",None)
 repo.criar_estrutura(); c=dbc.conectar();cur=c.cursor()
 cur.execute("INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES('LEG-1','Galinha Cortada','PRODUTO_ACABADO','Kg','Sim')"); cortada=cur.lastrowid
 cur.execute("INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES('LEG-2','Galinha Inteira','PRODUTO_ACABADO','Un','Sim')"); inteira=cur.lastrowid
 cur.execute("INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES('NOVO','Terceiro SKU','PRODUTO_ACABADO','Un','Sim')"); terceiro=cur.lastrowid
 cur.execute("INSERT INTO almoxarifado_insumos(descricao,categoria,unidade,ativo) VALUES('Filme ambíguo','Embalagem','Un','Sim')"); insumo=cur.lastrowid
 cur.execute("""INSERT INTO receitas_sku(sku_id,insumo_id,quantidade_por_unidade,tipo_consumo,unidade,status)
 VALUES(?,?,1,'FIXO_UNIDADE','Un','Ativo')""",(cortada,insumo))
 for ddl in ["CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,sku TEXT,status TEXT)","CREATE TABLE estoque_eventos(id INTEGER PRIMARY KEY,marcador TEXT)","CREATE TABLE cmv_eventos(id INTEGER PRIMARY KEY,marcador TEXT)","CREATE TABLE pa_nao_conformes(id INTEGER PRIMARY KEY,marcador TEXT)","CREATE TABLE expedicoes(id INTEGER PRIMARY KEY,marcador TEXT)","CREATE TABLE movimentacoes(id INTEGER PRIMARY KEY,marcador TEXT)"]:
  cur.execute(ddl)
 cur.execute("INSERT INTO ordens_producao VALUES(1,'Galinha Cortada','Encerrada')")
 for t in ('estoque_eventos','cmv_eventos','pa_nao_conformes','expedicoes','movimentacoes'): cur.execute(f"INSERT INTO {t} VALUES(1,'preservado')")
 c.commit();c.close();return {"cortada":cortada,"inteira":inteira,"terceiro":terceiro}

def test_paridade_estrutural_exata_e_idempotencia(banco):
 r=rl.aplicar('Teste'); assert r['comparacao']['paridade']; assert len(r['ambiguidades'])==1
 assert r['ambiguidades'][0]['classificacao']=='DECISAO_DE_NEGOCIO_NECESSARIA'
 assert rl.aplicar('Teste')['criados']==[]
 c=dbc.conectar();cur=c.cursor()
 dados={}
 for nome in ('Galinha Cortada','Galinha Inteira'):
  cur.execute("""SELECT re.ordem,re.nome,re.unidade_entrada,re.unidade_saida,re.parametros_json
   FROM roteiro_etapas re JOIN roteiro_versoes rv ON rv.id=re.roteiro_versao_id
   JOIN sku_versoes sv ON sv.id=rv.sku_versao_id WHERE sv.nome=? ORDER BY re.ordem""",(nome,)); dados[nome]=[dict(x) for x in cur.fetchall()]
 assert [x['nome'] for x in dados['Galinha Cortada']]==['Recepção e Pendura','Escalda e Depenagem','Evisceração','Corte','Embalagem','Embalagem Primária','Embalagem Secundária']
 assert [x['nome'] for x in dados['Galinha Inteira']]==['Recepção e Pendura','Escalda e Depenagem','Evisceração','Embalagem','Embalagem Primária']
 assert json.loads(dados['Galinha Cortada'][-1]['parametros_json'])['bandejas_por_caixa']==12
 assert json.loads(dados['Galinha Inteira'][-1]['parametros_json'])['aves_por_pacote']=={'V1':1,'V2':2}
 c.close()

def test_terceiro_sku_nao_recebe_versao_roteiro_ou_autoridade(banco):
 rl.aplicar('Teste'); c=dbc.conectar();cur=c.cursor()
 assert cur.execute('SELECT COUNT(*) n FROM sku_versoes WHERE sku_id=?',(banco['terceiro'],)).fetchone()['n']==0
 assert cur.execute('SELECT COUNT(*) n FROM op_config_snapshots').fetchone()['n']==0
 c.close()

def test_representacao_nao_altera_operacao_historico_ou_financeiro(banco):
 c=dbc.conectar();cur=c.cursor(); tabelas=['ordens_producao','estoque_eventos','cmv_eventos','pa_nao_conformes','expedicoes','movimentacoes']; antes={t:[tuple(x) for x in cur.execute(f'SELECT * FROM {t}').fetchall()] for t in tabelas};c.close()
 rl.aplicar('Teste');c=dbc.conectar();cur=c.cursor()
 for t,linhas in antes.items(): assert [tuple(x) for x in cur.execute(f'SELECT * FROM {t}').fetchall()]==linhas
 assert cur.execute('SELECT COUNT(*) n FROM op_config_snapshots').fetchone()['n']==0;c.close()

def test_comparacao_expõe_divergencia_sem_autocorrecao(banco):
 rl.aplicar('Teste');c=dbc.conectar();cur=c.cursor();cur.execute("UPDATE roteiro_etapas SET unidade_saida='Un' WHERE nome='Corte'");c.commit();c.close()
 resultado=rl.comparar('Galinha Cortada');assert not resultado['paridade'];assert resultado['divergencias']
 assert not rl.comparar_todos()['paridade']
