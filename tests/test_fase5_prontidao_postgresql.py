import os
from pathlib import Path

import psycopg2
import pytest


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente")
ROOT = Path(__file__).resolve().parents[1]


def _conn():
    return psycopg2.connect(TEST_DATABASE_URL)


def _executar(nome):
    conn = _conn(); conn.autocommit = True
    conn.cursor().execute((ROOT / "database" / nome).read_text(encoding="utf-8"))
    conn.close()


@pytest.fixture(autouse=True)
def estrutura_base():
    if not TEST_DATABASE_URL:
        yield
        return
    conn = _conn(); conn.autocommit = True; cur = conn.cursor()
    cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    cur.execute("CREATE TABLE op_config_reconciliacoes(id SERIAL PRIMARY KEY, dado TEXT)")
    cur.execute("CREATE TABLE op_config_reconciliacao_execucoes(id SERIAL PRIMARY KEY, dado TEXT)")
    cur.execute("INSERT INTO op_config_reconciliacoes(dado) VALUES('preservar')")
    cur.execute("INSERT INTO op_config_reconciliacao_execucoes(dado) VALUES('preservar')")
    conn.close()
    yield
    conn = _conn(); conn.autocommit = True
    conn.cursor().execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    conn.close()


def test_apply_reapply_constraints_e_indices():
    _executar("20260926_fase5_prontidao_sku.sql")
    _executar("20260926_fase5_prontidao_sku.sql")
    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT table_name FROM information_schema.tables
        WHERE table_schema='public' AND table_name LIKE 'sku_prontidao_%' ORDER BY table_name""")
    assert [item[0] for item in cur.fetchall()] == [
        "sku_prontidao_avaliacoes", "sku_prontidao_parametros"
    ]
    cur.execute("""INSERT INTO sku_prontidao_parametros(
        sku,dimensoes_criticas_json) VALUES('Galinha Cortada','[]') RETURNING id""")
    parametro_id = cur.fetchone()[0]
    cur.execute("""INSERT INTO sku_prontidao_avaliacoes(
        sku,parametro_id,estado,parametros_json,metricas_json,hash_avaliacao)
        VALUES('Galinha Cortada',%s,'EM_OBSERVACAO','{}','{}','hash')""", (parametro_id,))
    with pytest.raises(psycopg2.errors.UniqueViolation):
        cur.execute("""INSERT INTO sku_prontidao_avaliacoes(
            sku,parametro_id,estado,parametros_json,metricas_json,hash_avaliacao)
            VALUES('Galinha Cortada',%s,'EM_OBSERVACAO','{}','{}','hash')""", (parametro_id,))
    conn.rollback(); conn.close()


def test_rollback_e_reapply_preservam_reconciliacao_legada():
    _executar("20260926_fase5_prontidao_sku.sql")
    _executar("20260926_fase5_prontidao_sku_rollback.sql")
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT dado FROM op_config_reconciliacoes")
    assert cur.fetchone()[0] == "preservar"
    cur.execute("SELECT dado FROM op_config_reconciliacao_execucoes")
    assert cur.fetchone()[0] == "preservar"
    cur.execute("SELECT to_regclass('public.sku_prontidao_parametros')")
    assert cur.fetchone()[0] is None
    conn.close()
    _executar("20260926_fase5_prontidao_sku.sql")
    conn = _conn(); cur = conn.cursor()
    cur.execute("SELECT to_regclass('public.sku_prontidao_avaliacoes')")
    assert cur.fetchone()[0] == "sku_prontidao_avaliacoes"
    conn.close()
