"""Validação PostgreSQL real da reconciliação em sombra da Fase 4."""

import os
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import psycopg2.extras
import pytest


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from database import conectar, transaction  # noqa: E402
from modules.engenharia_produtos import reconciliacao, representacao_legada, repositories, snapshot_op  # noqa: E402


def _direta():
    return psycopg2.connect(TEST_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


@pytest.fixture(scope="module", autouse=True)
def banco_descartavel():
    if not TEST_DATABASE_URL:
        yield
        return
    conn = _direta(); conn.autocommit = True
    conn.cursor().execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    conn.close()
    repositories.criar_estrutura()
    with transaction() as banco:
        cur = banco.cursor()
        cur.execute("CREATE TABLE ordens_producao(id SERIAL PRIMARY KEY,sku TEXT,status TEXT)")
        cur.execute("""INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES
            ('LEG-1','Galinha Cortada','PRODUTO_ACABADO','Kg','Sim'),
            ('LEG-2','Galinha Inteira','PRODUTO_ACABADO','Un','Sim')""")
    representacao_legada.aplicar("PostgreSQL Fase 4")
    reconciliacao.criar_estrutura()
    yield
    conn = _direta(); conn.autocommit = True
    conn.cursor().execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    conn.close()


def test_reconciliacao_paridade_e_idempotencia_concorrente():
    with transaction() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO ordens_producao(sku,status) VALUES('Galinha Inteira','Aberta') RETURNING id")
        op_id = cur.fetchone()["id"]
        snapshot_op.gravar_snapshot(cur, op_id, "Galinha Inteira", 1, "Teste PG")

    def executar():
        with transaction() as conn:
            return reconciliacao.reconciliar_op(conn.cursor(), op_id)["id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _item: executar(), range(2)))
    assert ids[0] == ids[1]
    conn = conectar(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) n,MIN(resultado_geral) resultado FROM op_config_reconciliacoes WHERE op_id=%s", (op_id,))
    row = cur.fetchone()
    assert row["n"] == 1 and row["resultado"] == "PARIDADE"
    conn.close()


def test_rollback_transacional_remove_op_snapshot_e_reconciliacao():
    with pytest.raises(RuntimeError, match="rollback controlado"):
        with transaction() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO ordens_producao(sku,status) VALUES('Galinha Cortada','Aberta') RETURNING id")
            op_id = cur.fetchone()["id"]
            snapshot_op.gravar_snapshot(cur, op_id, "Galinha Cortada", 1, "Teste PG")
            reconciliacao.reconciliar_op(cur, op_id)
            raise RuntimeError("rollback controlado")
    conn = conectar(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) n FROM ordens_producao WHERE sku='Galinha Cortada'")
    assert cur.fetchone()["n"] == 0
    cur.execute("SELECT COUNT(*) n FROM op_config_reconciliacoes")
    assert cur.fetchone()["n"] == 1
    conn.close()
