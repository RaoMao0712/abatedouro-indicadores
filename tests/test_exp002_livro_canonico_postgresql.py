"""EXP-002: consolidação do livro canônico em PostgreSQL real descartável."""

import os

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REQUIRE_REAL_POSTGRESQL = os.getenv("REQUIRE_REAL_POSTGRESQL") == "1"
if not TEST_DATABASE_URL and REQUIRE_REAL_POSTGRESQL:
    raise RuntimeError("PostgreSQL real é obrigatório para esta execução.")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente")

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    from modules.expedicao import movimentacoes_canonicas as canonico  # noqa: E402
    from modules.relatorios import expedicao as relatorio  # noqa: E402


DDL = """
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
CREATE TABLE locais_estoque(id INTEGER PRIMARY KEY,nome TEXT);
CREATE TABLE expedicoes(
 id INTEGER PRIMARY KEY,numero_romaneio TEXT,data TEXT,status TEXT,
 tipo_movimentacao TEXT,destino_local_id INTEGER
);
CREATE TABLE pa_caixas(
 id INTEGER PRIMARY KEY,codigo_caixa TEXT,sku TEXT,data_fabricacao TEXT,
 data_validade TEXT,peso_bruto NUMERIC,peso_liquido NUMERIC,
 quantidade_bandejas NUMERIC,status TEXT,disponibilidade TEXT,
 local_estoque_id INTEGER,apresentacao TEXT
);
CREATE TABLE pa_caixa_composicao(
 id SERIAL PRIMARY KEY,caixa_id INTEGER,op_id INTEGER,quantidade_bandejas NUMERIC
);
CREATE TABLE expedicao_itens(
 id SERIAL PRIMARY KEY,expedicao_id INTEGER,caixa_id INTEGER,
 local_anterior_id INTEGER,ativo INTEGER DEFAULT 1
);
CREATE TABLE estoque_eventos(
 id SERIAL PRIMARY KEY,caixa_id INTEGER,expedicao_id INTEGER,acao TEXT,
 usuario TEXT,criado_em TIMESTAMP,idempotency_key TEXT UNIQUE
);
CREATE TABLE pa_movimentacoes(
 id SERIAL PRIMARY KEY,caixa_id INTEGER,local_origem_id INTEGER,
 local_destino_id INTEGER,tipo TEXT,expedicao_id INTEGER,
 usuario TEXT,criado_em TIMESTAMP
);
INSERT INTO locais_estoque VALUES(1,'Abatedouro'),(2,'Camara Fria LSM');
INSERT INTO expedicoes VALUES
 (10,'ROM-CANONICO','2026-10-17','Concluído','TRANSFERENCIA',2),
 (11,'ROM-VENDA','2026-10-17','Concluído','VENDA_DIRETA',NULL),
 (12,'ROM-LEGADO','2026-10-17','Concluído','TRANSFERENCIA',2);
INSERT INTO pa_caixas VALUES
 (1,'CX-CANONICA','Galinha Cortada','2026-10-17','2027-10-17',11,10,12,
  'Transferido','TRANSFERIDO',2,'Caixa'),
 (2,'CX-VENDA','Galinha Cortada','2026-10-17','2027-10-17',12,11,12,
  'Expedido','EXPEDIDO',1,'Caixa'),
 (3,'CX-LEGADA','Galinha Cortada','2026-10-17','2027-10-17',13,12,12,
  'Transferido','TRANSFERIDO',2,'Caixa');
INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas)
 VALUES(1,101,12),(2,102,12),(3,103,12);
INSERT INTO expedicao_itens(expedicao_id,caixa_id,local_anterior_id)
 VALUES(10,1,1),(11,2,1),(12,3,1);
INSERT INTO estoque_eventos(caixa_id,expedicao_id,acao,usuario,criado_em,idempotency_key)
 VALUES(1,10,'CONFIRMACAO_ROMANEIO','Atual','2026-10-17 10:00','CAN-1'),
       (2,11,'VENDA_DIRETA','Atual','2026-10-17 11:00','CAN-2');
INSERT INTO pa_movimentacoes(
 caixa_id,local_origem_id,local_destino_id,tipo,expedicao_id,usuario,criado_em)
 VALUES(1,1,2,'TRANSFERENCIA',10,'Duplicado','2026-10-17 10:00'),
       (3,1,2,'TRANSFERENCIA',12,'Legado','2026-10-17 09:00');
"""


def conectar():
    return psycopg2.connect(TEST_DATABASE_URL, cursor_factory=RealDictCursor)


@pytest.fixture(scope="module", autouse=True)
def schema():
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute(DDL)


@pytest.fixture(autouse=True)
def conexoes(monkeypatch):
    monkeypatch.setattr(relatorio, "conectar", conectar)
    monkeypatch.setattr(canonico, "conectar", conectar)


def filtros():
    return relatorio.normalizar_filtros({
        "data_inicio": "2026-10-17", "data_fim": "2026-10-17",
        "por_pagina": "100",
    }, relatorio.RELATORIOS_EXPEDICAO["transferencias"])


def test_a_b_d_e_f_relatorio_canonico_venda_fallback_e_sem_duplicidade():
    transferencias = relatorio.buscar_transferencias(filtros())
    assert [(item["codigo_caixa"], item["fonte_livro"]) for item in transferencias] == [
        ("CX-CANONICA", "estoque_eventos"),
        ("CX-LEGADA", "pa_movimentacoes_fallback"),
    ]
    historico_venda = relatorio.buscar_historico_caixa(2)
    assert len(historico_venda) == 1
    assert historico_venda[0]["tipo"] == "VENDA_DIRETA"
    assert historico_venda[0]["fonte_livro"] == "estoque_eventos"


def test_c_estorno_identifica_saida_original_no_livro_canonico():
    with conectar() as conn:
        with conn.cursor() as cursor:
            eventos = canonico.buscar_eventos_sucessores_cursor(cursor, [1])
    saidas = [item for item in eventos if item["tipo"] == "CONFIRMACAO_ROMANEIO"]
    assert len(saidas) == 1 and saidas[0]["fonte"] == "estoque_eventos"


def test_reconciliacao_read_only_aponta_exclusivamente_o_legado_real():
    divergencias = canonico.reconciliar_movimentacoes_expedicao()
    assert [(item["numero_romaneio"], item["divergencia"]) for item in divergencias] == [
        ("ROM-LEGADO", "SOMENTE_LIVRO_LEGADO"),
    ]


def test_g_livro_legado_vazio_nao_interrompe_fluxo_atual():
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM pa_movimentacoes")
    transferencias = relatorio.buscar_transferencias(filtros())
    assert [(item["codigo_caixa"], item["fonte_livro"]) for item in transferencias] == [
        ("CX-CANONICA", "estoque_eventos"),
    ]
    assert relatorio.buscar_historico_caixa(2)[0]["tipo"] == "VENDA_DIRETA"
