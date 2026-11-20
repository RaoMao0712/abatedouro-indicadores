"""Contratos da BOM, com PostgreSQL descartável para migração e concorrência."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import os
from threading import Barrier
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg2
import pytest

import database
from database import connection
from modules.engenharia_produtos import bom, services


CABECALHO = {
    "descricao": "Estrutura genérica", "data_inicio_vigencia": "2026-01-01",
    "rendimento_entrada": "100", "rendimento_saida": "92",
    "rendimento_unidade_entrada": "Kg", "rendimento_unidade_saida": "Kg",
}


def item(componente="produto:2", **mudancas):
    dados = {
        "componente": componente, "sequencia": "1", "classificacao": "MATERIA_PRIMA",
        "quantidade_base": "2", "unidade": "Un", "regra_calculo": bom.REGRAS[0],
        "fator": "1", "perda_prevista_percentual": "0", "ativo": "1",
    }
    return dados | mudancas


def popular():
    with database.transaction() as conn:
        cur = conn.cursor()
        for nome in ("Conjunto A", "Componente B", "Componente C", "Semiacabado D"):
            cur.execute(database.q("INSERT INTO skus (nome, codigo) VALUES (?, ?)"), (nome, nome))
        cur.execute(database.q("""
            INSERT INTO almoxarifado_insumos (descricao, categoria, unidade)
            VALUES (?, ?, ?)
        """), ("Embalagem padrão", "Embalagem", "Un"))
        cur.execute(database.q("""
            INSERT INTO etapas_catalogo (codigo, nome, natureza, usuario_nome)
            VALUES (?, ?, ?, ?)
        """), ("MONT", "Montagem", "PROCESSO", "PCP"))


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(connection, "DB_NAME", str(tmp_path / "bom.sqlite"))
    monkeypatch.setattr(connection, "DATABASE_URL", None)
    monkeypatch.setattr(bom, "DATABASE_URL", None)
    services.criar_tabelas_engenharia_produtos()
    bom.migrar()
    popular()
    return tmp_path / "bom.sqlite"


@pytest.mark.parametrize(("regra", "base", "fator", "perda", "esperada"), [
    (bom.REGRAS[0], "2", "1", "2", "30.600000"),
    (bom.REGRAS[1], "2", "10", "0", "3.000000"),
    (bom.REGRAS[2], "2.5", "1", "0", "0.375000"),
    (bom.REGRAS[3], "0.2", "1", "0", "0.200000"),
    (bom.REGRAS[4], "1", "12", "0", "2.000000"),
    (bom.REGRAS[1], "1", "128", "0", "0.117188"),
])
def test_calculo(regra, base, fator, perda, esperada):
    registro = item(regra_calculo=regra, quantidade_base=base, fator=fator,
                    perda_prevista_percentual=perda)
    versao = {"produto_id": 1, "numero_versao": 1, "itens": [registro, registro | {"ativo": False}]}
    resultado, = bom.calcular_necessidades(1, versao, "15")
    assert resultado["necessidade_calculada"] == Decimal(esperada)


@pytest.mark.parametrize("quantidade", ["0", "-1", "NaN", "1.0000001"])
def test_calculo_rejeita_quantidade_invalida(quantidade):
    with pytest.raises(ValueError, match="Quantidade planejada"):
        bom.calcular_necessidades(1, {"produto_id": 1, "numero_versao": 1, "itens": []}, quantidade)


def test_calculo_vazio_versao_unidade_e_multiplos_itens():
    versao = {"produto_id": 1, "numero_versao": 1, "itens": []}
    assert bom.calcular_necessidades(1, versao, 1) == []
    with pytest.raises(ValueError, match="Versão"):
        bom.calcular_necessidades(2, versao, 1)
    versao["itens"] = [item(unidade="inválida")]
    with pytest.raises(ValueError, match="Unidade"):
        bom.calcular_necessidades(1, versao, 1)
    versao["itens"] = [item(), item("produto:3", quantidade_base="0.5")]
    assert [linha["necessidade_calculada"] for linha in bom.calcular_necessidades(1, versao, 10)] == [20, 5]


def exercitar_versoes():
    assert bom.estado_produtivo(1) == "LEGADO"
    with pytest.raises(ValueError, match="fabricável"):
        bom.criar_versao(1, CABECALHO, 9)
    bom.definir_aquisicao(1, True, True)
    v1 = bom.criar_versao(1, CABECALHO, 9)
    assert bom.estado_produtivo(1) == "EM_CONFIGURACAO"
    assert bom.estado_produtivo(4) == "LEGADO"
    with pytest.raises(ValueError, match="publicada"):
        bom.ativar(v1, 9, ativa_esperada=None)
    bom.salvar_item(v1, item(), 9)
    bom.salvar_item(v1, item("produto:3", sequencia="2", quantidade_base="0.5"), 9)
    bom.salvar_item(v1, item("insumo:1", sequencia="3", regra_calculo=bom.REGRAS[4],
                            classificacao="EMBALAGEM", fator="12", etapa_id="1"), 9)
    with pytest.raises(ValueError, match="sequência"):
        bom.salvar_item(v1, item(), 9)
    bom.publicar(v1, 9)
    anterior = bom.detalhar(v1)
    assert anterior["status"] == "PUBLICADA"
    assert bom.estado_produtivo(1) == "EM_CONFIGURACAO"
    bom.ativar(v1, 9, ativa_esperada=None)
    assert bom.estado_produtivo(1) == "BOM_ATIVA"
    assert bom.detalhar(v1)["status"] == "ATIVA"
    assert anterior["numero_versao"] == 1
    assert Decimal(anterior["rendimento_saida"]) == 92
    with pytest.raises(ValueError, match="nova versão"):
        bom.remover_item(v1, anterior["itens"][0]["id"], 9)
    v2 = bom.criar_versao(
        1, CABECALHO | {"data_inicio_vigencia": "2026-02-01"}, 9, v1, clonar=True
    )
    clone = bom.detalhar(v2)
    assert clone["numero_versao"] == 2
    assert clone["itens"][0]["id"] != anterior["itens"][0]["id"]
    bom.salvar_item(v2, item(quantidade_base="8"), 9, clone["itens"][0]["id"])
    bom.publicar(v2, 9)
    with pytest.raises(ValueError, match="nova versão"):
        bom.atualizar_cabecalho(v2, CABECALHO | {"descricao": "Alterada"}, 9)
    bom.ativar(v2, 9, ativa_esperada=v1, usuario_nome="PCP", motivo="Estrutura homologada")
    historica = bom.detalhar(v1)
    assert historica["status"] == "INATIVA"
    assert historica["data_fim_vigencia"] == anterior["data_fim_vigencia"]
    assert historica["itens"] == anterior["itens"]
    ativa = bom.detalhar(v2)
    assert ativa["status"] == "ATIVA"
    assert ativa["produto_id"] == historica["produto_id"] == 1
    ultimo = ativa["historico"][0]
    assert ultimo["antes"]["versao"] == {"id": v1, "numero": 1}
    assert ultimo["depois"]["versao"] == {"id": v2, "numero": 2}
    assert ultimo["depois"]["motivo"] == "Estrutura homologada"
    with pytest.raises(ValueError, match="publicada"):
        bom.ativar(v1, 9, ativa_esperada=v2)
    vazia = bom.criar_versao(1, CABECALHO, 9, v2)
    assert bom.detalhar(vazia)["itens"] == []
    assert len(bom.listar()) == 3
    return v2


def test_versoes(ambiente):
    exercitar_versoes()


def exercitar_ciclos():
    for produto in (1, 2, 4):
        bom.definir_aquisicao(produto, True, False)
    a, b, d = (bom.criar_versao(produto, CABECALHO, 9) for produto in (1, 2, 4))
    with pytest.raises(ValueError, match="próprio"):
        bom.salvar_item(a, item("produto:1"), 9)
    bom.salvar_item(a, item("produto:2"), 9)
    with pytest.raises(ValueError, match="ciclo"):
        bom.salvar_item(b, item("produto:1"), 9)
    bom.salvar_item(b, item("produto:4", regra_calculo=bom.REGRAS[3]), 9)
    with pytest.raises(ValueError, match="ciclo"):
        bom.salvar_item(d, item("produto:1"), 9)
    assert bom.detalhar(d)["itens"] == []
    return d


def test_multinivel(ambiente):
    exercitar_ciclos()


def test_fluxo_e_permissoes_http(ambiente):
    from app import app

    client = app.test_client()
    base = "/engenharia-produtos/boms"
    assert client.get(base).status_code == 302
    with client.session_transaction() as sessao:
        sessao.update(usuario_id=9, perfil="pcp", nome="PCP")
    assert "BOMs" in client.get("/engenharia-produtos").text
    assert "Nenhuma BOM" in client.get(base).text
    client.post(f"{base}/aquisicao", data={"produto_id": 1, "fabricavel": "1"})
    editor = client.post(f"{base}/nova", data=CABECALHO | {"produto_id": 1}).location
    detalhe = editor.removesuffix("/editar")
    assert "Editar BOM" in client.get(editor).text
    assert "Unidade inválida" in client.post(
        editor, data=item(unidade="inv") | {"acao": "item"}
    ).text
    client.post(editor, data=item() | {"acao": "item"})
    client.post(editor, data=item("produto:3", sequencia="2") | {"acao": "item"})
    id1, id2 = [linha["id"] for linha in bom.detalhar(1)["itens"]]
    client.post(f"{editor}?item={id1}", data=item(quantidade_base="4") | {"acao": "item"})
    client.post(editor, data={"acao": "remover", "item_id": id2})
    assert "4.000000" in client.post(detalhe, data={"quantidade_planejada": 1}).text
    assert "Componente C" not in client.get(detalhe).text
    assert "Componente B" in client.get(detalhe).text
    client.post(f"{detalhe}/status", data={"acao": "publicar"})
    assert "Publicada" in client.get(detalhe).text
    assert client.get(editor).status_code == 409
    nova = f"{detalhe}/nova-versao"
    assert "Nova versão" in client.get(nova).text
    assert client.post(nova, data=CABECALHO | {"modelo": "clonar"}).status_code == 302
    assert len(bom.detalhar(2)["itens"]) == 1
    client.post(f"{detalhe}/status", data={"acao": "ativar"})
    assert "VERSÃO ATIVA EM PRODUÇÃO" in client.get(detalhe).text
    assert "Necessidades consolidadas" in client.post(detalhe, data={"quantidade_planejada": 1}).text
    client.post(f"{detalhe}/status", data={"acao": "inativar"})
    assert "Inativa" in client.get(detalhe).text
    with client.session_transaction() as sessao:
        sessao["perfil"] = "qualidade"
    assert client.get(base).status_code == 200
    assert client.post(nova, data=CABECALHO).status_code == 302
    assert client.post(editor, data=item() | {"acao": "item"}).status_code == 302
    assert len(bom.listar()) == 2


@pytest.fixture
def postgres(monkeypatch):
    url = os.getenv("FRIGODATTA_BOM_TEST_POSTGRES")
    if not url:
        pytest.skip("Configure FRIGODATTA_BOM_TEST_POSTGRES para o PostgreSQL descartável.")
    destino = urlsplit(url)
    if destino.hostname not in ("localhost", "127.0.0.1") or destino.path != "/frigo_bom_test":
        pytest.fail("O PostgreSQL da BOM deve usar frigo_bom_test em loopback.")
    from modules.engenharia_produtos import fundacao, repositories
    from modules.almoxarifado import services as almoxarifado

    schema = "bom_teste_" + uuid4().hex
    with psycopg2.connect(url) as conn:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE SCHEMA {schema}")
    try:
        monkeypatch.setenv("PGOPTIONS", f"-c search_path={schema}")
        for modulo in (database, connection, bom, fundacao, repositories, almoxarifado):
            monkeypatch.setattr(modulo, "DATABASE_URL", url)
        monkeypatch.setattr(connection, "_pool_postgres_habilitado", False)
        with database.transaction() as conn:
            conn.cursor().execute("CREATE TABLE ordens_producao (id SERIAL PRIMARY KEY)")
        repositories.criar_estrutura()
        fundacao.criar_estrutura()
        popular()
        yield
    finally:
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cursor:
                cursor.execute(f"DROP SCHEMA {schema} CASCADE")


def concorrer(*acoes):
    barreira = Barrier(len(acoes))

    def executar(acao):
        barreira.wait(timeout=5)
        try:
            return acao()
        except (ValueError, psycopg2.IntegrityError) as erro:
            return erro

    with ThreadPoolExecutor(max_workers=len(acoes)) as executor:
        return list(executor.map(executar, acoes))


def test_postgresql_migration_integridade_e_concorrencia(postgres):
    bom.migrar()
    bom.migrar(reverter=True)
    with database.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT to_regclass('bom') AS bom, count(*) AS produtos FROM skus")
        assert dict(cursor.fetchone()) == {"bom": None, "produtos": 4}
    bom.migrar()
    exercitar_versoes()
    with database.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT numeric_precision, numeric_scale FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'bom_item' AND column_name = 'quantidade_base'
        """)
        assert tuple(cursor.fetchone().values()) == (18, 6)
        cursor.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() AND tablename = 'bom_item'")
        assert {"ix_bom_item_produto", "ix_bom_item_insumo"} <= {
            linha["indexname"] for linha in cursor.fetchall()
        }

    resultado = bom.criar_versao(1, CABECALHO, 9)

    def inserir_invalido(componente):
        with database.transaction() as conn:
            conn.cursor().execute("""
                INSERT INTO bom_item (bom_id, componente_produto_id, sequencia,
                    classificacao, quantidade_base, unidade, regra_calculo)
                VALUES (%s, %s, 9, 'COMPONENTE', 1, 'Un', 'FIXO_POR_ORDEM')
            """, (resultado, componente))

    erros = concorrer(lambda: inserir_invalido(99999), lambda: inserir_invalido(None))
    assert {erro.pgcode for erro in erros} == {"23503", "23514"}
    bom.definir_aquisicao(4, True, True)
    versoes = concorrer(lambda: bom.criar_versao(4, CABECALHO, 9),
                        lambda: bom.criar_versao(4, CABECALHO, 9))
    assert {bom.detalhar(versao)["numero_versao"] for versao in versoes} == {1, 2}
    for versao in versoes:
        bom.salvar_item(versao, item("produto:3"), 9)
        bom.publicar(versao, 9)
    resultados = concorrer(*(lambda v=v: bom.ativar(v, 9, ativa_esperada=None) for v in versoes))
    assert sum(erro is None for erro in resultados) == 1
    assert any(isinstance(erro, ValueError) and "versão ativa mudou" in str(erro) for erro in resultados)
    publicada = next(v for v in versoes if bom.detalhar(v)["status"] == "PUBLICADA")

    def inserir_mesma_versao():
        with database.transaction() as conn:
            conn.cursor().execute("""
                INSERT INTO bom (produto_id, numero_versao, descricao, data_inicio_vigencia)
                VALUES (4, 3, 'Concorrência', '2027-01-01')
            """)

    duplicadas = concorrer(inserir_mesma_versao, inserir_mesma_versao)
    assert sum(erro is None for erro in duplicadas) == 1
    assert any(isinstance(erro, psycopg2.errors.UniqueViolation) for erro in duplicadas)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        with database.transaction() as conn:
            conn.cursor().execute("UPDATE bom SET status = 'ATIVA' WHERE id = %s", (publicada,))
    with pytest.raises(psycopg2.errors.CheckViolation):
        with database.transaction() as conn:
            conn.cursor().execute("UPDATE bom SET descricao = 'reescrita' WHERE id = %s", (publicada,))
    with pytest.raises(psycopg2.errors.CheckViolation):
        with database.transaction() as conn:
            conn.cursor().execute("DELETE FROM bom_item WHERE bom_id = %s", (publicada,))
    with database.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM bom WHERE produto_id = 4 AND status = 'ATIVA'")
        assert cursor.fetchone()["total"] == 1


