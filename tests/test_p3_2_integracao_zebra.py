"""P3.2 — matriz numerada 01–39, sem acesso a impressora física."""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from flask import Flask
import pytest

from modules.label_printing import services as svc
from local_print_agent.adapters import NiceLabelAutomationAdapter, SimulatedAdapter


CASOS = [f"{numero:02d}" for numero in range(1, 40)]


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    banco = tmp_path / "p32.db"
    def conectar():
        conn = sqlite3.connect(banco); conn.row_factory = sqlite3.Row; return conn
    @contextmanager
    def transaction():
        conn = conectar()
        try:
            yield conn; conn.commit()
        except Exception:
            conn.rollback(); raise
        finally: conn.close()
    monkeypatch.setattr(svc, "conectar", conectar); monkeypatch.setattr(svc, "transaction", transaction)
    svc.criar_tabelas_impressao_etiquetas()
    conn = conectar(); conn.execute("""CREATE TABLE pa_caixas(id INTEGER PRIMARY KEY,codigo_caixa TEXT,sku TEXT,
        data_fabricacao TEXT,data_validade TEXT,peso_bruto TEXT,peso_liquido TEXT,peso_tara TEXT,
        quantidade_bandejas TEXT,status TEXT)""")
    conn.execute("CREATE TABLE pa_caixa_composicao(id INTEGER PRIMARY KEY,caixa_id INTEGER,op_id INTEGER,quantidade_bandejas TEXT)")
    conn.execute("INSERT INTO pa_caixas VALUES(1,'CX-OFICIAL-001','Galinha Cortada','2026-08-26','2027-08-26','12.500','12.000','0.500','10','Em estoque')")
    conn.execute("INSERT INTO pa_caixa_composicao VALUES(1,1,161,'10')")
    modelo = tmp_path / "ETIQUETA CAIXA.nlbl"; modelo.write_bytes(b"modelo-controlado")
    sha = hashlib.sha256(modelo.read_bytes()).hexdigest()
    conn.execute("""INSERT INTO label_model_configs(sku,apresentacao,label_type,template_path,template_sha256,
        printer_allowlist,variable_map_json,pieces_source,ativo,criado_em) VALUES(?,?,?,?,?,?,?,?,1,?)""",
        ("Galinha Cortada","Galinha Cortada","CAIXA_PA",str(modelo),sha,json.dumps(["ZDesigner ZD220"]),
         json.dumps(svc.VARIAVEIS_CENTRAIS),"quantidade_bandejas",svc._agora()))
    conn.commit(); conn.close()
    app = Flask(__name__); app.config.update(TESTING=True,SECRET_KEY="teste",
        LABEL_PRINTING_ENABLED=True,BOX_LABEL_AUTO_PRINT_ENABLED=True,LOCAL_PRINT_AGENT_ENABLED=True)
    return app, conectar, modelo, sha


def _job(app, conectar):
    with app.app_context():
        with svc.transaction() as conn:
            uuid = svc.criar_job_caixa_cursor(conn.cursor(), 1, solicitado_por="Teste")
    conn = conectar(); row = conn.execute("SELECT * FROM label_print_jobs WHERE job_uuid=?", (uuid,)).fetchone(); conn.close()
    return dict(row)


def _agente_e_lease(app, conectar):
    job = _job(app, conectar)
    conn = conectar(); conn.execute("INSERT INTO local_print_agents(agent_uuid,nome,station_code,status,auto_print_enabled,criado_em) VALUES('a','A','E','ATIVO',1,?)", (svc._agora(),)); conn.commit(); aid=conn.execute("SELECT id FROM local_print_agents").fetchone()[0]; conn.close()
    with app.app_context(): leased = svc.obter_proximo_job(aid, printer_name="ZDesigner ZD220", printer_model="ZD220")
    return job, leased


