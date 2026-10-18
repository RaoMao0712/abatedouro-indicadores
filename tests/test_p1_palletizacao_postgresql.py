"""P1 palletizacao: integridade e concorrencia em PostgreSQL real descartavel."""

from contextlib import contextmanager
from pathlib import Path
import os
import threading

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REQUIRE_REAL_POSTGRESQL = os.getenv("REQUIRE_REAL_POSTGRESQL") == "1"
if not TEST_DATABASE_URL and REQUIRE_REAL_POSTGRESQL:
    raise RuntimeError("PostgreSQL real e obrigatorio para esta execucao.")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente")

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    from modules.expedicao import palletizacao  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
UPGRADE = (ROOT / "database" / "20261018_p1_palletizacao.sql").read_text(encoding="utf-8")
DOWNGRADE = (ROOT / "database" / "20261018_p1_palletizacao_rollback.sql").read_text(encoding="utf-8")

BASE_DDL = """
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
CREATE TABLE locais_estoque(
 id SERIAL PRIMARY KEY,nome TEXT UNIQUE NOT NULL,tipo TEXT,ativo TEXT DEFAULT 'Sim'
);
CREATE TABLE expedicoes(id SERIAL PRIMARY KEY,numero_romaneio TEXT);
CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,sku TEXT);
CREATE TABLE pa_caixas(
 id SERIAL PRIMARY KEY,codigo_caixa TEXT UNIQUE NOT NULL,sku TEXT NOT NULL,
 quantidade_bandejas NUMERIC DEFAULT 0,peso_liquido NUMERIC DEFAULT 0,
 quantidade_pacotes INTEGER DEFAULT 0,quantidade_galinhas INTEGER DEFAULT 0,
 status TEXT DEFAULT 'Em estoque',disponibilidade TEXT DEFAULT 'DISPONIVEL',
 estoque_operacional INTEGER DEFAULT 1,local_estoque_id INTEGER
);
CREATE TABLE pa_caixa_composicao(
 id SERIAL PRIMARY KEY,caixa_id INTEGER NOT NULL REFERENCES pa_caixas(id),
 op_id INTEGER NOT NULL REFERENCES ordens_producao(id),quantidade_bandejas NUMERIC DEFAULT 0
);
INSERT INTO locais_estoque(nome,tipo) VALUES('Abatedouro','interno'),('Camara Fria LSM','interno');
INSERT INTO ordens_producao VALUES(121,'Galinha Inteira'),(122,'Galinha Cortada');
INSERT INTO pa_caixas(
 codigo_caixa,sku,quantidade_bandejas,peso_liquido,quantidade_pacotes,
 quantidade_galinhas,local_estoque_id
) VALUES
 ('CX-1','Galinha Inteira',0,100,962,1924,1),
 ('CX-2','Galinha Cortada',12,22,0,0,1),
 ('CX-3','Galinha Cortada',8,14,0,0,1);
INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas)
VALUES(1,121,0),(2,122,12),(3,122,8);
"""


def conectar():
    return psycopg2.connect(TEST_DATABASE_URL, cursor_factory=RealDictCursor)


@pytest.fixture(scope="module", autouse=True)
def schema_postgresql():
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute(BASE_DDL)
            cursor.execute(UPGRADE)
            cursor.execute(DOWNGRADE)
            cursor.execute(UPGRADE)
            cursor.execute("""SELECT to_regclass('public.pallets') AS pallets,
                                      to_regclass('public.pallet_caixa_eventos') AS eventos""")
            estado = cursor.fetchone()
            assert estado["pallets"] == "pallets"
            assert estado["eventos"] == "pallet_caixa_eventos"
    yield


@pytest.fixture(autouse=True)
def estado_limpo(monkeypatch):
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE pallet_caixas_atuais, pallet_caixa_eventos, pallets RESTART IDENTITY")

    @contextmanager
    def transacao_real():
        conn = conectar()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout='8s'")
                cursor.execute("SET LOCAL statement_timeout='15s'")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(palletizacao, "transaction", transacao_real)
    monkeypatch.setattr(palletizacao, "conectar", conectar)


