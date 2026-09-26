"""Migration PostgreSQL real de quantidade_aprovada (RC): schema, backfill, rollback e reaplicação.

Executar com TEST_DATABASE_URL apontando para banco DESCARTÁVEL: esta suíte destrói e recria o schema public.
"""
from pathlib import Path
import os

import psycopg2
import pytest

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database"
URL = os.getenv("TEST_DATABASE_URL")
if not URL and os.getenv("REQUIRE_REAL_POSTGRESQL") == "1":
    raise RuntimeError("PostgreSQL real é obrigatório para esta execução.")
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL ausente")

BASE = (DB / "20260919_requisicoes_compra.sql").read_text(encoding="utf-8")
MIGRATION = (DB / "20260925_rc_quantidade_aprovada.sql").read_text(encoding="utf-8")
ROLLBACK = (DB / "20260925_rc_quantidade_aprovada_rollback.sql").read_text(encoding="utf-8")


def _rc(cur, numero, status, aprovado_em):
    cur.execute("""INSERT INTO requisicoes_compra(numero,status,tipo_origem,origem_descricao_snapshot,origem_dados_snapshot,setor,solicitante_nome_snapshot,
        prioridade,chave_criacao,criado_em,aprovado_em,atualizado_em) VALUES(%s,%s,'ADMINISTRATIVO','x','{}','S','Sol','NORMAL',%s,now(),%s,now()) RETURNING id""",
                (numero, status, "k-" + numero, aprovado_em))
    return cur.fetchone()[0]


def _item(cur, rid, desc, qtd, custo=None, nu=None):
    cur.execute("""INSERT INTO requisicao_compra_itens(requisicao_compra_id,descricao_snapshot,unidade_snapshot,quantidade_solicitada,custo_estimado_unitario,nu,criado_em,atualizado_em)
        VALUES(%s,%s,'un',%s,%s,%s,now(),now())""", (rid, desc, qtd, custo, nu))


def _colunas(cur):
    cur.execute("SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE table_name='requisicao_compra_itens' ORDER BY ordinal_position")
    return cur.fetchall()


def _dados(cur):
    cur.execute("SELECT i.id,i.requisicao_compra_id,i.descricao_snapshot,i.quantidade_solicitada,i.custo_estimado_unitario,i.nu,i.status FROM requisicao_compra_itens i ORDER BY i.id")
    return cur.fetchall()


def _aprovadas(cur):
    cur.execute("SELECT i.descricao_snapshot,i.quantidade_solicitada,i.quantidade_aprovada FROM requisicao_compra_itens i ORDER BY i.id")
    return cur.fetchall()


@pytest.fixture()
def cur():
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    c = conn.cursor()
    c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    c.execute(BASE)
    yield c
    conn.close()


def test_migration_backfill_rollback_e_reaplicacao_em_postgresql_real(cur):
    aprov = _rc(cur, "RC-A", "APROVADA", "2026-09-10 10:00:00")
    cancel = _rc(cur, "RC-C", "CANCELADA", "2026-09-11 10:00:00")   # aprovada e depois cancelada
    aberta = _rc(cur, "RC-B", "ABERTA", None)
    rasc = _rc(cur, "RC-R", "RASCUNHO", None)
    rejeit = _rc(cur, "RC-J", "REJEITADA", None)
    _item(cur, aprov, "aprov-1", 5, 2.5, "123")
    _item(cur, aprov, "aprov-2", 3.5)
    _item(cur, cancel, "cancel-1", 7, 1)
    _item(cur, aberta, "aberta-1", 9, 4)
    _item(cur, rasc, "rasc-1", 2)
    _item(cur, rejeit, "rejeit-1", 6)

    colunas_antes, dados_antes = _colunas(cur), _dados(cur)
    assert "quantidade_aprovada" not in [c[0] for c in colunas_antes]

    cur.execute(MIGRATION)
    colunas_depois = _colunas(cur)
    assert [c[0] for c in colunas_depois if c not in colunas_antes] == ["quantidade_aprovada"]
    nova = [c for c in colunas_depois if c[0] == "quantidade_aprovada"][0]
    assert nova[1] == "real" and nova[2] == "YES"
    assert _dados(cur) == dados_antes  # nenhuma coluna pré-existente foi alterada
    assert _aprovadas(cur) == [("aprov-1", 5.0, 5.0), ("aprov-2", 3.5, 3.5), ("cancel-1", 7.0, 7.0),
                               ("aberta-1", 9.0, None), ("rasc-1", 2.0, None), ("rejeit-1", 6.0, None)]

    cur.execute(ROLLBACK)
    assert _colunas(cur) == colunas_antes and _dados(cur) == dados_antes

    cur.execute(MIGRATION)  # repetibilidade: reaplicar após o rollback
    assert _aprovadas(cur) == [("aprov-1", 5.0, 5.0), ("aprov-2", 3.5, 3.5), ("cancel-1", 7.0, 7.0),
                               ("aberta-1", 9.0, None), ("rasc-1", 2.0, None), ("rejeit-1", 6.0, None)]
    cur.execute(MIGRATION)  # idempotente: aplicar de novo não falha nem altera dados
    assert _dados(cur) == dados_antes and _colunas(cur) == colunas_depois


def test_backfill_nao_sobrescreve_quantidade_aprovada_ja_existente(cur):
    cur.execute(MIGRATION)
    aprov = _rc(cur, "RC-A", "APROVADA_COM_AJUSTES", "2026-09-10 10:00:00")
    _item(cur, aprov, "ajustado", 10)
    cur.execute("UPDATE requisicao_compra_itens SET quantidade_aprovada=4 WHERE descricao_snapshot='ajustado'")
    cur.execute(MIGRATION)
    assert _aprovadas(cur) == [("ajustado", 10.0, 4.0)]
