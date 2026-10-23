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
CREATE TABLE expedicoes(id SERIAL PRIMARY KEY,numero_romaneio TEXT,status TEXT DEFAULT 'Aberto');
CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,sku TEXT,status TEXT DEFAULT 'Aberta');
CREATE TABLE pa_caixas(
 id SERIAL PRIMARY KEY,codigo_caixa TEXT UNIQUE NOT NULL,sku TEXT NOT NULL,
 quantidade_bandejas NUMERIC DEFAULT 0,peso_liquido NUMERIC DEFAULT 0,
 quantidade_pacotes INTEGER DEFAULT 0,quantidade_galinhas INTEGER DEFAULT 0,
 unidade_estoque TEXT DEFAULT 'CAIXA',apresentacao TEXT,
 status TEXT DEFAULT 'Em estoque',disponibilidade TEXT DEFAULT 'DISPONIVEL',condicao TEXT DEFAULT 'CONFORME',
 estoque_operacional INTEGER DEFAULT 1,local_estoque_id INTEGER,peso_bruto NUMERIC,
 quantidade_pacotes_reservados INTEGER DEFAULT 0,reservado_expedicao_id INTEGER
);
CREATE TABLE pa_caixa_composicao(
 id SERIAL PRIMARY KEY,caixa_id INTEGER NOT NULL REFERENCES pa_caixas(id),
 op_id INTEGER NOT NULL REFERENCES ordens_producao(id),quantidade_bandejas NUMERIC DEFAULT 0
);
CREATE TABLE expedicao_itens(
 id SERIAL PRIMARY KEY,expedicao_id INTEGER,caixa_id INTEGER,ativo INTEGER DEFAULT 1
);
INSERT INTO locais_estoque(nome,tipo) VALUES('Abatedouro','interno'),('Camara Fria LSM','interno');
INSERT INTO ordens_producao(id,sku) VALUES(121,'Galinha Inteira'),(122,'Galinha Cortada');
INSERT INTO pa_caixas(
 codigo_caixa,sku,quantidade_bandejas,peso_liquido,quantidade_pacotes,
 quantidade_galinhas,local_estoque_id
) VALUES
 ('CX-1','Galinha Inteira',0,100,962,1924,1),
 ('CX-2','Galinha Cortada',12,22,0,0,1),
 ('CX-3','Galinha Cortada',8,14,0,0,1);
UPDATE pa_caixas SET unidade_estoque='PACOTE',apresentacao='PACOTE' WHERE codigo_caixa='CX-1';
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
            cursor.execute("TRUNCATE op_palletizacao_excecoes, pallet_caixas_atuais, pallet_caixa_eventos, pallets RESTART IDENTITY")
            cursor.execute("DELETE FROM pa_caixa_composicao WHERE caixa_id IN (SELECT id FROM pa_caixas WHERE posicao_origem_id IS NOT NULL)")
            cursor.execute("DELETE FROM pa_caixas WHERE posicao_origem_id IS NOT NULL")
            cursor.execute("""UPDATE pa_caixas SET quantidade_galinhas=1924,quantidade_pacotes=962,
                peso_liquido=100,peso_bruto=NULL,quantidade_original_galinhas=NULL WHERE id=1""")

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


