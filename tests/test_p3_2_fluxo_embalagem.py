"""Integração transacional P3.2 com inclusão individual e em lote."""

from contextlib import contextmanager
import hashlib
import json
import sqlite3

from flask import Flask
import pytest

from modules.expedicao import services as expedicao
from modules.expedicao import conferencia_embalagem
from modules.label_printing import services as labels


@pytest.fixture
def fluxo(tmp_path, monkeypatch):
    banco = tmp_path / "fluxo.db"
    def conectar():
        c=sqlite3.connect(banco); c.row_factory=sqlite3.Row; return c
    @contextmanager
    def transaction():
        c=conectar()
        try: yield c; c.commit()
        except Exception: c.rollback(); raise
        finally: c.close()
    monkeypatch.setattr(labels,"conectar",conectar); monkeypatch.setattr(labels,"transaction",transaction)
    monkeypatch.setattr(expedicao,"conectar",conectar); monkeypatch.setattr(expedicao,"transaction",transaction)
    labels.criar_tabelas_impressao_etiquetas()
    c=conectar(); c.executescript("""
      CREATE TABLE pa_caixas(id INTEGER PRIMARY KEY AUTOINCREMENT,codigo_caixa TEXT,sku TEXT,data_fabricacao TEXT,data_validade TEXT,peso_bruto TEXT,peso_liquido TEXT,peso_tara TEXT,quantidade_bandejas TEXT,status TEXT,usuario_pesagem TEXT);
      CREATE TABLE pa_caixa_composicao(id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,op_id INTEGER,quantidade_bandejas TEXT);
      CREATE TABLE embalagem_secundaria_requisicoes(op_id INTEGER,acao TEXT,idempotency_key TEXT UNIQUE,resultado_json TEXT,usuario TEXT,criado_em TEXT,repeticoes INTEGER DEFAULT 0,ultimo_reenvio_em TEXT);
    """)
    modelo=tmp_path/"m.nlbl"; modelo.write_bytes(b"modelo")
    c.execute("""INSERT INTO label_model_configs(sku,apresentacao,label_type,template_path,template_sha256,printer_allowlist,variable_map_json,pieces_source,ativo,criado_em)
      VALUES('Galinha Cortada','Galinha Cortada','CAIXA_PA',?,?,?,?,?,1,?)""",(str(modelo),hashlib.sha256(b"modelo").hexdigest(),json.dumps(["Zebra"]),json.dumps(labels.VARIAVEIS_CENTRAIS),"quantidade_bandejas",labels._agora()))
    c.commit(); c.close()
    monkeypatch.setattr(expedicao,"criar_tabelas_estoque_pi_pa",lambda:None)
    monkeypatch.setattr(conferencia_embalagem,"criar_tabelas_conferencia_embalagem",lambda:None)
    monkeypatch.setattr(expedicao,"_resultado_requisicao_embalagem_persistido",lambda chave:None)
    monkeypatch.setattr(expedicao,"preparar_composicao_caixa",lambda form:([(161,10)],10,"Galinha Cortada"))
    monkeypatch.setattr(expedicao,"validar_saldo_pi_para_composicoes",lambda composicoes:None)
    monkeypatch.setattr(expedicao,"buscar_op_por_id",lambda op:{"data":"2026-08-26"})
    monkeypatch.setattr(expedicao,"_validar_lancamento_secundaria_cursor",lambda cursor,consumo:{161:{"data":"2026-08-26"}})
    monkeypatch.setattr(expedicao,"_invalidar_conferencia_por_inclusao",lambda cursor,ops:None)
    monkeypatch.setattr(expedicao,"_gerar_codigo_caixa_cursor",lambda cursor:"CX-20260826-001")
    def inserir(cursor,codigo,sku,fab,val,bruto,liquido,bandejas,obs,composicao):
        cursor.execute("INSERT INTO pa_caixas(codigo_caixa,sku,data_fabricacao,data_validade,peso_bruto,peso_liquido,peso_tara,quantidade_bandejas,status) VALUES(?,?,?,?,?,?,?,?,?)",
          (codigo,sku,fab,val,str(bruto),str(liquido),str(bruto-liquido),str(bandejas),"Em estoque")); caixa=cursor.lastrowid
        cursor.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(?,?,?)",(caixa,161,str(bandejas))); return caixa
    monkeypatch.setattr(expedicao,"inserir_caixa_pa",inserir)
    app=Flask(__name__); app.config.update(LABEL_PRINTING_ENABLED=True,BOX_LABEL_AUTO_PRINT_ENABLED=True,LOCAL_PRINT_AGENT_ENABLED=True)
    return app, conectar


def _form(chave="req-1", lote=False):
    base={"idempotency_key":chave,"peso_bruto":"12.500","peso_liquido":"12.000","data_fabricacao":"2026-08-26","data_validade":"2027-08-26"}
    if lote: base.update(pesos_brutos_lote="12.500\n13.500\n14.500\n15.500\n16.500",pesos_liquidos_lote="12.000\n13.000\n14.000\n15.000\n16.000")
    return base


def test_30_uma_caixa_gera_um_job(fluxo):
    app,conectar=fluxo
    with app.app_context(): expedicao.registrar_caixa_pa_manual(_form(),usuario="Operador")
    c=conectar(); assert c.execute("SELECT COUNT(*) FROM label_print_jobs").fetchone()[0]==1; c.close()


def test_31_cinco_caixas_geram_cinco_jobs(fluxo):
    app,conectar=fluxo
    with app.app_context(): codigos=expedicao.registrar_caixas_pa_lote(_form(lote=True),usuario="Operador")
    c=conectar(); assert len(codigos)==5 and c.execute("SELECT COUNT(*) FROM label_print_jobs").fetchone()[0]==5; c.close()


def test_32_ordem_do_lote_e_preservada(fluxo):
    app,conectar=fluxo
    with app.app_context(): codigos=expedicao.registrar_caixas_pa_lote(_form(lote=True),usuario="Operador")
    c=conectar(); jobs=[json.loads(r[0])["codigo_caixa"] for r in c.execute("SELECT snapshot_json FROM label_print_jobs ORDER BY id")]; c.close(); assert jobs==codigos


def test_33_um_job_individual_por_caixa(fluxo):
    app,conectar=fluxo
    with app.app_context(): expedicao.registrar_caixas_pa_lote(_form(lote=True),usuario="Operador")
    c=conectar(); assert c.execute("SELECT COUNT(DISTINCT caixa_id) FROM label_print_jobs").fetchone()[0]==5; c.close()


def test_34_rollback_do_lote_remove_caixas_e_jobs(fluxo,monkeypatch):
    app,conectar=fluxo; original=expedicao.inserir_caixa_pa; chamadas={"n":0}
    def falhar(*args,**kwargs):
        chamadas["n"]+=1
        if chamadas["n"]==3: raise RuntimeError("falha controlada")
        return original(*args,**kwargs)
    monkeypatch.setattr(expedicao,"inserir_caixa_pa",falhar)
    with app.app_context(),pytest.raises(RuntimeError): expedicao.registrar_caixas_pa_lote(_form(lote=True),usuario="Operador")
    c=conectar(); assert c.execute("SELECT COUNT(*) FROM pa_caixas").fetchone()[0]==0 and c.execute("SELECT COUNT(*) FROM label_print_jobs").fetchone()[0]==0; c.close()
