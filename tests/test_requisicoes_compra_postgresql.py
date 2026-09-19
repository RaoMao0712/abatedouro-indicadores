"""Homologação PostgreSQL real da Requisição de Compra.

Executar isoladamente com TEST_DATABASE_URL apontando para banco descartável.
Esta suíte destrói e recria o schema public.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import threading
import time

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database" / "20260919_requisicoes_compra.sql"
ROLLBACK = ROOT / "database" / "20260919_requisicoes_compra_rollback.sql"
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REQUIRE_REAL_POSTGRESQL = os.getenv("REQUIRE_REAL_POSTGRESQL") == "1"
if not TEST_DATABASE_URL and REQUIRE_REAL_POSTGRESQL:
    raise RuntimeError("PostgreSQL real é obrigatório para esta execução.")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente")

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    import database.connection as dbc  # noqa: E402
    from modules.requisicoes_compra import services as svc  # noqa: E402
else:
    dbc = svc = None


BASE_DDL = """
CREATE TABLE controle_base (id SERIAL PRIMARY KEY, marcador TEXT NOT NULL);
INSERT INTO controle_base(marcador) VALUES ('preservar');
CREATE TABLE almoxarifado_insumos(id SERIAL PRIMARY KEY,descricao TEXT,categoria TEXT,unidade TEXT,ativo TEXT,origem_baixa TEXT);
CREATE TABLE almoxarifado_lotes(id SERIAL PRIMARY KEY,insumo_id INTEGER,quantidade_atual REAL);
CREATE TABLE almoxarifado_movimentacoes(id SERIAL PRIMARY KEY,insumo_id INTEGER,quantidade REAL);
CREATE TABLE almoxarifado_requisicoes(id SERIAL PRIMARY KEY,status TEXT,ordem_servico_id INTEGER);
CREATE TABLE almoxarifado_requisicao_itens(id SERIAL PRIMARY KEY,requisicao_id INTEGER,insumo_id INTEGER,quantidade_reservada REAL);
CREATE TABLE almoxarifado_requisicao_alocacoes(id SERIAL PRIMARY KEY);
CREATE TABLE manutencao_ordens(id SERIAL PRIMARY KEY,status TEXT,descricao TEXT,setor TEXT,sgi_nc_id INTEGER);
CREATE TABLE ordens_producao(id SERIAL PRIMARY KEY,data TEXT,status TEXT,sku TEXT);
CREATE TABLE sgi_verificacoes(id SERIAL PRIMARY KEY,formulario_codigo TEXT,formulario_nome TEXT,setor TEXT,vinculo_tipo TEXT,local_id INTEGER,equipamento_id INTEGER);
CREATE TABLE sgi_nao_conformidades(id SERIAL PRIMARY KEY,verificacao_id INTEGER,descricao TEXT,criticidade TEXT,situacao TEXT);
CREATE TABLE movimentacoes_financeiras(id SERIAL PRIMARY KEY);
INSERT INTO almoxarifado_insumos(id,descricao,categoria,unidade,ativo,origem_baixa) VALUES
 (1,'Bandeja X','Embalagem','un','Sim','ORDEM_PRODUCAO'),
 (2,'Inativo','Manutenção','un','Nao','REQUISICAO_ALMOXARIFADO'),
 (3,'Peça oficial','Manutenção','un','Sim','REQUISICAO_ALMOXARIFADO');
