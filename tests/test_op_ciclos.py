import os
from pathlib import Path
import sqlite3
from uuid import uuid4

import pytest

from modules.producao import ciclos_op, planejamento_reversao_op, reversao_pi_op


MIGRATIONS = Path(__file__).resolve().parents[1] / "database"


@pytest.fixture(params=["sqlite", "postgres"])
def banco(request, monkeypatch):
    pg = request.param == "postgres"
    if pg:
        dsn = os.environ.get("PG_CICLO_TEST_DSN")
        if not dsn:
            pytest.skip("PostgreSQL descartável não configurado")
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
        schema = "ciclos_teste_" + uuid4().hex
        conn.cursor().execute(f"CREATE SCHEMA {schema}; SET LOCAL search_path TO {schema}; CREATE TABLE ordens_producao (id INTEGER PRIMARY KEY,status TEXT)")
        cursor = conn.cursor()
        sufixo = ""
    else:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("CREATE TABLE ordens_producao (id INTEGER PRIMARY KEY,status TEXT)")
        sufixo = "_sqlite"
    monkeypatch.setattr(ciclos_op, "DATABASE_URL", dsn if pg else None)
    monkeypatch.setattr(ciclos_op, "q", lambda sql: sql.replace("?", "%s") if pg else sql)
    monkeypatch.setattr(reversao_pi_op, "DATABASE_URL", dsn if pg else None)
    monkeypatch.setattr(reversao_pi_op, "q", ciclos_op.q)
    monkeypatch.setattr(planejamento_reversao_op, "q", ciclos_op.q)

    def aplicar(rollback=False):
        nome = "20261127_op_ciclos" + sufixo + ("_rollback" if rollback else "") + ".sql"
        script = (MIGRATIONS / nome).read_text(encoding="utf-8-sig")
        if pg:
            cursor.execute(script)
        else:
            cursor.executescript(script)

    try:
        yield cursor, aplicar
    finally:
        conn.close()


def test_backfill_preserva_op_e_sincroniza_fluxos_existentes(banco):
    cursor, aplicar = banco
    cursor.execute("INSERT INTO ordens_producao VALUES (1,'Encerrada'),(2,'Aberta'),(3,'Estornada')")
    aplicar()
    assert [ciclos_op.ciclo_corrente_cursor(cursor, op)["status"] for op in (1, 2, 3)] == [
        "ENCERRADO", "ATIVO", "ESTORNADO",
    ]
    aplicar()
    cursor.execute("INSERT INTO ordens_producao VALUES (4,'Aberta')")
    cursor.execute("UPDATE ordens_producao SET status='Encerrada' WHERE id=4")
    ciclo = ciclos_op.ciclo_corrente_cursor(cursor, 4)
    assert ciclo["numero_ciclo"] == 1 and ciclo["encerrado_em"]
    cursor.execute("UPDATE ordens_producao SET status='Aberta' WHERE id=4")
    assert ciclos_op.ciclo_corrente_cursor(cursor, 4)["status"] == "ATIVO"
    cursor.execute("DELETE FROM ordens_producao WHERE id=4")
    cursor.execute("SELECT COUNT(*) total FROM op_ciclos WHERE op_id=4")
    assert cursor.fetchone()["total"] == 0


def test_troca_preserva_ciclo_original_e_rejeita_versao_antiga(banco):
    cursor, aplicar = banco
    aplicar()
    cursor.execute("INSERT INTO ordens_producao VALUES (1,'Encerrada')")
    original = ciclos_op.ciclo_corrente_cursor(cursor, 1)
    dados = dict(ciclo_id=original["id"], operacao_id="reset-1", usuario="Admin",
                 motivo="Ajuste validado", agora="2026-11-27 10:30:00")
    novo = ciclos_op.substituir_ciclo_cursor(cursor, 1, **dados)
    assert novo["numero_ciclo"] == 2 and novo["id"] != original["id"]
    cursor.execute("SELECT status,operacao_reset_id FROM op_ciclos WHERE numero_ciclo=1")
    assert dict(cursor.fetchone()) == {
        "status": "INVALIDADO_REPROCESSAMENTO", "operacao_reset_id": "reset-1",
    }
    with pytest.raises(ValueError, match="ciclo corrente mudou"):
        ciclos_op.substituir_ciclo_cursor(cursor, 1, **dados)
    with pytest.raises(Exception, match="Rollback recusado|CHECK constraint"):
        aplicar(rollback=True)


def test_rollback_antes_de_uso_preserva_ordem(banco):
    cursor, aplicar = banco
    cursor.execute("INSERT INTO ordens_producao VALUES (1,'Aberta')")
    aplicar()
    aplicar(rollback=True)
    cursor.execute("SELECT status FROM ordens_producao WHERE id=1")
    assert cursor.fetchone()["status"] == "Aberta"


