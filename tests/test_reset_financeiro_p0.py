"""Regressoes do reset P0 controlado do modulo Financeiro."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from io import BytesIO

import pytest

from database import connection
from modules.movimentacoes import reset_financeiro as reset
from modules.movimentacoes.services import (
    alterar_origem_principal_movimentacao,
    atualizar_movimentacao_financeira,
    corrigir_natureza_aportes_fluxo_caixa,
    excluir_movimentacao_financeira,
    importar_movimentacoes_financeiras_excel,
    reclassificar_movimentacoes,
    salvar_movimentacao_financeira,
    sincronizar_movimentacoes_plano_contas,
)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE movimentacoes_financeiras (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_documento TEXT, data_vencimento TEXT NOT NULL, data_realizacao TEXT,
    tipo TEXT NOT NULL, categoria TEXT NOT NULL, descricao TEXT NOT NULL,
    valor REAL NOT NULL, valor_documento REAL DEFAULT 0, valor_pago REAL DEFAULT 0,
    status TEXT DEFAULT 'Pendente', documento_id TEXT, import_key TEXT
);
CREATE TABLE movimentacoes_financeiras_importacao_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, arquivo_nome TEXT NOT NULL,
    arquivo_hash TEXT NOT NULL, tipo_importador TEXT NOT NULL,
    modo_origem TEXT NOT NULL, usuario_nome TEXT NOT NULL, status TEXT NOT NULL,
    iniciado_em TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE movimentacoes_financeiras_origens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movimentacao_id INTEGER NOT NULL REFERENCES movimentacoes_financeiras(id),
    lote_importacao_id INTEGER REFERENCES movimentacoes_financeiras_importacao_lotes(id),
    chave_idempotente TEXT, status TEXT DEFAULT 'ATIVA'
);
CREATE TABLE movimentacoes_financeiras_importacao_linhas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id INTEGER NOT NULL REFERENCES movimentacoes_financeiras_importacao_lotes(id),
    movimentacao_id INTEGER REFERENCES movimentacoes_financeiras(id),
    hash_normalizado TEXT NOT NULL, status TEXT NOT NULL
);
CREATE TABLE movimentacoes_financeiras_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT, movimentacao_id INTEGER NOT NULL,
    acao TEXT NOT NULL, usuario_nome TEXT NOT NULL, data_hora TEXT NOT NULL
);
CREATE TABLE movimentacoes_financeiras_configuracao_corte (
    id INTEGER PRIMARY KEY, data_corte TEXT, ativo INTEGER DEFAULT 0
);
CREATE TABLE plano_contas_mestre (id INTEGER PRIMARY KEY, nome TEXT NOT NULL);
CREATE TABLE clientes (id INTEGER PRIMARY KEY, nome TEXT NOT NULL);
CREATE TABLE fornecedores (id INTEGER PRIMARY KEY, nome TEXT NOT NULL);
CREATE TABLE produtos (id INTEGER PRIMARY KEY, nome TEXT NOT NULL);
CREATE TABLE estoque_eventos (id INTEGER PRIMARY KEY, acao TEXT NOT NULL);
CREATE TABLE ordens_producao (id INTEGER PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE pedidos_venda (id INTEGER PRIMARY KEY, numero TEXT NOT NULL);
CREATE TABLE expedicoes (id INTEGER PRIMARY KEY, numero_romaneio TEXT NOT NULL);
CREATE TABLE expedicao_itens (id INTEGER PRIMARY KEY, expedicao_id INTEGER NOT NULL);
CREATE TABLE pa_nao_conformes (id INTEGER PRIMARY KEY, status TEXT NOT NULL);
CREATE TABLE vendas_diarias (id INTEGER PRIMARY KEY, receita REAL NOT NULL);
CREATE TABLE custos_mensais (id INTEGER PRIMARY KEY, valor REAL NOT NULL);
CREATE TABLE documentos_operacionais (
    id INTEGER PRIMARY KEY, numero TEXT NOT NULL,
    movimentacao_id INTEGER REFERENCES movimentacoes_financeiras(id)
);
"""


