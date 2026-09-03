import sqlite3
from pathlib import Path

import pytest
from flask import Flask

from modules.almoxarifado import routes, services


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PG = ROOT / "database" / "20260903_correcao_entrada_estoque.sql"
MIGRATION_SQLITE = ROOT / "database" / "20260903_correcao_entrada_estoque_sqlite.sql"


def _schema_legado(conn):
    conn.executescript("""
    CREATE TABLE almoxarifado_insumos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, descricao TEXT NOT NULL UNIQUE,
        categoria TEXT NOT NULL, unidade TEXT NOT NULL, ativo TEXT DEFAULT 'Sim',
        observacoes TEXT, criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE almoxarifado_lotes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, insumo_id INTEGER NOT NULL,
        data_entrada TEXT NOT NULL, lote TEXT, fornecedor TEXT, numero_nf TEXT,
        quantidade_inicial REAL NOT NULL, quantidade_atual REAL NOT NULL,
        valor_unitario REAL NOT NULL, valor_total REAL NOT NULL,
        status TEXT DEFAULT 'Aberto', criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE almoxarifado_movimentacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, data_movimentacao TEXT NOT NULL,
        tipo TEXT NOT NULL, insumo_id INTEGER NOT NULL, lote_id INTEGER,
        quantidade REAL NOT NULL, valor_unitario REAL DEFAULT 0, valor_total REAL DEFAULT 0,
        fornecedor TEXT, numero_nf TEXT, lote TEXT, origem TEXT DEFAULT 'Manual',
        op_id INTEGER, observacoes TEXT, criado_em TEXT DEFAULT CURRENT_TIMESTAMP
    );
    INSERT INTO almoxarifado_insumos(descricao,categoria,unidade) VALUES('Bandeja','Embalagem','Un');
    INSERT INTO almoxarifado_lotes(insumo_id,data_entrada,quantidade_inicial,quantidade_atual,valor_unitario,valor_total)
        VALUES(1,'2026-09-03',1000,1000,15,15000);
    """)


def test_migration_postgresql_e_transacional_aditiva_idempotente_e_sem_dml_operacional():
    sql = MIGRATION_PG.read_text(encoding="utf-8")
    normalizado = " ".join(sql.upper().split())
    assert normalizado.startswith("BEGIN;") and normalizado.endswith("COMMIT;")
    assert "ADD COLUMN IF NOT EXISTS" in normalizado
    assert "CREATE TABLE IF NOT EXISTS" in normalizado
    assert "CREATE INDEX IF NOT EXISTS" in normalizado
    for proibido in ("DROP TABLE", "DROP COLUMN", "TRUNCATE", "DELETE FROM", "UPDATE ALMOXARIFADO"):
        assert proibido not in normalizado
    assert "DATABASE_URL" not in sql and "postgresql://" not in sql.lower()


def test_migration_sqlite_preserva_dado_legado_e_runtime_oficial_e_reaplicavel(tmp_path, monkeypatch):
    banco = tmp_path / "migration.sqlite"
    conn = sqlite3.connect(banco)
    _schema_legado(conn)
    conn.executescript(MIGRATION_SQLITE.read_text(encoding="utf-8"))
    assert tuple(conn.execute("SELECT quantidade_atual,valor_unitario,valor_total FROM almoxarifado_lotes").fetchone()) == (1000, 15, 15000)
    conn.close()

    def conectar():
        conexao = sqlite3.connect(banco)
        conexao.row_factory = sqlite3.Row
        return conexao

    monkeypatch.setattr(services, "DATABASE_URL", None)
    monkeypatch.setattr(services, "conectar", conectar)
    services.criar_tabelas_estoque_almoxarifado()
    services.criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    assert conn.execute("SELECT COUNT(*) FROM almoxarifado_correcoes_entrada").fetchone()[0] == 0
    assert tuple(conn.execute("SELECT quantidade_atual,valor_unitario,valor_total FROM almoxarifado_lotes").fetchone()) == (1000, 15, 15000)
    conn.close()


def test_url_direta_autoriza_admin_gerencia_e_bloqueia_operador(tmp_path, monkeypatch):
    banco = tmp_path / "autorizacao.sqlite"

    def conectar():
        conexao = sqlite3.connect(banco)
        conexao.row_factory = sqlite3.Row
        return conexao

    monkeypatch.setattr(services, "DATABASE_URL", None)
    monkeypatch.setattr(services, "conectar", conectar)
    services.criar_tabelas_estoque_almoxarifado()
    conn = conectar()
    conn.execute("INSERT INTO almoxarifado_insumos(descricao,categoria,unidade) VALUES('Bandeja','Embalagem','Un')")
    conn.commit(); conn.close()
    services.salvar_entrada_estoque_almoxarifado({
        "insumo_id": "1", "data_entrada": "2026-09-03", "quantidade": "1000",
        "valor_unitario": "15", "fornecedor": "Teste", "numero_nf": "NF-1",
        "lote": "L-1", "observacoes": "",
    }, usuario="Operadora")

    app = Flask("hotfix-auth", template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.secret_key = "teste"
    app.jinja_env.filters["br_numero"] = lambda valor, casas=2: f"{float(valor):.{int(casas)}f}"
    app.jinja_env.filters["br_moeda"] = lambda valor: f"R$ {float(valor):.2f}"
    app.add_url_rule("/", "login", lambda: "login")
    app.add_url_rule("/inicio", "inicio", lambda: "inicio")
    app.add_url_rule("/sair", "sair", lambda: "sair")
    routes.register_almoxarifado_routes(app)

    for perfil in ("admin", "gerencia"):
        cliente = app.test_client()
        with cliente.session_transaction() as sessao:
            sessao.update({"usuario_id": 1, "nome": perfil, "perfil": perfil})
        assert cliente.get("/almoxarifado/entradas/1/corrigir").status_code == 200

    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update({"usuario_id": 2, "nome": "PCP", "perfil": "pcp"})
    resposta = cliente.get("/almoxarifado/entradas/1/corrigir")
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/inicio")