def test_previa_vincula_ciclo_e_rejeita_consequencias_alteradas(banco, monkeypatch):
    cursor, aplicar = banco
    aplicar()
    cursor.execute("INSERT INTO ordens_producao VALUES (1,'Aberta')")
    ciclo = ciclos_op.ciclo_corrente_cursor(cursor, 1)
    snapshot = {"ponto_retorno": "INICIO_DO_CICLO", "movimentos": [1, 2]}
    serializado, hash_plano = planejamento_reversao_op._serializar_snapshot(snapshot)
    cursor.execute(ciclos_op.q("""INSERT INTO op_planos_reprocessamento
        (id,ciclo_id,versao_operacional,hash_consequencias,snapshot_json,criado_por)
        VALUES ('plano-1',?,0,?,?,'Teste')"""), (ciclo["id"], hash_plano, serializado))
    monkeypatch.setattr(planejamento_reversao_op, "_snapshot_cursor", lambda *args: snapshot)
    assert planejamento_reversao_op.revalidar_previa_cursor(cursor, 1, "plano-1") == snapshot
    snapshot["movimentos"].append(3)
    with pytest.raises(ValueError, match="mudaram desde a análise"):
        planejamento_reversao_op.revalidar_previa_cursor(cursor, 1, "plano-1")


def test_op_93_compensa_somente_pi_residual_e_preserva_origens(banco):
    cursor, aplicar = banco
    aplicar()
    cursor.execute("INSERT INTO ordens_producao VALUES (93,'Aberta')")
    ciclo = ciclos_op.ciclo_corrente_cursor(cursor, 93)
    identidade = "SERIAL PRIMARY KEY" if reversao_pi_op.DATABASE_URL else "INTEGER PRIMARY KEY"
    cursor.execute(f"""CREATE TABLE estoque_produto_intermediario (
        id {identidade}, op_id INTEGER, tipo TEXT, sku TEXT, quantidade_bandejas INTEGER,
        caixa_id INTEGER, movimento_origem_id INTEGER, data_movimentacao TEXT,
        origem TEXT, observacoes TEXT, idempotency_key TEXT UNIQUE
    )""")
    inserir = reversao_pi_op.q("""INSERT INTO estoque_produto_intermediario
        (op_id,tipo,sku,quantidade_bandejas,caixa_id,movimento_origem_id)
        VALUES (93,?,'Galinha Cortada',?,?,?) RETURNING id""")
    cursor.execute(inserir, ("ENTRADA_EMBALAGEM_PRIMARIA", 1468, None, None))
    entrada = cursor.fetchone()["id"]
    ativos = set()
    for indice in range(279):
        quantidade = 8 if indice == 165 else 10 if indice == 278 else 12
        cursor.execute(inserir, ("SAIDA_EMBALAGEM_SECUNDARIA", quantidade, indice + 1, None))
        origem = cursor.fetchone()["id"]
        if indice < 166:
            cursor.execute(inserir, ("ENTRADA_ESTORNO_CAIXA", quantidade, indice + 1, origem))
            cursor.fetchone()
        else:
            ativos.add(origem)
    plano = reversao_pi_op.planejar_compensacoes_pi_cursor(cursor, 93)
    assert {item["origem_id"] for item in plano} == ativos | {entrada}
    assert sum(int(item["quantidade"]) for item in plano if item["tipo"].startswith("ENTRADA")) == 1354
    assert plano[0]["quantidade"] == "1468"
    cursor.execute("SAVEPOINT antes_compensacoes")
    reversao_pi_op.compensar_pi_cursor(cursor, 93, plano=plano, operacao_id="reset-93", agora="2026-11-27")
    cursor.execute("SELECT COUNT(*) AS total FROM estoque_produto_intermediario")
    assert cursor.fetchone()["total"] == 446 + 114
    with pytest.raises(ValueError, match="mudaram"):
        reversao_pi_op.compensar_pi_cursor(cursor, 93, plano=plano, operacao_id="reset-93", agora="2026-11-27")
    novo = ciclos_op.substituir_ciclo_cursor(
        cursor, 93, ciclo_id=ciclo["id"], operacao_id="reset-93", usuario="Admin",
        motivo="PI incorreto", agora="2026-11-27 11:00:00",
    )
    assert novo["numero_ciclo"] == 2
    cursor.execute(inserir, ("ENTRADA_EMBALAGEM_PRIMARIA", 1456, None, None))
    entrada_nova = cursor.fetchone()["id"]
    assert [item["origem_id"] for item in reversao_pi_op.planejar_compensacoes_pi_cursor(cursor, 93)] == [entrada_nova]
    cursor.execute("ROLLBACK TO SAVEPOINT antes_compensacoes")
    assert reversao_pi_op.planejar_compensacoes_pi_cursor(cursor, 93) == plano
    assert ciclos_op.ciclo_corrente_cursor(cursor, 93)["id"] == ciclo["id"]