SELECT setval(pg_get_serial_sequence('almoxarifado_insumos','id'),3,true);
INSERT INTO almoxarifado_lotes(insumo_id,quantidade_atual) VALUES(1,1200);
INSERT INTO almoxarifado_requisicoes(status,ordem_servico_id) VALUES('EMITIDA',NULL);
INSERT INTO almoxarifado_requisicao_itens(requisicao_id,insumo_id,quantidade_reservada) VALUES(1,1,200);
INSERT INTO manutencao_ordens(id,status,descricao,setor,sgi_nc_id) VALUES(10,'Aberta','OS com acentuação, aspas ''duplas'' & segurança','Manutenção',NULL),(11,'Aberta','OS SGI','Qualidade',7);
SELECT setval(pg_get_serial_sequence('manutencao_ordens','id'),11,true);
INSERT INTO ordens_producao(id,data,status,sku) VALUES(20,'2026-09-19','Aberta','Produto A');
SELECT setval(pg_get_serial_sequence('ordens_producao','id'),20,true);
INSERT INTO sgi_verificacoes(id,formulario_codigo,formulario_nome,setor,vinculo_tipo,local_id,equipamento_id) VALUES(30,'PLM 02','Verificação','Qualidade','Equipamento',1,2);
INSERT INTO sgi_nao_conformidades(id,verificacao_id,descricao,criticidade,situacao) VALUES(31,30,'NC com ação corretiva','ALTA','Aberta');
"""


def conectar():
    return psycopg2.connect(TEST_DATABASE_URL, cursor_factory=RealDictCursor)


def aplicar(path):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute(path.read_text(encoding="utf-8"))


def resetar():
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        cur.execute(BASE_DDL)
    aplicar(MIGRATION)


@pytest.fixture(scope="module", autouse=True)
def banco_postgresql_real():
    resetar()
    yield


@pytest.fixture(autouse=True)
def limpar_rcs():
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE requisicao_compra_eventos,requisicao_compra_itens,requisicoes_compra RESTART IDENTITY")


def usr(i, perfil="admin"):
    return {"id": i, "nome": f"Usuário {i}", "perfil": perfil}


def dados(tipo="ADMINISTRATIVO", oid=None):
    return {"tipo_origem": tipo, "origem_id": oid, "setor": "Administrativo", "origem_descricao": "Descrição com á, aspas ' e &", "origem_numero": "DOC-1", "prioridade": "NORMAL", "justificativa": "Teste PostgreSQL"}


def item(material=1, quantidade="1"):
    return {"material_id": str(material), "quantidade_item": quantidade, "descricao_item": "", "unidade_item": "", "custo_item": "", "observacao_item": ""}


def provisorio():
    return {"material_id": "", "quantidade_item": "2", "descricao_item": "Peça provisória & especial", "unidade_item": "un", "custo_item": "", "observacao_item": "snapshot original"}


def criar(chave, ator=None, tipo="ADMINISTRATIVO", oid=None, itens=None):
    return svc.criar_rascunho(dados(tipo, oid), itens or [item()], ator=ator or usr(1), idempotency_key=chave)


def paralelas(a, b):
    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(a), pool.submit(b)]
        resultados, erros = [], []
        for futuro in futuros:
            try:
                resultados.append(futuro.result(timeout=20))
            except Exception as erro:  # desfecho concorrente esperado em uma ponta
                erros.append(erro)
    return resultados, erros


def eventos(rid, nome):
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) total FROM requisicao_compra_eventos WHERE requisicao_compra_id=%s AND evento=%s", (rid, nome))
        return int(cur.fetchone()["total"])


def test_01_migration_reaplicacao_rollback_schema_e_constraints():
    aplicar(MIGRATION)
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename IN ('requisicoes_compra','requisicao_compra_itens','requisicao_compra_eventos') ORDER BY tablename")
        assert [x["tablename"] for x in cur.fetchall()] == ["requisicao_compra_eventos", "requisicao_compra_itens", "requisicoes_compra"]
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public' AND indexname LIKE 'idx_rc_%'")
        assert len(cur.fetchall()) == 4
        cur.execute("SELECT column_default,is_nullable,data_type FROM information_schema.columns WHERE table_name='requisicoes_compra' AND column_name='versao'")
        assert cur.fetchone() == {"column_default": "0", "is_nullable": "NO", "data_type": "integer"}
        cur.execute("SELECT is_nullable,data_type FROM information_schema.columns WHERE table_name='requisicao_compra_itens' AND column_name='nu'")
        assert cur.fetchone() == {"is_nullable": "YES", "data_type": "text"}
        cur.execute("SELECT pg_get_serial_sequence('requisicoes_compra','id') seq")
        assert cur.fetchone()["seq"]
    aplicar(ROLLBACK)
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT marcador FROM controle_base")
        assert cur.fetchone()["marcador"] == "preservar"
        cur.execute("SELECT to_regclass('public.requisicoes_compra') tabela")
        assert cur.fetchone()["tabela"] is None
    aplicar(MIGRATION)


def test_02_numeracao_sequence_e_criacoes_concorrentes():
    a = criar("seq-1"); b = criar("seq-2")
    assert (a["numero"], b["numero"]) == ("RC-000001", "RC-000002")
    resultados, erros = paralelas(lambda: criar("conc-a", usr(10)), lambda: criar("conc-b", usr(11)))
    assert not erros and len({x["id"] for x in resultados}) == 2 and len({x["numero"] for x in resultados}) == 2


def test_03_criacao_idempotente_concorrente():
    resultados, erros = paralelas(lambda: criar("mesma-chave", usr(20)), lambda: criar("mesma-chave", usr(20)))
    assert not erros and resultados[0]["id"] == resultados[1]["id"]
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) total FROM requisicoes_compra WHERE chave_criacao='mesma-chave'")
        assert cur.fetchone()["total"] == 1


def test_03b_rollback_de_sequence_admite_gap_sem_numero_vazio_ou_duplicado():
    with conectar() as conn, conn.cursor() as cur:
        cur.execute("SELECT nextval(pg_get_serial_sequence('requisicoes_compra','id')) id")
        consumido = int(cur.fetchone()["id"])
        conn.rollback()
    rc = criar("apos-rollback")
    assert rc["id"] > consumido and rc["numero"] == f"RC-{rc['id']:06d}"
    assert rc["numero"]


def _aberta(chave, autor=1):
    rc = criar(chave, usr(autor))
    return svc.enviar(rc["id"], ator=usr(autor), versao=0, idempotency_key=chave+":env")


def test_03c_for_update_bloqueia_service_em_backend_independente():
    rc = _aberta("lock-real")
    primeira = conectar(); cur = primeira.cursor()
    cur.execute("SELECT id FROM requisicoes_compra WHERE id=%s FOR UPDATE", (rc["id"],))
    terminou = threading.Event(); resultado = {}

    def aprovar_bloqueada():
        try:
            resultado["rc"] = svc.aprovar(rc["id"], ator=usr(2), versao=1, idempotency_key="lock-apr")
        finally:
            terminou.set()

    thread = threading.Thread(target=aprovar_bloqueada)
    thread.start(); time.sleep(.35)
    assert not terminou.is_set()
    primeira.commit(); primeira.close(); thread.join(10)
    assert terminou.is_set() and resultado["rc"]["status"] == "APROVADA"


@pytest.mark.parametrize("outra,motivo", [("cancelar", "Cancelamento concorrente"), ("rejeitar", "Rejeição concorrente")])
def test_04_decisoes_conflitantes_serializadas_por_for_update(outra, motivo):
    rc = _aberta("terminal-"+outra)
    segunda = svc.cancelar if outra == "cancelar" else svc.rejeitar
    resultados, erros = paralelas(
        lambda: svc.aprovar(rc["id"], ator=usr(2), versao=1, idempotency_key="aprovar-"+outra),
        lambda: segunda(rc["id"], ator=usr(3, "gerencia"), versao=1, idempotency_key=outra+"-conc", motivo=motivo),
    )
    assert len(resultados) == 1 and len(erros) == 1
    final = svc.buscar_rc(rc["id"])
    assert final["versao"] == 2 and final["status"] in {"APROVADA", "CANCELADA", "REJEITADA"}
    assert sum(eventos(rc["id"], n) for n in ("APROVACAO", "CANCELAMENTO", "REJEICAO")) == 1


def test_05_edicao_contra_envio_sem_lost_update():
    rc = criar("edit-env")
    resultados, erros = paralelas(
        lambda: svc.editar_rascunho(rc["id"], {"prioridade": "NORMAL", "justificativa": "edit"}, [item(3, "9")], ator=usr(1), versao=0, idempotency_key="edit-conc"),
        lambda: svc.enviar(rc["id"], ator=usr(1), versao=0, idempotency_key="env-conc"),
    )
    assert len(resultados) == 1 and len(erros) == 1
    final = svc.buscar_rc(rc["id"])
    assert final["versao"] == 1
    if final["status"] == "RASCUNHO":
        assert final["itens"][0]["quantidade_solicitada"] == 9
    else:
        assert final["status"] == "ABERTA" and final["itens"][0]["quantidade_solicitada"] == 1


@pytest.mark.parametrize("acao,evento", [("envio", "ENVIO"), ("aprovacao", "APROVACAO"), ("cancelamento", "CANCELAMENTO")])
def test_06_idempotencia_concorrente_de_acoes(acao, evento):
    rc = criar("idem-"+acao)
    if acao in {"aprovacao", "cancelamento"}:
        rc = svc.enviar(rc["id"], ator=usr(1), versao=0, idempotency_key="pre-"+acao)
    if acao == "envio":
        chamada = lambda: svc.enviar(rc["id"], ator=usr(1), versao=0, idempotency_key="mesma-env")
    elif acao == "aprovacao":
        chamada = lambda: svc.aprovar(rc["id"], ator=usr(2), versao=1, idempotency_key="mesma-apr")
    else:
        chamada = lambda: svc.cancelar(rc["id"], ator=usr(2, "gerencia"), versao=1, idempotency_key="mesma-can", motivo="Fim")
    resultados, erros = paralelas(chamada, chamada)
    assert not erros and len(resultados) == 2 and eventos(rc["id"], evento) == 1


def test_07_vinculo_provisorio_concorrente_e_snapshot():
    rc = criar("prov-pg", itens=[provisorio()]); iid = rc["itens"][0]["id"]
    resultados, erros = paralelas(
        lambda: svc.vincular_material(rc["id"], iid, 3, ator=usr(8, "pcp"), idempotency_key="vinc-a"),
        lambda: svc.vincular_material(rc["id"], iid, 3, ator=usr(9, "pcp"), idempotency_key="vinc-b"),
    )
    assert len(resultados) == 1 and len(erros) == 1
    final = svc.buscar_rc(rc["id"]); assert final["itens"][0]["descricao_snapshot"] == "Peça provisória & especial"
    assert final["itens"][0]["material_id"] == 3 and eventos(rc["id"], "VINCULO_MATERIAL") == 1


@pytest.mark.parametrize("perfil", ["admin", "gerencia"])
def test_08_autoaprovacao_bloqueada_no_postgresql(perfil):
    rc = criar("auto-"+perfil, usr(40, perfil)); rc = svc.enviar(rc["id"], ator=usr(40, perfil), versao=0, idempotency_key="env-auto-"+perfil)
    with pytest.raises(PermissionError):
        svc.aprovar(rc["id"], ator=usr(40, perfil), versao=1, idempotency_key="apr-auto-"+perfil)
    assert svc.buscar_rc(rc["id"])["status"] == "ABERTA"


def test_09_unique_reais_snapshot_queries_e_performance():
    rc = criar("unicode", tipo="ORDEM_SERVICO", oid=10)
    assert "acentuação" in rc["origem_descricao_snapshot"] and "&" in rc["origem_descricao_snapshot"]
    with conectar() as conn, conn.cursor() as cur:
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO requisicoes_compra(numero,status,tipo_origem,origem_descricao_snapshot,origem_dados_snapshot,setor,solicitante_nome_snapshot,prioridade,chave_criacao,criado_em,atualizado_em) SELECT numero,status,tipo_origem,origem_descricao_snapshot,origem_dados_snapshot,setor,solicitante_nome_snapshot,prioridade,'outra-chave',criado_em,atualizado_em FROM requisicoes_compra WHERE id=%s", (rc["id"],))
    for n in range(100):
        criar(f"volume-{n}", usr(50), tipo="ORDEM_SERVICO" if n % 3 == 0 else "ADMINISTRATIVO", oid=10 if n % 3 == 0 else None)
    reposicao=criar("lookup-rep", tipo="REPOSICAO_ESTOQUE", oid=1)
    nc=criar("lookup-nc", ator=usr(51,"qualidade"), tipo="NAO_CONFORMIDADE_SGI", oid=31)
    inicio=time.perf_counter(); encontrados=svc.listar({"status":"RASCUNHO","tipo_origem":"ORDEM_SERVICO","termo":"Bandeja X"}); duracao_lista=time.perf_counter()-inicio
    assert encontrados and duracao_lista < 5
    inicio=time.perf_counter(); assert svc.buscar_rc(rc["id"])["id"] == rc["id"]; duracao_detalhe=time.perf_counter()-inicio
    inicio=time.perf_counter(); assert svc.listar_por_origens("ORDEM_SERVICO", [10])[10]; duracao_lookup=time.perf_counter()-inicio
    assert svc.listar_por_origens("REPOSICAO_ESTOQUE", [1])[1][0]["id"] == reposicao["id"]
    assert svc.listar_por_origens("NAO_CONFORMIDADE_SGI", [31])[31][0]["id"] == nc["id"]
    assert max(duracao_detalhe,duracao_lookup) < 5
    assert svc.listar({"termo":"%' OR 1=1 --"}) == []


def test_10_nu_lock_concorrencia_e_idempotencia_real():
    rc=_aberta("nu-real")
    rc=svc.aprovar(rc["id"],ator=usr(2,"gerencia"),versao=1,idempotency_key="nu-real-apr")
    iid=rc["itens"][0]["id"]
    resultados,erros=paralelas(
        lambda: svc.aplicar_nu(rc["id"],[iid],"001234",ator=usr(8,"pcp"),versao=2,idempotency_key="nu-conc-a"),
        lambda: svc.aplicar_nu(rc["id"],[iid],"999999",ator=usr(9,"pcp"),versao=2,idempotency_key="nu-conc-b"),
    )
    assert len(resultados)==1 and len(erros)==1
    final=svc.buscar_rc(rc["id"]); assert final["itens"][0]["nu"] in {"001234","999999"} and final["versao"]==3
    retry,erros=paralelas(
        lambda: svc.aplicar_nu(rc["id"],[iid],"777777",ator=usr(8,"pcp"),versao=3,idempotency_key="nu-mesma"),
        lambda: svc.aplicar_nu(rc["id"],[iid],"777777",ator=usr(8,"pcp"),versao=3,idempotency_key="nu-mesma"),
    )
    assert not erros and len(retry)==2
    assert eventos(rc["id"],"NU_APLICADA")==1 and eventos(rc["id"],"NU_ALTERADA")==1