def test_explosao_multinivel_perdas_conversao_e_consolidacao(ambiente):
    with database.transaction() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE skus SET unidade_venda = 'Un'")
        cur.execute("INSERT INTO skus (nome,codigo,unidade_venda) VALUES ('Ramo E','E','Un')")
    for produto in (1, 2, 4, 5):
        bom.definir_aquisicao(produto, True, True)
    a, b, d, e = (bom.criar_versao(produto, CABECALHO, 9) for produto in (1, 2, 4, 5))
    bom.salvar_item(a, item("produto:2", quantidade_base="2", perda_prevista_percentual="10"), 9)
    bom.salvar_item(a, item("produto:5", sequencia="2", quantidade_base="1"), 9)
    bom.salvar_item(b, item("produto:4", quantidade_base="3"), 9)
    bom.salvar_item(d, item("produto:3", quantidade_base="0.5", unidade="Kg",
                            perda_prevista_percentual="20"), 9)
    bom.salvar_item(e, item("produto:3", quantidade_base="1040", unidade="G"), 9)
    for versao in (a, b, d, e):
        bom.publicar(versao, 9)
    assert "incompleta" in bom.simular(a, 1)["erro"]
    with pytest.raises(ValueError, match="incompleta"):
        bom.ativar(a, 9, ativa_esperada=None)
    for versao in (d, b, e):
        bom.ativar(versao, 9, ativa_esperada=None)
    dois_niveis = bom.simular(b, 2)
    assert dois_niveis["consolidados"][0]["quantidade_total"] == Decimal("3.600000")
    resultado = bom.simular(a, 1)
    consolidado, = resultado["consolidados"]
    # 2 × 1,10 × 3 × 0,5 × 1,20 + 1040 g = 5 kg.
    assert consolidado["quantidade_total"] == Decimal("5.000000")
    assert consolidado["unidade"] == "Kg"
    itens = resultado["detalhados"]
    assert [v["nivel"] for v in itens] == [3, 2]
    assert [v["bom_id"] for v in itens[0]["versoes"]] == [a, b, d]
    assert len(consolidado["origens"]) == 2
    bom.ativar(a, 9, ativa_esperada=None)
    assert bom.estado_produtivo(1) == "BOM_ATIVA"