def test_p10_postgresql_fracionamento_concorrente_idempotente_e_invariante():
    criar("P10-SCHEMA")
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS galinhas_por_pacote INTEGER")
        cursor.execute("DELETE FROM pa_caixa_composicao WHERE caixa_id IN (SELECT id FROM pa_caixas WHERE posicao_origem_id=1)")
        cursor.execute("DELETE FROM pa_caixas WHERE posicao_origem_id=1")
        cursor.execute("""UPDATE pa_caixas SET quantidade_galinhas=1924,quantidade_pacotes=962,
            galinhas_por_pacote=2,peso_liquido=100,peso_bruto=100,
            quantidade_original_galinhas=NULL,posicao_origem_id=NULL,
            quantidade_pacotes_reservados=0,reservado_expedicao_id=NULL WHERE id=1""")
    pallet_a, pallet_b = criar("P10-PG-A"), criar("P10-PG-B")
    erros = []

    def operar(pallet_id, quantidade, chave):
        try:
            palletizacao.palletizar_quantidade_pacote(
                pallet_id, 1, quantidade, usuario="PCP", idempotency_key=chave)
        except Exception as erro:
            erros.append(erro)

    threads = [threading.Thread(target=operar, args=(pallet_a["id"], 330, "P10-PG-330")),
               threading.Thread(target=operar, args=(pallet_b["id"], 500, "P10-PG-500"))]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert not erros
    palletizacao.palletizar_quantidade_pacote(
        pallet_a["id"], 1, 330, usuario="PCP", idempotency_key="P10-PG-330")
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT quantidade_galinhas FROM pa_caixas WHERE id=1")
        assert cursor.fetchone()["quantidade_galinhas"] == 1094
        cursor.execute("SELECT quantidade_galinhas FROM pa_caixas WHERE posicao_origem_id=1 ORDER BY quantidade_galinhas")
        assert [item["quantidade_galinhas"] for item in cursor.fetchall()] == [330, 500]
    assert palletizacao.auditar_fracionamento_posicao(1)["status"] == "OK"
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("""UPDATE pa_caixas SET quantidade_galinhas=1924,quantidade_pacotes=962,
            peso_liquido=100,peso_bruto=NULL,quantidade_original_galinhas=NULL WHERE id=1""")


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


def test_p2_consulta_agregacoes_filtros_e_localizacao_por_codigo():
    pallet = criar("PALLET-P2")
    palletizacao.adicionar_caixa(pallet["id"], 1, usuario="Teste", idempotency_key="ADD-P2")
    detalhe = palletizacao.consultar_pallet(pallet["id"])
    assert detalhe["produtos_texto"] == "Galinha Inteira"
    assert detalhe["ops_texto"] == "121"
    assert detalhe["totais"]["peso_liquido"] == 100.0
    assert detalhe["ops"][0]["pacotes"] == 962
    assert palletizacao.buscar_pallet_por_codigo(f"  {pallet['codigo'].lower()}  ")["id"] == pallet["id"]
    for filtros in (
        {"codigo": pallet["codigo"][-3:]}, {"status": "ABERTO"},
        {"produto": "inteira"}, {"op": "121"}, {"localizacao": "1"},
    ):
        assert [item["id"] for item in palletizacao.listar_pallets(filtros)] == [pallet["id"]]