def criar(chave, usuario="Teste"):
    return palletizacao.criar_pallet(
        usuario=usuario, idempotency_key=chave, localizacao_atual_id=1,
        posicao_atual="A-01",
    )


def contagem(tabela, where="TRUE", args=()):
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) AS total FROM {tabela} WHERE {where}", args)
            return int(cursor.fetchone()["total"])


def test_a_b_c_criar_codigo_unico_consultar_e_retry_idempotente():
    primeiro = criar("PALLET-A")
    retry = criar("PALLET-A")
    segundo = criar("PALLET-B")
    assert primeiro["id"] == retry["id"]
    assert primeiro["codigo"].startswith("PALT-")
    assert primeiro["codigo"] != segundo["codigo"]
    assert palletizacao.consultar_pallet(primeiro["id"])["codigo"] == primeiro["codigo"]
    assert contagem("pallet_caixa_eventos", "tipo_evento='PALLET_CRIADO'") == 2
    with conectar() as conn, conn.cursor() as cursor:
        with pytest.raises(psycopg2.Error):
            cursor.execute("UPDATE pallets SET codigo='PALT-999999' WHERE id=%s", (primeiro["id"],))


def test_d_f_l_m_n_o_adicionar_remover_preserva_op_estoque_evento_e_totais():
    pallet = criar("PALLET-D")
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT status,disponibilidade,estoque_operacional FROM pa_caixas WHERE id=1")
        antes = dict(cursor.fetchone())
    adicionado = palletizacao.adicionar_caixa(
        pallet["id"], 1, usuario="Teste", idempotency_key="ADD-D",
    )
    assert adicionado["totais"] == {
        "caixas": 1, "bandejas": 0.0, "peso_liquido": 100.0,
        "pacotes": 962, "aves": 1924,
    }
    assert adicionado["composicao_op"][0]["op_id"] == 121
    palletizacao.remover_caixa(
        pallet["id"], 1, usuario="Teste", idempotency_key="REM-D",
        justificativa="teste",
    )
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT status,disponibilidade,estoque_operacional FROM pa_caixas WHERE id=1")
        depois = dict(cursor.fetchone())
        cursor.execute("SELECT tipo_evento FROM pallet_caixa_eventos ORDER BY id")
        eventos = [item["tipo_evento"] for item in cursor.fetchall()]
    assert antes == depois
    assert eventos == ["PALLET_CRIADO", "CAIXA_ADICIONADA", "CAIXA_REMOVIDA"]
    assert contagem("pallet_caixas_atuais") == 0