def test_vigencia_e_publicacao_futura(ambiente):
    bom.definir_aquisicao(1, True, True)
    inicio = (bom._hoje() + timedelta(days=5)).isoformat()
    futura = bom.criar_versao(1, CABECALHO | {"data_inicio_vigencia": inicio}, 9)
    bom.salvar_item(futura, item(), 9)
    bom.publicar(futura, 9)
    with pytest.raises(ValueError, match="fora da vigência"):
        bom.ativar(futura, 9, ativa_esperada=None)
    assert bom.detalhar(futura)["status"] == "PUBLICADA"
    bom.inativar(futura, 9)
    assert bom.estado_produtivo(1) == "LEGADO"


@pytest.mark.parametrize("motor", ["ambiente", "postgres"])
def test_rollback_atomicidade_e_historico(motor, request, monkeypatch):
    request.getfixturevalue(motor)
    bom.migrar()
    bom.definir_aquisicao(1, True, True)
    primeira = bom.criar_versao(1, CABECALHO, 9)
    bom.salvar_item(primeira, item(), 9)
    bom.publicar(primeira, 9)
    bom.ativar(primeira, 9, ativa_esperada=None)
    segunda = bom.criar_versao(1, CABECALHO, 9, primeira, clonar=True)
    bom.publicar(segunda, 9)

    def falhar(*args, **kwargs):
        raise RuntimeError("Auditoria indisponível")

    monkeypatch.setattr(bom, "registrar_historico_cursor", falhar)
    with pytest.raises(RuntimeError, match="Auditoria"):
        bom.ativar(segunda, 9, ativa_esperada=primeira)
    assert bom.detalhar(primeira)["status"] == "ATIVA"
    assert bom.detalhar(segunda)["status"] == "PUBLICADA"
    assert len(bom.detalhar(primeira)["historico"]) == 1