@pytest.mark.parametrize("caso", CASOS, ids=[f"P3.2-{c}" for c in CASOS])
def test_matriz_p3_2_01_a_39(caso, ambiente):
    app, conectar, modelo, sha = ambiente
    if caso == "01":
        conn=conectar(); assert {"label_print_jobs","local_print_agents","label_model_configs"} <= {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}; conn.close()
    elif caso == "02":
        from config import Config; assert not Config.LABEL_PRINTING_ENABLED and not Config.BOX_LABEL_AUTO_PRINT_ENABLED and not Config.LOCAL_PRINT_AGENT_ENABLED
    elif caso == "03": assert set(svc.VARIAVEIS_CENTRAIS) == {"fabricacao","validade","lote","pecas","peso_bruto","tara","peso_liquido"}
    elif caso == "04":
        with svc.transaction() as c: snap=svc._snapshot_caixa(c.cursor(),1)
        assert snap["peso_bruto"] == "12.500" and snap["codigo_caixa"] == "CX-OFICIAL-001"
    elif caso == "05":
        conn=conectar(); conn.execute("UPDATE pa_caixas SET peso_tara='0.400' WHERE id=1"); conn.commit(); conn.close()
        with pytest.raises(ValueError, match="bruto"):
            with svc.transaction() as c: svc._snapshot_caixa(c.cursor(),1)
    elif caso == "06":
        conn=conectar(); conn.execute("UPDATE pa_caixas SET quantidade_bandejas='1.5' WHERE id=1"); conn.commit(); conn.close()
        with pytest.raises(ValueError, match="peças"):
            with svc.transaction() as c: svc._snapshot_caixa(c.cursor(),1)
    elif caso == "07":
        conn=conectar(); conn.execute("UPDATE label_model_configs SET ativo=0"); conn.commit(); conn.close()
        with app.app_context():
            with svc.transaction() as c: assert svc.criar_job_caixa_cursor(c.cursor(),1) is None
    elif caso == "08":
        app.config["BOX_LABEL_AUTO_PRINT_ENABLED"]=False
        with app.app_context():
            with svc.transaction() as c: assert svc.criar_job_caixa_cursor(c.cursor(),1) is None
    elif caso == "09": assert _job(app, conectar)["state"] == "PENDENTE"
    elif caso == "10":
        _job(app,conectar)
        with app.app_context(), pytest.raises(sqlite3.IntegrityError):
            with svc.transaction() as c: svc.criar_job_caixa_cursor(c.cursor(),1)
    elif caso == "11":
        job=_job(app,conectar); conn=conectar(); conn.execute("UPDATE pa_caixas SET peso_bruto='99' WHERE id=1"); conn.commit(); assert json.loads(job["snapshot_json"])["peso_bruto"] == "12.500"; conn.close()
    elif caso == "12":
        first=_job(app,conectar)
        with app.app_context(): uuid=svc.solicitar_reimpressao(1,usuario="Gerência",justificativa="Etiqueta física danificada")
        conn=conectar(); row=conn.execute("SELECT * FROM label_print_jobs WHERE job_uuid=?",(uuid,)).fetchone(); assert row["generation"]==2 and row["original_job_id"]==first["id"]; conn.close()
    elif caso == "13":
        _job(app,conectar)
        with app.app_context(), pytest.raises(ValueError,match="justificativa"): svc.solicitar_reimpressao(1,usuario="G",justificativa="curta")
    elif caso == "14":
        _job(app,conectar); app.config["LABEL_PRINTING_ENABLED"]=False
        with app.app_context(), pytest.raises(ValueError,match="desabilitada"): svc.solicitar_reimpressao(1,usuario="G",justificativa="Justificativa suficiente")
    elif caso == "15":
        with app.app_context(), pytest.raises(ValueError,match="original"): svc.solicitar_reimpressao(1,usuario="G",justificativa="Justificativa suficiente")
    elif caso == "16":
        _job(app,conectar)
        with svc.transaction() as c: svc.invalidar_jobs_caixa_cursor(c.cursor(),1)
        conn=conectar(); assert conn.execute("SELECT state FROM label_print_jobs").fetchone()[0]=="INVALIDADA"; conn.close()
    elif caso == "17":
        _job(app,conectar); conn=conectar(); conn.execute("UPDATE label_print_jobs SET state='ENVIADA_IMPRESSORA'"); conn.commit(); conn.close()
        with svc.transaction() as c: svc.invalidar_jobs_caixa_cursor(c.cursor(),1)
        conn=conectar(); row=conn.execute("SELECT state,box_reversed FROM label_print_jobs").fetchone(); assert tuple(row)==("ENVIADA_IMPRESSORA",1); conn.close()
    elif caso == "18":
        app.config["LOCAL_PRINT_AGENT_ENABLED"]=False
        with app.app_context(), pytest.raises(ValueError,match="desabilitado"): svc.criar_codigo_pareamento("a","A","E")
    elif caso == "19":
        with app.app_context(): code=svc.criar_codigo_pareamento("a","A","E")
        assert len(code)==6 and code.isdigit()
    elif caso == "20":
        with app.app_context(): svc.criar_codigo_pareamento("a","A","E")
        with app.app_context(), pytest.raises(ValueError,match="inválido"): svc.parear_agente("a","000000")
    elif caso == "21":
        with app.app_context(): code=svc.criar_codigo_pareamento("a","A","E"); token=svc.parear_agente("a",code)
        conn=conectar(); row=conn.execute("SELECT token_hash,pairing_code_hash FROM local_print_agents").fetchone(); assert token not in row[0] and row[1] is None; conn.close()
    elif caso == "22":
        with app.app_context(): code=svc.criar_codigo_pareamento("a","A","E"); token=svc.parear_agente("a",code); assert svc.autenticar_agente(token)["agent_uuid"]=="a"
    elif caso == "23":
        with app.app_context(): assert svc.autenticar_agente("incorreto") is None
    elif caso == "24":
        conn=conectar(); conn.execute("INSERT INTO local_print_agents(agent_uuid,nome,station_code,status,auto_print_enabled,criado_em) VALUES('a','A','E','ATIVO',1,?)",(svc._agora(),)); conn.commit(); aid=conn.execute("SELECT id FROM local_print_agents").fetchone()[0]; conn.close()
        with app.app_context(): assert svc.obter_proximo_job(aid,printer_name="ZDesigner ZD220",printer_model="ZD220") is None
    elif caso == "25":
        job=_job(app,conectar); conn=conectar(); conn.execute("INSERT INTO local_print_agents(agent_uuid,nome,station_code,status,auto_print_enabled,criado_em) VALUES('a','A','E','ATIVO',1,?)",(svc._agora(),)); conn.commit(); aid=conn.execute("SELECT id FROM local_print_agents").fetchone()[0]; conn.close()
        with app.app_context(), pytest.raises(ValueError,match="allowlist"): svc.obter_proximo_job(aid,printer_name="Outra",printer_model="ZD220")
    elif caso == "26":
        job,leased=_agente_e_lease(app,conectar); assert leased["lease_token"] and leased["snapshot"]["codigo_caixa"]=="CX-OFICIAL-001"
    elif caso in {"27","28","29","30"}:
        job,leased=_agente_e_lease(app,conectar); outcome={"27":"SPOOL_ACCEPTED","28":"AMBIGUOUS","29":"TEMPORARY_FAILURE","30":"PERMANENT_FAILURE"}[caso]
        expected={"27":"ENVIADA_IMPRESSORA","28":"CONFERENCIA_NECESSARIA","29":"FALHA_TEMPORARIA","30":"FALHA_PERMANENTE"}[caso]
        assert svc.registrar_resultado(job["job_uuid"],leased["lease_token"],outcome=outcome)==expected
    elif caso == "31":
        job,leased=_agente_e_lease(app,conectar)
        with pytest.raises(ValueError,match="inválido"): svc.registrar_resultado(job["job_uuid"],leased["lease_token"],outcome="PRINTED")
    elif caso == "32":
        job,leased=_agente_e_lease(app,conectar)
        with pytest.raises(ValueError,match="Lease"): svc.registrar_resultado(job["job_uuid"],"errado",outcome="SPOOL_ACCEPTED")
    elif caso == "33":
        job=_job(app,conectar)
        with pytest.raises(ValueError,match="disponível"): svc.registrar_resultado(job["job_uuid"],"x",outcome="SPOOL_ACCEPTED")
    elif caso == "34":
        job={"template_path":str(modelo),"template_sha256":sha,"job_uuid":"12345678"}; assert SimulatedAdapter().send(job,"ZDesigner ZD220").outcome=="SPOOL_ACCEPTED"
    elif caso == "35":
        with pytest.raises(RuntimeError,match="HASH"): SimulatedAdapter().send({"template_path":str(modelo),"template_sha256":"0"*64,"job_uuid":"12345678"},"Z")
    elif caso == "36": assert NiceLabelAutomationAdapter().capability()["reason"]=="NICELABEL_AUTOMATION_NOT_AUDITED"
    elif caso == "37": assert Path("database/20260826_p3_2_integracao_zebra.sql").exists() and Path("database/20260826_p3_2_integracao_zebra_rollback.sql").exists()
    elif caso == "38": assert "pesagem_app" not in Path("local_print_agent/agent.py").read_text(encoding="utf-8")
    elif caso == "39": assert "Enviada à impressora" in Path("docs/P3_2_INTEGRACAO_ZEBRA_ZD220.md").read_text(encoding="utf-8")
