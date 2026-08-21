from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import time

import pytest
from pypdf import PdfReader

from modules.qualidade import descarte_pnc as descarte
from modules.qualidade import liberacoes
from modules.qualidade import produtos_nao_conformes as nc
from modules.qualidade.descarte_pnc_pdf import gerar_romaneio_descarte_pdf


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "descarte.db"

    def conectar():
        conn = sqlite3.connect(caminho, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transacao():
        conn = conectar()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback(); raise
        finally:
            conn.close()

    for modulo in (nc, descarte, liberacoes):
        monkeypatch.setattr(modulo, "conectar", conectar)
        monkeypatch.setattr(modulo, "transaction", transacao)
        monkeypatch.setattr(modulo, "DATABASE_URL", None)
    conn = conectar()
    conn.executescript("""
      CREATE TABLE locais_estoque(id INTEGER PRIMARY KEY,nome TEXT,tipo TEXT,ativo TEXT);
      INSERT INTO locais_estoque VALUES(4,'Câmara NC','segregacao','Sim');
      CREATE TABLE pa_caixas(id INTEGER PRIMARY KEY,codigo_caixa TEXT,condicao TEXT,disponibilidade TEXT,
        zona_estoque TEXT,motivo_nao_conformidade TEXT,local_estoque_id INTEGER);
      CREATE TABLE expedicoes(id INTEGER PRIMARY KEY,tipo_movimentacao TEXT,status TEXT);
      CREATE TABLE pedidos_venda(id INTEGER PRIMARY KEY,status TEXT);
      CREATE TABLE estoque_operacional_teste(id INTEGER PRIMARY KEY,peso_g INTEGER);
    """)
    conn.commit(); conn.close()
    nc.criar_tabelas_pa_nao_conforme(); descarte.criar_tabelas_descarte_pnc()
    return conectar


def criar_pnc(banco, *, status="DESCARTE", peso=8340430, caixas=689, bandejas=8268,
              numero="PNC-LEG-2026_07_30_CARNE_ESCURA"):
    agora="2026-07-30 12:00:00"; conn=banco()
    cur=conn.execute("""INSERT INTO pa_nao_conformes(numero,produto,apresentacao,quantidade,peso,unidade,motivo,
      status,local_estoque_id,registrado_por,perfil_registro,registrado_em,criado_em,atualizado_em,tipo_registro,
      origem_entrada,caixas_iniciais,bandejas_iniciais,caixas_bloqueadas,bandejas_bloqueadas,saldo_inicial_g,
      saldo_bloqueado_g,saldo_operacional_g,justificativa_destinacao)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      (numero,"Galinha Cortada","Congelada",bandejas,peso/1000,"BANDEJA","Carne Escura",status,4,
       "Inventário","admin",agora,agora,agora,"INVENTARIO_LEGADO_AGREGADO",
       "Inventário físico de Produtos Não Conformes — 30/07/2026",caixas,bandejas,caixas,bandejas,peso,peso,0,
       "Produto impróprio destinado a descarte"))
    conn.commit(); rid=cur.lastrowid; conn.close(); return rid


def dados(chave="DESC-1", modalidade="INTEGRAL", **extra):
    base={"data_saida":(datetime.now()-timedelta(days=1)).date().isoformat(),"hora_saida":"14:30",
      "destino":"Aterro sanitário autorizado","motorista":"José da Silva","motorista_cpf":"",
      "placa":"ABC1D23","responsavel_entrega":"Maria Qualidade","responsavel_recebimento":"João",
      "observacoes":"Saída acompanhada por documento manual","referencia_manual":"MAN-2026-77",
      "saida_ja_realizada":"on","modalidade":modalidade,"idempotency_key":chave}
    base.update(extra); return base


def linha(banco, sql, params=()):
    conn=banco(); item=conn.execute(sql,params).fetchone(); conn.close(); return item


def test_saldo_integral_movimento_snapshot_e_estoque_operacional_zero(banco):
    rid=criar_pnc(banco)
    rom=descarte.registrar_saida_descarte_pnc(rid,dados(),usuario="Admin",perfil="admin",origem="teste")
    registro=linha(banco,"SELECT * FROM pa_nao_conformes WHERE id=?",(rid,))
    mov=linha(banco,"SELECT * FROM pnc_movimentos_descarte WHERE romaneio_id=?",(rom["id"],))
    assert (registro["saldo_bloqueado_g"],registro["caixas_bloqueadas"],registro["bandejas_bloqueadas"]) == (0,0,0)
    assert registro["saldo_operacional_g"] == 0 and registro["status"] == "DESCARTADO"
    assert (mov["tipo"],mov["peso_g"],mov["caixas"],mov["bandejas"]) == ("SAIDA_DESCARTE_PNC",8340430,689,8268)
    snap=json.loads(rom["snapshot_json"])
    assert snap["saida_ja_realizada"] is True and snap["lancado_em"] != snap["saida_fisica_em"]
    assert linha(banco,"SELECT COUNT(*) total FROM expedicoes")["total"] == 0
    assert linha(banco,"SELECT COUNT(*) total FROM pedidos_venda")["total"] == 0
    assert linha(banco,"SELECT COUNT(*) total FROM estoque_operacional_teste")["total"] == 0


def test_saida_parcial_idempotencia_e_segunda_baixa_do_remanescente(banco):
    rid=criar_pnc(banco)
    parcial=dados("PARCIAL-1","PARCIAL",caixas="100",bandejas="1200",peso="1.000,250",galinhas="0",pacotes="0")
    primeira=descarte.registrar_saida_descarte_pnc(rid,parcial,usuario="PCP",perfil="pcp")
    repetida=descarte.registrar_saida_descarte_pnc(rid,parcial,usuario="PCP",perfil="pcp")
    assert primeira["id"] == repetida["id"]
    pnc=linha(banco,"SELECT * FROM pa_nao_conformes WHERE id=?",(rid,))
    assert (pnc["status"],pnc["saldo_bloqueado_g"],pnc["caixas_bloqueadas"],pnc["bandejas_bloqueadas"]) == ("DESCARTE_PARCIAL",7340180,589,7068)
    final=descarte.registrar_saida_descarte_pnc(rid,dados("FINAL"),usuario="Qualidade",perfil="qualidade")
    assert final["id"] != primeira["id"]
    assert linha(banco,"SELECT status FROM pa_nao_conformes WHERE id=?",(rid,))["status"] == "DESCARTADO"


def test_cancela_liberacao_pendente_sem_aprovar_e_vincula_romaneio(banco):
    rid=criar_pnc(banco); agora="2026-08-20 10:00:00"; conn=banco()
    conn.execute("""INSERT INTO pa_nao_conforme_solicitacoes(pa_nao_conforme_id,idempotency_key,peso_g,caixas,
      bandejas,status,justificativa,solicitado_por,perfil_solicitante,solicitado_em,criado_em,atualizado_em)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(rid,"LIB-PEND",500000,40,480,descarte.PENDENTE_LIBERACAO,"liberar","Qualidade","qualidade",agora,agora,agora))
    conn.execute("UPDATE pa_nao_conformes SET saldo_pendente_g=500000 WHERE id=?",(rid,)); conn.commit(); conn.close()
    rom=descarte.registrar_saida_descarte_pnc(rid,dados(),usuario="Gerente",perfil="gerencia")
    sol=linha(banco,"SELECT * FROM pa_nao_conforme_solicitacoes WHERE idempotency_key='LIB-PEND'")
    assert sol["status"] == descarte.CANCELADA_LIBERACAO and sol["romaneio_descarte_id"] == rom["id"]
    assert linha(banco,"SELECT saldo_pendente_g FROM pa_nao_conformes WHERE id=?",(rid,))["saldo_pendente_g"] == 0


def test_liberacao_nao_pode_vencer_corrida_com_destinacao_de_descarte(banco):
    rid=criar_pnc(banco); agora="2026-08-20 10:00:00"; conn=banco()
    cur=conn.execute("""INSERT INTO pa_nao_conforme_solicitacoes(pa_nao_conforme_id,idempotency_key,peso_g,caixas,
      bandejas,status,justificativa,solicitado_por,perfil_solicitante,solicitado_em,criado_em,atualizado_em)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",(rid,"LIB-CORRIDA",500000,40,480,liberacoes.PENDENTE,"liberar","Qualidade","qualidade",agora,agora,agora))
    conn.commit(); sid=cur.lastrowid; conn.close()
    with pytest.raises(ValueError,match="destinado a descarte"):
        liberacoes.validar(sid,"APROVAR","Aprovação",usuario="Gerente",perfil="gerencia",origem="teste")
    assert linha(banco,"SELECT saldo_operacional_g FROM pa_nao_conformes WHERE id=?",(rid,))["saldo_operacional_g"] == 0


def test_inconsistencia_de_saldo_operacional_interrompe_antes_da_baixa(banco):
    rid=criar_pnc(banco); conn=banco(); conn.execute("UPDATE pa_nao_conformes SET saldo_operacional_g=1 WHERE id=?",(rid,)); conn.commit(); conn.close()
    with pytest.raises(ValueError,match="Inconsistência impeditiva"):
        descarte.registrar_saida_descarte_pnc(rid,dados("INCONSISTENTE"),usuario="Admin",perfil="admin")
    assert linha(banco,"SELECT COUNT(*) total FROM pnc_romaneios_descarte")["total"] == 0


@pytest.mark.parametrize("apresentacao,fator",[("Pacote com 1 ave",1),("Pacote com 2 aves",2)])
def test_galinha_inteira_usa_galinhas_e_pacotes_sem_peso_estimado(banco,apresentacao,fator):
    rid=criar_pnc(banco,peso=0,caixas=0,bandejas=0,numero=f"PNC-GI-{fator}")
    conn=banco(); conn.execute("""UPDATE pa_nao_conformes SET produto='Galinha Inteira',apresentacao=?,unidade='PACOTE',
      quantidade=10,pacotes_bloqueados=10,galinhas_bloqueadas=? WHERE id=?""",(apresentacao,10*fator,rid)); conn.commit(); conn.close()
    parcial=dados(f"GI-{fator}","PARCIAL",caixas=0,bandejas=0,peso=0,pacotes=3,galinhas=3*fator)
    rom=descarte.registrar_saida_descarte_pnc(rid,parcial,usuario="Admin",perfil="admin")
    snap=json.loads(rom["snapshot_json"])
    assert snap["saida"]["pacotes"] == 3 and snap["saida"]["galinhas"] == 3*fator and snap["saida"]["peso_g"] == 0


def test_unidades_incompativeis_nao_sao_somadas(banco):
    rid=criar_pnc(banco)
    with pytest.raises(ValueError,match="Galinha Cortada"):
        descarte.registrar_saida_descarte_pnc(rid,dados("UNIDADE-RUIM","PARCIAL",caixas=1,bandejas=1,peso="0,001",pacotes=1,galinhas=1),usuario="Admin",perfil="admin")


def test_cancelamento_so_existe_para_rascunho_e_nao_exclui(banco):
    rid=criar_pnc(banco); agora="2026-08-21 10:00:00"; conn=banco()
    cur=conn.execute("""INSERT INTO pnc_romaneios_descarte(numero,pa_nao_conforme_id,status,idempotency_key,
      saida_fisica_em,lancado_em,destino,motorista,placa,responsavel_entrega,usuario_emissor,perfil_emissor,
      snapshot_json,criado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",("RASC-1",rid,"RASCUNHO","RASC-1",agora,agora,"Destino","Motorista","ABC1D23","Entrega","Admin","admin","{}",agora))
    conn.commit(); rom_id=cur.lastrowid; conn.close()
    descarte.cancelar_romaneio_descarte(rom_id,"Documento não confirmado",usuario="Admin",perfil="admin")
    assert linha(banco,"SELECT status FROM pnc_romaneios_descarte WHERE id=?",(rom_id,))["status"] == "CANCELADO"


@pytest.mark.parametrize("status",["BLOQUEADO","LIBERADO","DESCARTADO"])
def test_rejeita_pnc_sem_destinacao_ou_sem_saldo(status,banco):
    rid=criar_pnc(banco,status=status,peso=0 if status=="DESCARTADO" else 1000,caixas=0,bandejas=0)
    with pytest.raises(ValueError):
        descarte.registrar_saida_descarte_pnc(rid,dados(f"INVALIDO-{status}"),usuario="Admin",perfil="admin")


def test_saldo_insuficiente_permissao_e_rollback_integral(banco):
    rid=criar_pnc(banco,peso=100000,caixas=2,bandejas=20)
    with pytest.raises(PermissionError):
        descarte.registrar_saida_descarte_pnc(rid,dados("SEM-PERM"),usuario="Operador",perfil="producao")
    with pytest.raises(ValueError):
        descarte.registrar_saida_descarte_pnc(rid,dados("EXCEDE","PARCIAL",caixas=3,bandejas=1,peso="0,010"),usuario="Admin",perfil="admin")
    def falhar(etapa):
        if etapa == "antes_commit": raise RuntimeError("falha simulada")
    with pytest.raises(RuntimeError):
        descarte.registrar_saida_descarte_pnc(rid,dados("ROLLBACK"),usuario="Admin",perfil="admin",checkpoint=falhar)
    assert linha(banco,"SELECT COUNT(*) total FROM pnc_romaneios_descarte")["total"] == 0
    assert linha(banco,"SELECT saldo_bloqueado_g FROM pa_nao_conformes WHERE id=?",(rid,))["saldo_bloqueado_g"] == 100000


def test_estorno_autorizado_exato_e_duplicado_bloqueado(banco):
    rid=criar_pnc(banco); rom=descarte.registrar_saida_descarte_pnc(rid,dados(),usuario="Admin",perfil="admin")
    with pytest.raises(PermissionError): descarte.estornar_romaneio_descarte(rom["id"],"erro",usuario="PCP",perfil="pcp")
    resultado=descarte.estornar_romaneio_descarte(rom["id"],"Saída lançada no PNC incorreto",usuario="Gerente",perfil="gerencia")
    assert resultado["pnc_status"] == "DESCARTE"
    pnc=linha(banco,"SELECT * FROM pa_nao_conformes WHERE id=?",(rid,))
    assert (pnc["saldo_bloqueado_g"],pnc["caixas_bloqueadas"],pnc["bandejas_bloqueadas"],pnc["saldo_operacional_g"]) == (8340430,689,8268,0)
    assert linha(banco,"SELECT COUNT(*) total FROM pnc_movimentos_descarte WHERE romaneio_id=?",(rom["id"],))["total"] == 2
    with pytest.raises(ValueError): descarte.estornar_romaneio_descarte(rom["id"],"duplicado",usuario="Gerente",perfil="gerencia")


def test_movimento_e_item_sao_imutaveis_e_pdf_reimprime_snapshot(banco):
    rid=criar_pnc(banco); rom=descarte.registrar_saida_descarte_pnc(rid,dados(),usuario="Admin",perfil="admin")
    conn=banco()
    with pytest.raises(sqlite3.IntegrityError): conn.execute("UPDATE pnc_movimentos_descarte SET peso_g=1 WHERE romaneio_id=?",(rom["id"],))
    conn.rollback(); conn.execute("UPDATE pa_nao_conformes SET produto='ALTERADO',saldo_bloqueado_g=999 WHERE id=?",(rid,)); conn.commit(); conn.close()
    original=descarte.obter_romaneio_descarte(rom["id"])["snapshot"]
    pdf=gerar_romaneio_descarte_pdf(original)
    texto="".join(p.extract_text() or "" for p in PdfReader(__import__('io').BytesIO(pdf)).pages)
    assert "Galinha Cortada" in texto and "8.340,430" in texto and "ALTERADO" not in texto


def test_legado_sem_op_lote_validade_e_data_fisica_anterior(banco):
    rid=criar_pnc(banco); previa=descarte.previa_saida_descarte_pnc(linha(banco,"SELECT * FROM pa_nao_conformes WHERE id=?",(rid,)),{"modalidade":"INTEGRAL"})
    assert previa["saida"] == {"peso_g":8340430,"caixas":689,"bandejas":8268,"pacotes":0,"galinhas":0}
    rom=descarte.registrar_saida_descarte_pnc(rid,dados("LEGADO"),usuario="Admin",perfil="admin")
    assert rom["saida_fisica_em"] < rom["lancado_em"]


def test_migration_sqlite_upgrade_downgrade_upgrade(tmp_path):
    raiz=__import__('pathlib').Path(__file__).resolve().parents[1]
    upgrade=(raiz/"database"/"20260821_romaneio_descarte_pnc_sqlite.sql").read_text(encoding="utf-8")
    downgrade=(raiz/"database"/"20260821_romaneio_descarte_pnc_sqlite_rollback.sql").read_text(encoding="utf-8")
    conn=sqlite3.connect(tmp_path/"migration.db")
    conn.executescript("""CREATE TABLE pa_nao_conformes(id INTEGER PRIMARY KEY);
      CREATE TABLE pa_nao_conforme_solicitacoes(id INTEGER PRIMARY KEY);""")
    conn.executescript(upgrade)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='pnc_romaneios_descarte'").fetchone()
    conn.executescript(downgrade)
    assert not conn.execute("SELECT name FROM sqlite_master WHERE name='pnc_romaneios_descarte'").fetchone()
    conn.executescript(upgrade)
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='pnc_movimentos_descarte'").fetchone()
    conn.close()


def test_feature_flag_e_csrf_da_rota(monkeypatch):
    from flask import Flask
    from modules.qualidade import routes
    raiz=__import__('pathlib').Path(__file__).resolve().parents[1]
    app=Flask(__name__,template_folder=str(raiz/"templates")); app.secret_key="teste"
    app.jinja_env.filters["br_numero"] = lambda valor, casas=2: f"{float(valor or 0):.{casas}f}"
    @app.get("/login")
    def login(): return "login"
    @app.get("/dashboard")
    def dashboard(): return "dashboard"
    @app.get("/")
    def inicio(): return "inicio"
    @app.get("/sair")
    def sair(): return "sair"
    registro={"id":1,"numero":"PNC-1","status":"DESCARTE","produto":"Galinha Cortada","apresentacao":"Congelada",
      "motivo":"Carne Escura","origem_entrada":"Inventário","tipo_registro":"INVENTARIO_LEGADO_AGREGADO",
      "saldo_bloqueado_g":1000,"caixas_bloqueadas":1,"bandejas_bloqueadas":12,"galinhas_bloqueadas":0,
      "pacotes_bloqueados":0,"peso":1,"quantidade":12,"unidade":"BANDEJA"}
    monkeypatch.setattr(routes,"obter_detalhe_pa_nc",lambda _:(registro,[]))
    routes.register_qualidade_routes(app)
    cliente=app.test_client()
    with cliente.session_transaction() as sess:
        sess.update({"usuario_id":1,"nome":"Admin","perfil":"admin"})
    url="/qualidade/produtos-nao-conformes/1/romaneio-descarte"
    assert cliente.get(url).status_code == 404
    app.config["PNC_DISCARD_WAYBILL_ENABLED"] = True
    assert cliente.get(url).status_code == 200
    assert cliente.post(url+"/previa",data={}).status_code == 400
    with cliente.session_transaction() as sess:
        token = sess["csrf_descarte_pnc"]
    resposta = cliente.post(url+"/previa", data={"csrf_token": token, "modalidade": "INTEGRAL"})
    assert resposta.status_code == 200
    conteudo = resposta.get_data(as_text=True)
    assert "1.000 kg" in conteudo
    assert "Nenhuma saída foi registrada" in conteudo
    assert "CONFIRMAR SAÍDA PARA DESCARTE" not in conteudo


def test_duas_baixas_simultaneas_nao_consumem_o_mesmo_saldo(banco, monkeypatch):
    rid=criar_pnc(banco,peso=100000,caixas=2,bandejas=20)
    monkeypatch.setattr(descarte,"criar_tabelas_descarte_pnc",lambda:None)
    def executar(chave):
        try:
            return descarte.registrar_saida_descarte_pnc(rid,dados(chave),usuario="Admin",perfil="admin",
                checkpoint=lambda etapa: time.sleep(.08) if etapa=="revalidado" else None)["id"]
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados=list(pool.map(executar,("CONC-1","CONC-2")))
    assert sum(item is not None for item in resultados) == 1
    assert linha(banco,"SELECT COUNT(*) total FROM pnc_movimentos_descarte WHERE tipo='SAIDA_DESCARTE_PNC'")["total"] == 1