def test_p2_criacao_concorrente_codigo_unico_e_idempotencia():
    barreira = threading.Barrier(4)
    resultados, erros = [], []

    def alvo(chave):
        try:
            barreira.wait(timeout=5)
            resultados.append(criar(chave))
        except Exception as erro:
            erros.append(erro)

    threads = [threading.Thread(target=alvo, args=(chave,)) for chave in ("P2-C1", "P2-C2", "P2-IDEM", "P2-IDEM")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not erros
    assert len({item["codigo"] for item in resultados}) == 3
    assert len({item["id"] for item in resultados if item["codigo"] == next(r["codigo"] for r in resultados if r["id"] == resultados[-1]["id"])}) >= 1
    assert contagem("pallets") == 3


def test_p3_transferencia_concorrente_da_mesma_caixa_apenas_uma_vence():
    origem = criar("P3-CONC-ORIGEM")
    destinos = [criar("P3-CONC-D1"), criar("P3-CONC-D2")]
    palletizacao.adicionar_caixa(
        origem["id"], 2, usuario="Concorrencia", idempotency_key="P3-CONC-ADD",
    )
    barreira = threading.Barrier(2)
    resultados, erros = [], []

    def alvo(destino, chave):
        try:
            barreira.wait(timeout=5)
            palletizacao.transferir_caixa(
                origem["id"], destino["id"], 2,
                usuario="Concorrencia", idempotency_key=chave,
            )
            resultados.append(destino["id"])
        except Exception as erro:
            erros.append(erro)

    threads = [
        threading.Thread(target=alvo, args=(destinos[0], "P3-CONC-T1")),
        threading.Thread(target=alvo, args=(destinos[1], "P3-CONC-T2")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert len(resultados) == 1
    assert len(erros) == 1
    assert contagem("pallet_caixas_atuais", "caixa_id=2") == 1
    assert contagem("pallet_caixa_eventos", "tipo_evento='CAIXA_TRANSFERIDA' AND caixa_id=2") == 1


def test_p5_agregacoes_filtros_reserva_pacote_sem_pallet_e_zero_mutacao():
    vazio, cortada, pacote = criar("P5-PG-V"), criar("P5-PG-C"), criar("P5-PG-P")
    palletizacao.adicionar_caixas(cortada["id"], [2, 3], usuario="Teste", idempotency_key="P5-PG-ADD-C")
    palletizacao.adicionar_caixa(pacote["id"], 1, usuario="Teste", idempotency_key="P5-PG-ADD-P")
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("UPDATE pa_caixas SET disponibilidade='RESERVADO',reservado_expedicao_id=10 WHERE id=2")
        cursor.execute("UPDATE pa_caixas SET quantidade_pacotes_reservados=100 WHERE id=1")
        cursor.execute("INSERT INTO expedicoes(id,numero_romaneio,status) VALUES(10,'PG-10','Aberto')")
        cursor.execute("INSERT INTO expedicao_itens(expedicao_id,caixa_id,ativo) VALUES(10,2,1)")
        cursor.execute("""SELECT id,status,disponibilidade,estoque_operacional,
                                  quantidade_pacotes_reservados,reservado_expedicao_id
                           FROM pa_caixas ORDER BY id""")
        antes = [dict(item) for item in cursor.fetchall()]
        cursor.execute("SELECT id,sku FROM ordens_producao ORDER BY id")
        ops_antes = [dict(item) for item in cursor.fetchall()]
    visao = palletizacao.visao_estoque_por_pallet()
    por_id = {item["id"]: item for item in visao["pallets"]}
    assert por_id[vazio["id"]]["disponibilidade_agregada"] == "VAZIO"
    assert por_id[cortada["id"]]["disponibilidade_agregada"] == "PARCIALMENTE_RESERVADO"
    assert por_id[pacote["id"]]["disponibilidade_agregada"] == "PARCIALMENTE_RESERVADO"
    assert por_id[cortada["id"]]["totais"]["peso_liquido"] == 36
    assert por_id[pacote["id"]]["totais"]["pacotes"] == 962
    assert palletizacao.visao_estoque_por_pallet({"op": "122"})["pallets"][0]["id"] == cortada["id"]
    assert palletizacao.visao_estoque_por_pallet({"produto": "inteira"})["pallets"][0]["id"] == pacote["id"]
    assert visao["sem_pallet"] == []
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT id,status,disponibilidade,estoque_operacional,
                                  quantidade_pacotes_reservados,reservado_expedicao_id
                           FROM pa_caixas ORDER BY id""")
        assert [dict(item) for item in cursor.fetchall()] == antes
        cursor.execute("SELECT id,sku FROM ordens_producao ORDER BY id")
        assert [dict(item) for item in cursor.fetchall()] == ops_antes


def test_p4_organizacao_op_excecao_retry_e_zero_mutacao_postgresql():
    pallet = criar("P4-PG-PALLET")
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT id,status,disponibilidade,estoque_operacional,
                                  quantidade_pacotes_reservados,reservado_expedicao_id
                             FROM pa_caixas WHERE id IN (2,3) ORDER BY id""")
        antes = [dict(item) for item in cursor.fetchall()]
        cursor.execute("SELECT id,sku,status FROM ordens_producao WHERE id=122")
        op_antes = dict(cursor.fetchone())
    palletizacao.adicionar_caixa(
        pallet["id"], 2, usuario="PCP", idempotency_key="P4-PG-ADD",
        dados={"op_id": 122, "origem": "ENCERRAMENTO_OP"},
    )
    resumo = palletizacao.resumo_organizacao_op(122)
    assert resumo["organizadas"] == 1 and resumo["nao_organizadas"] == 1
    with pytest.raises(ValueError, match="justificativa"):
        palletizacao.validar_organizacao_para_encerramento(122)
    primeira = palletizacao.validar_organizacao_para_encerramento(
        122, justificativa="Excecao operacional controlada", usuario="PCP",
        idempotency_key="P4-PG-EXCECAO",
    )
    retry = palletizacao.validar_organizacao_para_encerramento(
        122, justificativa="Excecao operacional controlada", usuario="PCP",
        idempotency_key="P4-PG-EXCECAO",
    )
    assert primeira["nao_organizadas"] == retry["nao_organizadas"] == 1
    assert contagem("op_palletizacao_excecoes", "op_id=122") == 1
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT id,status,disponibilidade,estoque_operacional,
                                  quantidade_pacotes_reservados,reservado_expedicao_id
                             FROM pa_caixas WHERE id IN (2,3) ORDER BY id""")
        depois = [dict(item) for item in cursor.fetchall()]
        cursor.execute("SELECT id,sku,status FROM ordens_producao WHERE id=122")
        op_depois = dict(cursor.fetchone())
    assert antes == depois and op_antes == op_depois


def test_p8_versoes_concorrentes_idempotencia_auditoria_e_zero_mutacao_postgresql():
    pallet = criar("P8-PG-PALLET")
    palletizacao.adicionar_caixas(
        pallet["id"], [2, 3], usuario="PCP", idempotency_key="P8-PG-ADD",
    )
    palletizacao.registrar_impressao_etiqueta(
        pallet["id"], usuario="Expedicao", idempotency_key="P8-PG-V1",
    )
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT id,status,disponibilidade,estoque_operacional,
                                  quantidade_pacotes_reservados,reservado_expedicao_id
                           FROM pa_caixas ORDER BY id""")
        caixas_antes = [dict(item) for item in cursor.fetchall()]
        cursor.execute("SELECT id,sku,status FROM ordens_producao ORDER BY id")
        ops_antes = [dict(item) for item in cursor.fetchall()]
        cursor.execute("SELECT * FROM pallets WHERE id=%s", (pallet["id"],))
        pallet_antes = dict(cursor.fetchone())
    resultados, erros = [], []

    def imprimir(indice):
        try:
            resultados.append(palletizacao.registrar_impressao_etiqueta(
                pallet["id"], usuario=f"Expedicao {indice}",
                idempotency_key=f"P8-PG-V{indice}", justificativa=f"Teste concorrente {indice}",
            ))
        except Exception as erro:  # pragma: no cover - diagnóstico do gate
            erros.append(erro)

    threads = [threading.Thread(target=imprimir, args=(2,)), threading.Thread(target=imprimir, args=(3,))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert not erros
    assert sorted(item["versao"] for item in resultados) == [2, 3]
    retry = palletizacao.registrar_impressao_etiqueta(
        pallet["id"], usuario="Expedicao 2", idempotency_key="P8-PG-V2",
        justificativa="Teste concorrente 2",
    )
    assert retry["versao"] in {2, 3}
    assert contagem("pallet_caixa_eventos", "tipo_evento='ETIQUETA_PALLET_IMPRESSA'") == 3
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("""SELECT id,status,disponibilidade,estoque_operacional,
                                  quantidade_pacotes_reservados,reservado_expedicao_id
                           FROM pa_caixas ORDER BY id""")
        assert [dict(item) for item in cursor.fetchall()] == caixas_antes
        cursor.execute("SELECT id,sku,status FROM ordens_producao ORDER BY id")
        assert [dict(item) for item in cursor.fetchall()] == ops_antes
        cursor.execute("SELECT * FROM pallets WHERE id=%s", (pallet["id"],))
        assert dict(cursor.fetchone()) == pallet_antes


def test_p9_historico_logistico_postgresql_read_only_e_filtrado():
    pallet = criar("P9-PG-HIST")
    palletizacao.adicionar_caixa(
        pallet["id"], 2, usuario="PCP", idempotency_key="P9-PG-HIST-ADD",
        dados={"op_id": 122},
    )
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT * FROM pa_caixas WHERE id=2")
        antes = dict(cursor.fetchone())
    eventos = palletizacao.listar_historico_logistico({
        "pallet": pallet["codigo"], "op": "122", "tipo_evento": "ADICIONADA",
    })
    assert len(eventos) == 1
    assert eventos[0]["objeto"] == "CX-2"
    with conectar() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT * FROM pa_caixas WHERE id=2")
        assert dict(cursor.fetchone()) == antes