def test_upgrade_de_base_anterior_preserva_status_e_itens(ambiente):
    bom.migrar(reverter=True, somente_producao=True)
    with database.transaction() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO bom (produto_id, numero_versao, descricao, status, data_inicio_vigencia, ativa) "
                    "VALUES (1, 1, 'Anterior', 'PUBLICADA', '2026-01-01', TRUE)")
        cur.execute("INSERT INTO bom_item (bom_id, componente_produto_id, sequencia, classificacao, quantidade_base, unidade, regra_calculo) "
                    "VALUES (1, 2, 1, 'INSUMO', 3, 'Un', 'POR_UNIDADE_PRODUZIDA')")
    bom.migrar()
    anterior = bom.detalhar(1)
    assert anterior["status"] == "PUBLICADA"
    assert len(anterior["itens"]) == 1
    assert bom.estado_produtivo(1) == "EM_CONFIGURACAO"
    assert bom.simular(1, 2)["consolidados"][0]["quantidade_total"] == 6


def test_protecao_defensiva_da_explosao():
    versao = {
        "id": 1, "produto_id": 1, "produto": "Componente recursivo", "numero_versao": 1,
        "unidade_producao": "Un",
        "itens": [item() | {"componente": "O mesmo produto", "componente_produto_id": 1,
                           "componente_insumo_id": None}],
    }
    with pytest.raises(ValueError, match="Ciclo detectado"):
        bom.explodir(versao, 1, lambda linha: versao, lambda estrutura: None)


def test_postgresql_rollback_preserva_estados_quando_periodos_incompativeis(postgres):
    bom.migrar()
    segunda = exercitar_versoes()
    with pytest.raises(psycopg2.errors.ExclusionViolation):
        bom.migrar(reverter=True, somente_producao=True)
    assert bom.detalhar(segunda)["status"] == "ATIVA"
    assert bom.detalhar(segunda)["historico"][0]["depois"]["versao"]["id"] == segunda
