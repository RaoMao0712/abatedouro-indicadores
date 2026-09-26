from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

import psycopg2
import pytest

import database.connection as db_connection
from modules.engenharia_produtos import repositories as repo


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente")
ROOT = Path(__file__).resolve().parents[1]


def _executar(nome):
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    conn.cursor().execute((ROOT / "database" / nome).read_text(encoding="utf-8"))
    conn.close()


@pytest.fixture(autouse=True)
def banco_postgresql(monkeypatch):
    if not TEST_DATABASE_URL:
        yield
        return
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS processos_produtivos_codigo_seq")
    cur.execute("DROP TABLE IF EXISTS processos_produtivos")
    cur.execute("""CREATE TABLE processos_produtivos(
        id SERIAL PRIMARY KEY, codigo TEXT NOT NULL UNIQUE, nome TEXT NOT NULL,
        descricao TEXT, setor TEXT, status TEXT NOT NULL DEFAULT 'Ativo',
        observacoes TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
    cur.execute("INSERT INTO processos_produtivos(codigo,nome) VALUES('LEGADO-X','Legado'),('PROC-0009','Existente')")
    conn.close()
    monkeypatch.setattr(repo, "DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(db_connection, "DATABASE_URL", TEST_DATABASE_URL)
    yield
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = True
    conn.cursor().execute("DROP TABLE IF EXISTS processos_produtivos_codigo_seq; DROP TABLE IF EXISTS processos_produtivos")
    conn.close()


def test_postgresql_apply_reapply_rollback_reapply_preserva_legado():
    _executar("20260926_processos_codigo_automatico.sql")
    _executar("20260926_processos_codigo_automatico.sql")
    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT ultimo_valor FROM processos_produtivos_codigo_seq WHERE chave='PROCESSO'")
    assert cur.fetchone()[0] == 9
    conn.close()
    _executar("20260926_processos_codigo_automatico_rollback.sql")
    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT codigo FROM processos_produtivos ORDER BY id")
    assert cur.fetchall() == [("LEGADO-X",), ("PROC-0009",)]
    conn.close()
    _executar("20260926_processos_codigo_automatico.sql")


def test_concorrencia_postgresql_usa_bloqueio_transacional():
    _executar("20260926_processos_codigo_automatico.sql")

    def criar(indice):
        return repo.inserir_processo((f"Processo {indice}", "", "", "Ativo", ""))[1]

    with ThreadPoolExecutor(max_workers=8) as executor:
        codigos = list(executor.map(criar, range(20)))
    assert len(codigos) == len(set(codigos)) == 20
    assert set(codigos) == {f"PROC-{indice:04d}" for indice in range(10, 30)}
    conn = psycopg2.connect(TEST_DATABASE_URL)
    cur = conn.cursor()
    with pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("INSERT INTO processos_produtivos(codigo,nome) VALUES('PROC-0010','Duplicado')")
    conn.rollback()
    conn.close()