def test_e_concorrencia_duas_sessoes_mesma_caixa_apenas_uma_vence():
    p1, p2 = criar("PALLET-E1"), criar("PALLET-E2")
    barreira = threading.Barrier(2)
    resultados, erros = [], []

    def alvo(pallet_id, chave):
        try:
            barreira.wait(timeout=5)
            palletizacao.adicionar_caixa(
                pallet_id, 2, usuario="Concorrencia", idempotency_key=chave,
            )
            resultados.append(pallet_id)
        except Exception as erro:
            erros.append(erro)

    threads = [
        threading.Thread(target=alvo, args=(p1["id"], "ADD-E1")),
        threading.Thread(target=alvo, args=(p2["id"], "ADD-E2")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert len(resultados) == 1
    assert len(erros) == 1
    assert contagem("pallet_caixas_atuais", "caixa_id=2") == 1
    assert contagem("pallet_caixa_eventos", "tipo_evento='CAIXA_ADICIONADA' AND caixa_id=2") == 1


def test_g_h_transferencia_atomica_e_rastreavel():
    origem, destino = criar("PALLET-G1"), criar("PALLET-G2")
    palletizacao.adicionar_caixa(origem["id"], 2, usuario="Teste", idempotency_key="ADD-G")
    resultado = palletizacao.transferir_caixa(
        origem["id"], destino["id"], 2, usuario="Teste", idempotency_key="TRANS-G",
    )
    assert resultado["totais"]["caixas"] == 1
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pallet_id,versao FROM pallet_caixas_atuais WHERE caixa_id=2")
        vinculo = cursor.fetchone()
        cursor.execute("""SELECT pallet_origem_id,pallet_destino_id,evento_origem_id
                          FROM pallet_caixa_eventos WHERE idempotency_key='TRANS-G'""")
        evento = cursor.fetchone()
    assert int(vinculo["pallet_id"]) == destino["id"] and int(vinculo["versao"]) == 1
    assert int(evento["pallet_origem_id"]) == origem["id"]
    assert int(evento["pallet_destino_id"]) == destino["id"]
    assert evento["evento_origem_id"] is not None


def test_i_retries_nao_duplicam_vinculo_nem_evento():
    origem, destino = criar("PALLET-I1"), criar("PALLET-I2")
    palletizacao.adicionar_caixa(origem["id"], 3, usuario="Teste", idempotency_key="ADD-I")
    palletizacao.adicionar_caixa(origem["id"], 3, usuario="Teste", idempotency_key="ADD-I")
    palletizacao.transferir_caixa(origem["id"], destino["id"], 3, usuario="Teste", idempotency_key="TRANS-I")
    palletizacao.transferir_caixa(origem["id"], destino["id"], 3, usuario="Teste", idempotency_key="TRANS-I")
    assert contagem("pallet_caixas_atuais", "caixa_id=3") == 1
    assert contagem("pallet_caixa_eventos", "idempotency_key IN ('ADD-I','TRANS-I')") == 2


def test_j_rollback_nao_deixa_evento_ou_vinculo_orfao(monkeypatch):
    pallet = criar("PALLET-J")
    original = palletizacao._id_inserido

    def falhar_no_vinculo(cursor, sql, parametros):
        if "INSERT INTO pallet_caixas_atuais" in sql:
            raise RuntimeError("falha controlada")
        return original(cursor, sql, parametros)

    monkeypatch.setattr(palletizacao, "_id_inserido", falhar_no_vinculo)
    with pytest.raises(RuntimeError, match="falha controlada"):
        palletizacao.adicionar_caixa(
            pallet["id"], 2, usuario="Teste", idempotency_key="ADD-J",
        )
    assert contagem("pallet_caixas_atuais", "caixa_id=2") == 0
    assert contagem("pallet_caixa_eventos", "idempotency_key='ADD-J'") == 0


@pytest.mark.parametrize("status", ["ENCERRADO", "CANCELADO"])
def test_k_pallet_encerrado_ou_cancelado_rejeita_caixa(status):
    pallet = criar(f"PALLET-K-{status}")
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE pallets SET status=%s WHERE id=%s", (status, pallet["id"]))
    with pytest.raises(ValueError, match="encerrado ou cancelado"):
        palletizacao.adicionar_caixa(
            pallet["id"], 2, usuario="Teste", idempotency_key=f"ADD-K-{status}",
        )


def test_h_transferencia_falha_reverte_evento_e_mantem_origem(monkeypatch):
    origem, destino = criar("PALLET-H1"), criar("PALLET-H2")
    palletizacao.adicionar_caixa(origem["id"], 2, usuario="Teste", idempotency_key="ADD-H")
    original = palletizacao._registrar_evento

    def falhar_depois_evento(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("falha transferencia")

    monkeypatch.setattr(palletizacao, "_registrar_evento", falhar_depois_evento)
    with pytest.raises(RuntimeError, match="falha transferencia"):
        palletizacao.transferir_caixa(
            origem["id"], destino["id"], 2, usuario="Teste", idempotency_key="TRANS-H",
        )
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pallet_id FROM pallet_caixas_atuais WHERE caixa_id=2")
        assert int(cursor.fetchone()["pallet_id"]) == origem["id"]
    assert contagem("pallet_caixa_eventos", "idempotency_key='TRANS-H'") == 0


def test_historico_e_append_only_no_banco():
    pallet = criar("PALLET-APPEND")
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT id FROM pallet_caixa_eventos WHERE pallet_id=%s", (pallet["id"],))
        evento_id = cursor.fetchone()["id"]
        with pytest.raises(psycopg2.Error):
            cursor.execute("DELETE FROM pallet_caixa_eventos WHERE id=%s", (evento_id,))