SEED = """
INSERT INTO movimentacoes_financeiras
    (id,data_documento,data_vencimento,data_realizacao,tipo,categoria,descricao,
     valor,valor_documento,valor_pago,status,documento_id,import_key)
VALUES
    (10,'2026-07-01','2026-07-15',NULL,'Entrada','Receita','Titulo aberto',1000,1000,0,'Pendente','PV-1','key-1'),
    (11,'2026-07-02','2026-07-16','2026-07-10','Saida','Fornecedor','Titulo pago',500,500,500,'Realizado',NULL,'key-2');
INSERT INTO movimentacoes_financeiras_importacao_lotes
    (id,arquivo_nome,arquivo_hash,tipo_importador,modo_origem,usuario_nome,status)
VALUES (20,'antigo.xlsx','hash-antigo','excel','IMPORTACAO_FINANCEIRA','Carga','CONCLUIDO');
INSERT INTO movimentacoes_financeiras_origens
    (id,movimentacao_id,lote_importacao_id,chave_idempotente,status)
VALUES (30,10,20,'key-1','ATIVA'),(31,11,20,'key-2','ATIVA');
INSERT INTO movimentacoes_financeiras_importacao_linhas
    (id,lote_id,movimentacao_id,hash_normalizado,status)
VALUES (40,20,10,'linha-1','IMPORTADA'),(41,20,11,'linha-2','IMPORTADA');
INSERT INTO movimentacoes_financeiras_auditoria
    (id,movimentacao_id,acao,usuario_nome,data_hora)
VALUES (50,10,'CRIACAO_IMPORTACAO','Carga','2026-07-01');
INSERT INTO movimentacoes_financeiras_configuracao_corte VALUES (1,'2026-01-01',1);
INSERT INTO plano_contas_mestre VALUES (1,'Receita Bruta');
INSERT INTO clientes VALUES (1,'Cliente preservado');
INSERT INTO fornecedores VALUES (1,'Fornecedor preservado');
INSERT INTO produtos VALUES (1,'Produto preservado');
INSERT INTO estoque_eventos VALUES (1,'ENTRADA');
INSERT INTO ordens_producao VALUES (1,'Encerrada');
INSERT INTO pedidos_venda VALUES (1,'PV-1');
INSERT INTO expedicoes VALUES (1,'ROM-1');
INSERT INTO expedicao_itens VALUES (1,1);
INSERT INTO pa_nao_conformes VALUES (1,'BLOQUEADO');
INSERT INTO vendas_diarias VALUES (1,1500);
INSERT INTO custos_mensais VALUES (1,700);
INSERT INTO documentos_operacionais VALUES (1,'DOC-1',10);
"""


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _all_rows(path):
    conn = _connect(path)
    result = {}
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name<>'sqlite_sequence' ORDER BY name"):
        result[table] = [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY 1')]
    conn.close()
    return result


@pytest.fixture
def reset_db(tmp_path, monkeypatch):
    db = tmp_path / "frigodatta-reset.db"
    conn = _connect(db)
    conn.executescript(SCHEMA)
    conn.executescript(SEED)
    conn.commit()
    conn.close()
    monkeypatch.setattr(connection, "DB_NAME", str(db))
    monkeypatch.setattr(connection, "DATABASE_URL", None)
    monkeypatch.setattr(reset, "DB_NAME", str(db))
    monkeypatch.setattr(reset, "DATABASE_URL", None)
    return db


def _approved_report(tmp_path):
    report = reset.build_dry_run()
    path = tmp_path / "dry-run.json"
    reset.write_report(report, path)
    return report, path


def _execute(tmp_path, report_path, **kwargs):
    return reset.execute_reset(
        confirmation=reset.CONFIRMATION_TOKEN,
        dry_run_report=report_path,
        backup_dir=tmp_path / "backups",
        reason="Substituir carga financeira incompleta antes da integracao Sankhya",
        executor="Agente de teste",
        **kwargs,
    )


def test_dry_run_inventaria_sem_alterar_dados(reset_db, tmp_path):
    before = _all_rows(reset_db)
    report, path = _approved_report(tmp_path)
    after = _all_rows(reset_db)

    assert before == after
    assert report["executable"] is True
    assert report["inventory_before"]["totals"] == {
        "records": 7, "original_value": "1500.0", "paid_value": "500.0",
        "balance": "1000.0", "open_titles": 1, "closed_titles": 1,
        "reconciliations": 0, "bank_movements": 0,
        "operational_document_links": 3, "import_batches": 1,
        "associated_audit_records": 1,
    }
    assert report["delete_order"].index("movimentacoes_financeiras") < report["delete_order"].index("movimentacoes_financeiras_importacao_lotes")
    assert report["operational_links_to_detach"][0]["child_table"] == "documentos_operacionais"
    assert report["preservation_before"]["cadastros_financeiros"]["tables"]["plano_contas_mestre"]["records"] == 1
    assert report["preservation_before"]["auditoria_financeira_global"]["tables"]["movimentacoes_financeiras_auditoria"]["records"] == 1
    assert reset.load_verified_dry_run(path)["dry_run_hash"] == report["dry_run_hash"]
    assert reset.financial_reconstruction_status()["active"] is False


def test_execucao_real_backup_auditoria_preservacao_e_bloqueio_importacao(reset_db, tmp_path):
    report, path = _approved_report(tmp_path)
    result = _execute(tmp_path, path)
    rows = _all_rows(reset_db)

    assert result["result"] == "SUCCESS"
    assert result["inventory_after"]["totals"]["records"] == 0
    for table in report["target_tables"]:
        assert rows[table] == []
    assert rows["movimentacoes_financeiras_auditoria"] == [(50, 10, "CRIACAO_IMPORTACAO", "Carga", "2026-07-01")]
    assert rows["documentos_operacionais"] == [(1, "DOC-1", None)]
    assert rows["vendas_diarias"] == [(1, 1500.0)]
    assert rows["custos_mensais"] == [(1, 700.0)]
    assert len(rows[reset.AUDIT_TABLE]) == 1
    backup = Path(result["backup"]["file"])
    assert backup.is_file()
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == result["backup"]["sha256"]
    restored = _all_rows(backup)
    assert len(restored["movimentacoes_financeiras"]) == 2
    assert reset.financial_imports_blocked() is True
    estado = reset.financial_reconstruction_status()
    assert estado == {
        "active": True,
        "state": "FINANCEIRO_EM_RECONSTRUCAO",
        "message": reset.FINANCIAL_RECONSTRUCTION_MESSAGE,
        "audit_event_id": result["audit_event_id"],
        "activated_at": rows[reset.AUDIT_TABLE][0][2],
    }
    with pytest.raises(reset.ResetSafetyError, match="desabilitadas"):
        reset.require_financial_imports_enabled()
    with pytest.raises(reset.ResetSafetyError, match="desabilitadas"):
        importar_movimentacoes_financeiras_excel(
            BytesIO(b"conteudo-nao-deve-ser-lido"), usuario_id=1, usuario_nome="Admin"
        )
    assert result["cache_invalidation"].startswith("Nenhum cache persistente")
    assert result["orphans"] == []


def test_rollback_integral_em_falha_intermediaria(reset_db, tmp_path):
    before = _all_rows(reset_db)
    _, path = _approved_report(tmp_path)
    with pytest.raises(RuntimeError, match="Falha intermediaria"):
        _execute(tmp_path, path, fail_after_table="movimentacoes_financeiras_origens")
    assert _all_rows(reset_db) == before
    assert reset.financial_reconstruction_status()["active"] is False


def test_idempotencia_na_segunda_execucao(reset_db, tmp_path):
    _, first = _approved_report(tmp_path)
    _execute(tmp_path, first)
    second_report = reset.build_dry_run()
    second = tmp_path / "dry-run-second.json"
    reset.write_report(second_report, second)
    backup_count = len(list((tmp_path / "backups").glob("*.sqlite3")))

    result = _execute(tmp_path, second)

    assert result["result"] == "ALREADY_ZERO"
    assert len(_all_rows(reset_db)[reset.AUDIT_TABLE]) == 1
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == backup_count
    assert reset.financial_reconstruction_status()["active"] is True


def test_bloqueia_token_backup_e_estado_divergente(reset_db, tmp_path, monkeypatch):
    _, path = _approved_report(tmp_path)
    before = _all_rows(reset_db)
    with pytest.raises(reset.ResetSafetyError, match="Confirmacao invalida"):
        reset.execute_reset(
            confirmation="RESET_FINANCEIRO_FRIGODATTA", dry_run_report=path, backup_dir=tmp_path,
            reason="motivo", executor="teste",
        )
    assert reset.CONFIRMATION_TOKEN == "RESET_TOTAL_FINANCEIRO_FRIGODATTA"

    monkeypatch.setattr(reset, "create_full_backup", lambda _path: (_ for _ in ()).throw(reset.ResetSafetyError("backup indisponivel")))
    with pytest.raises(reset.ResetSafetyError, match="backup indisponivel"):
        _execute(tmp_path, path)
    assert _all_rows(reset_db) == before

    conn = _connect(reset_db)
    conn.execute("UPDATE movimentacoes_financeiras SET valor=1001 WHERE id=10")
    conn.commit()
    conn.close()
    with pytest.raises(reset.ResetSafetyError, match="divergiu"):
        _execute(tmp_path, path)


def test_bloqueia_relatorio_dry_run_ausente_ou_adulterado(reset_db, tmp_path):
    with pytest.raises(reset.ResetSafetyError, match="nao encontrado"):
        _execute(tmp_path, tmp_path / "inexistente.json")

    report, path = _approved_report(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["inventory_before"]["totals"]["records"] = 0
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(reset.ResetSafetyError, match="Hash interno"):
        _execute(tmp_path, path)
    assert report["inventory_before"]["totals"]["records"] == 7


def test_bloqueia_dry_run_de_outro_banco_ambiente_ou_commit(reset_db, tmp_path):
    report, path = _approved_report(tmp_path)
    for field, value in (
        ("database", {"backend": "sqlite", "file": "outro.db"}),
        ("environment", "outro-ambiente"),
        ("commit", "outro-commit"),
    ):
        changed = dict(report)
        changed[field] = value
        changed.pop("dry_run_hash")
        changed["dry_run_hash"] = reset._sha(changed)
        reset.write_report(changed, path)
        with pytest.raises(reset.ResetSafetyError, match=field):
            _execute(tmp_path, path)


def test_dry_run_aborta_tabela_financeira_desconhecida(reset_db):
    conn = _connect(reset_db)
    conn.execute("CREATE TABLE conciliacoes_bancarias_novas(id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    report = reset.build_dry_run()
    assert report["executable"] is False
    assert report["blockers"][0]["code"] == "UNKNOWN_FINANCIAL_TABLES"


def test_dry_run_aborta_quando_schema_financeiro_principal_nao_existe(tmp_path, monkeypatch):
    db = tmp_path / "sem-financeiro.db"
    sqlite3.connect(db).close()
    monkeypatch.setattr(connection, "DB_NAME", str(db))
    monkeypatch.setattr(reset, "DB_NAME", str(db))
    report = reset.build_dry_run()
    assert report["executable"] is False
    assert report["blockers"][0]["code"] == "CORE_FINANCIAL_TABLE_MISSING"


def test_dry_run_aborta_fk_operacional_obrigatoria(reset_db):
    conn = _connect(reset_db)
    conn.execute("CREATE TABLE documento_financeiro_obrigatorio(id INTEGER PRIMARY KEY, movimentacao_id INTEGER NOT NULL REFERENCES movimentacoes_financeiras(id))")
    conn.execute("INSERT INTO documento_financeiro_obrigatorio VALUES (1,10)")
    conn.commit()
    conn.close()
    report = reset.build_dry_run()
    codes = {item["code"] for item in report["blockers"]}
    assert "UNKNOWN_FINANCIAL_TABLES" in codes
    assert "NON_NULL_OPERATIONAL_FK" in codes


def test_smoke_telas_financeiras_vazias_em_aplicacao_real(tmp_path):
    db = tmp_path / "smoke.db"
    script = r'''
import json, os, sys
from pathlib import Path
os.environ["DB_NAME"] = sys.argv[1]
os.environ.pop("DATABASE_URL", None)
import app
from database import conectar
from modules.movimentacoes.reset_financeiro import build_dry_run, execute_reset, write_report, CONFIRMATION_TOKEN
conn=conectar(); cur=conn.cursor()
cur.execute("INSERT INTO usuarios(nome,email,senha_hash,perfil) VALUES (?,?,?,?)",("Admin","admin@teste","x","admin"))
cur.execute("INSERT INTO movimentacoes_financeiras(data_vencimento,tipo,categoria,descricao,valor,status) VALUES (?,?,?,?,?,?)",("2026-08-31","Entrada","Receita Bruta","Smoke",100,"Pendente"))
conn.commit(); conn.close()
client=app.app.test_client()
with client.session_transaction() as session:
    session["usuario_id"]=1; session["nome"]="Admin"; session["perfil"]="admin"
before=client.get("/movimentacoes/entradas").get_data(as_text=True)
base=Path(sys.argv[2]); report=build_dry_run(); report_path=base/"dry.json"; write_report(report,report_path)
result=execute_reset(confirmation=CONFIRMATION_TOKEN,dry_run_report=report_path,backup_dir=base/"backup",reason="smoke",executor="teste")
financial_urls=("/movimentacoes/entradas","/fluxo-caixa","/dre-gerencial","/movimentacoes/importar","/movimentacoes/liquidacao")
responses={url:client.get(url) for url in financial_urls}
exports={url:client.get(url).status_code for url in ("/movimentacoes/liquidacao/exportar","/dre-gerencial/exportar-excel")}
operational={url:client.get(url) for url in ("/inicio","/ordem-producao","/estoque-produtos")}
print(json.dumps({
    "result":result["result"],
    "statuses":{url:response.status_code for url,response in responses.items()},
    "banner_before":"FINANCEIRO EM RECONSTRUCAO" in before,
    "banners_after":{url:"FINANCEIRO EM RECONSTRUCAO" in response.get_data(as_text=True) for url,response in responses.items()},
    "exports":exports,
    "operational":{url:{"status":response.status_code,"banner":"FINANCEIRO EM RECONSTRUCAO" in response.get_data(as_text=True)} for url,response in operational.items()},
}))
'''
    completed = subprocess.run(
        [sys.executable, "-c", script, str(db), str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload == {
        "result": "SUCCESS",
        "statuses": {
            "/movimentacoes/entradas": 200, "/fluxo-caixa": 200,
            "/dre-gerencial": 200, "/movimentacoes/importar": 200,
            "/movimentacoes/liquidacao": 200,
        },
        "banner_before": False,
        "banners_after": {
            "/movimentacoes/entradas": True, "/fluxo-caixa": True,
            "/dre-gerencial": True, "/movimentacoes/importar": True,
            "/movimentacoes/liquidacao": True,
        },
        "exports": {
            "/movimentacoes/liquidacao/exportar": 200,
            "/dre-gerencial/exportar-excel": 200,
        },
        "operational": {
            "/inicio": {"status": 200, "banner": False},
            "/ordem-producao": {"status": 200, "banner": False},
            "/estoque-produtos": {"status": 200, "banner": False},
        },
    }


def test_estado_ativo_bloqueia_todas_as_escritas_financeiras(reset_db, tmp_path):
    _, path = _approved_report(tmp_path)
    _execute(tmp_path, path)

    operacoes = (
        ("criacao_manual", lambda: salvar_movimentacao_financeira({}, usuario_id=1, usuario_nome="Admin")),
        ("edicao", lambda: atualizar_movimentacao_financeira(10, {"status": "Pendente"})),
        ("baixa_realizacao", lambda: atualizar_movimentacao_financeira(10, {"status": "Realizado"})),
        ("reabertura", lambda: atualizar_movimentacao_financeira(10, {"status": "Pendente"})),
        ("cancelamento", lambda: excluir_movimentacao_financeira(10, "cancelar")),
        ("alteracao_origem", lambda: alterar_origem_principal_movimentacao(
            10, "IMPORTACAO_FINANCEIRA", "alterar", 1, "Admin"
        )),
        ("reclassificacao_em_lote", lambda: reclassificar_movimentacoes([10], 1, "reclassificar")),
        ("importacao_financeira", lambda: importar_movimentacoes_financeiras_excel(
            BytesIO(b"despesa"), usuario_id=1, usuario_nome="Admin"
        )),
        ("importacao_vendas", lambda: importar_movimentacoes_financeiras_excel(
            BytesIO(b"venda"), natureza_padrao="RECEITA",
            origem_importacao="IMPORTACAO VENDAS", usuario_id=1, usuario_nome="Admin",
        )),
        ("comando_sincronizacao", lambda: sincronizar_movimentacoes_plano_contas("sincronizar")),
        ("comando_hotfix", lambda: corrigir_natureza_aportes_fluxo_caixa("corrigir")),
    )
    for nome, operacao in operacoes:
        with pytest.raises(
            reset.ResetSafetyError,
            match="FINANCEIRO_EM_RECONSTRUCAO",
        ) as bloqueio:
            operacao()
        assert nome and "desabilitadas" in str(bloqueio.value)
