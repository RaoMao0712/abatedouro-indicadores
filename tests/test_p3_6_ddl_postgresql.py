"""P3.6, Etapa C item 6: prova, contra PostgreSQL real e descartável, que a
coluna `almoxarifado_requisicoes.ordem_servico_id` nunca é criada/alterada
em runtime — só pela migration versionada. Executar isoladamente (mesmo
padrão de tests/test_romaneio_concorrencia_postgresql.py e
tests/test_hotfix_op502_ddl_bootstrap.py, herdado do hotfix do 502).
"""

from pathlib import Path
import os
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALTER_ORDEM_SERVICO_ID = re.compile(
    r"ALTER\s+TABLE\s+almoxarifado_requisicoes[^;]*ordem_servico_id", re.IGNORECASE
)

MIGRATION = ROOT / "database" / "20260914_p3_6_os_requisicao_almoxarifado.sql"
ROLLBACK = ROOT / "database" / "20260914_p3_6_os_requisicao_almoxarifado_rollback.sql"

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REQUIRE_REAL_POSTGRESQL = os.getenv("REQUIRE_REAL_POSTGRESQL") == "1"
if not TEST_DATABASE_URL:
    if REQUIRE_REAL_POSTGRESQL:
        raise RuntimeError("PostgreSQL real é obrigatório para esta execução.")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente; suíte PostgreSQL-only"
)

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    import database.connection as conexao  # noqa: E402
    import modules.almoxarifado.requisicoes as requisicoes_mod  # noqa: E402
    from database import q  # noqa: E402
else:
    conexao = requisicoes_mod = q = None


def _limpar_schema_publico():
    conn = conexao.get_connection()
    cursor = conn.cursor()
    cursor.execute("DROP SCHEMA public CASCADE")
    cursor.execute("CREATE SCHEMA public")
    conn.commit()
    conn.close()


def _colunas_de(tabela):
    conn = conexao.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (tabela,)
    )
    colunas = {linha["column_name"] for linha in cursor.fetchall()}
    conn.close()
    return colunas


def _indices_de(tabela):
    conn = conexao.get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT indexname FROM pg_indexes WHERE tablename = %s", (tabela,))
    indices = {linha["indexname"] for linha in cursor.fetchall()}
    conn.close()
    return indices


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente; suíte PostgreSQL-only")
class TestP36MigrationSemDDLRuntime:
    def setup_method(self, _metodo):
        _limpar_schema_publico()

    def test_migration_e_a_unica_fonte_da_coluna_em_ambiente_novo(self):
        """Sem rodar nenhum código Python de bootstrap: só a migration crua."""
        conn = conexao.get_connection()
        cursor = conn.cursor()
        # Tabela minima para a migration poder rodar (parceiros/pedidos_venda
        # nao sao tocados por esta migration especifica).
        cursor.execute("CREATE TABLE almoxarifado_requisicoes (id SERIAL PRIMARY KEY)")
        conn.commit()
        conn.close()

        antes = _colunas_de("almoxarifado_requisicoes")
        assert "ordem_servico_id" not in antes

        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()

        depois = _colunas_de("almoxarifado_requisicoes")
        assert "ordem_servico_id" in depois
        assert "idx_almox_req_ordem_servico" in _indices_de("almoxarifado_requisicoes")

    def test_rollback_remove_coluna_e_indice_sem_tocar_no_resto(self):
        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE almoxarifado_requisicoes (id SERIAL PRIMARY KEY, numero TEXT)")
        conn.commit()
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        assert "ordem_servico_id" in _colunas_de("almoxarifado_requisicoes")

        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute(ROLLBACK.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()

        colunas = _colunas_de("almoxarifado_requisicoes")
        assert "ordem_servico_id" not in colunas
        assert "numero" in colunas  # nada mais foi tocado
        assert "idx_almox_req_ordem_servico" not in _indices_de("almoxarifado_requisicoes")

    def test_criar_tabelas_requisicoes_nunca_altera_ordem_servico_id_em_postgres(self, monkeypatch):
        """O ponto central do item 6: com DATABASE_URL setado, a função de
        bootstrap runtime (chamada em toda rota do módulo) jamais tenta
        ALTER TABLE ... ordem_servico_id — nem no primeiro boot, nem
        repetido (simulando reinício de worker), com ou sem a migration já
        aplicada."""
        # Schema minimo que criar_tabelas_requisicoes_almoxarifado() precisa
        # tocar (via criar_tabelas_estoque_almoxarifado + ALTERs proprios).
        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE almoxarifado_insumos (id SERIAL PRIMARY KEY, ativo TEXT, categoria TEXT)")
        cursor.execute("CREATE TABLE almoxarifado_movimentacoes (id SERIAL PRIMARY KEY)")
        conn.commit()
        conn.close()

        sql_capturado = []
        original = conexao._registrar_sql

        def espiao(sql, duracao_ms):
            sql_capturado.append(str(sql))
            return original(sql, duracao_ms)

        monkeypatch.setattr(conexao, "_registrar_sql", espiao)

        for _rodada in range(3):  # simula 3 boots/requisicoes seguidas
            # Etapa C (correcao de performance): criar_tabelas_requisicoes_
            # almoxarifado() ganhou guarda de processo para nao repetir seu
            # bootstrap a cada chamada dentro do mesmo worker. Para de fato
            # simular 3 boots distintos (e nao 1 boot real + 2 no-ops), a
            # guarda e rearmada a cada rodada — exatamente o que um novo
            # processo faria.
            monkeypatch.setattr(requisicoes_mod, "_SCHEMA_REQUISICOES_INICIALIZADO", False)
            requisicoes_mod.criar_tabelas_requisicoes_almoxarifado()

        alters = [sql for sql in sql_capturado if ALTER_ORDEM_SERVICO_ID.search(sql)]
        assert alters == [], f"criar_tabelas_requisicoes_almoxarifado() alterou ordem_servico_id em Postgres: {alters}"

        # A migration, aplicada por fora, continua sendo quem prove a coluna.
        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute(MIGRATION.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()
        assert "ordem_servico_id" in _colunas_de("almoxarifado_requisicoes")

        # Repetir apos a coluna existir tambem nao gera ALTER (regressao dupla).
        sql_capturado.clear()
        monkeypatch.setattr(requisicoes_mod, "_SCHEMA_REQUISICOES_INICIALIZADO", False)
        requisicoes_mod.criar_tabelas_requisicoes_almoxarifado()
        alters_pos_migration = [sql for sql in sql_capturado if ALTER_ORDEM_SERVICO_ID.search(sql)]
        assert alters_pos_migration == []

        # E dentro do MESMO boot (guarda ainda armada), a 2a chamada nao
        # deve nem tentar tocar o schema de novo — e o ponto central da
        # correcao de performance da Etapa C.
        sql_capturado.clear()
        requisicoes_mod.criar_tabelas_requisicoes_almoxarifado()
        assert sql_capturado == [], (
            "2a chamada no mesmo processo deveria ser no-op (guarda de "
            f"processo), mas executou SQL: {sql_capturado}"
        )

    def test_consultas_de_requisicao_da_os_sao_somente_leitura_em_postgres(self, monkeypatch):
        """Item 11 da correcao de performance: listar_requisicoes_por_ordem_
        servico() e listar_requisicoes_vinculaveis() (as duas consultas que
        o detalhe da OS aciona) nao devem emitir ALTER TABLE / CREATE INDEX
        em hipotese alguma contra PostgreSQL real — nem no processo "frio"
        (sem a guarda de criar_tabelas_requisicoes_almoxarifado() jamais
        armada), pois elas pararam de chamar essa funcao. O teste monta o
        schema minimo por fora (como o boot real da aplicacao faria via
        inicializar_schema_aplicacao() em app.py) e so entao mede as duas
        consultas isoladamente."""
        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute(MIGRATION.read_text(encoding="utf-8").replace(
            "ALTER TABLE almoxarifado_requisicoes",
            "CREATE TABLE IF NOT EXISTS almoxarifado_requisicoes "
            "(id SERIAL PRIMARY KEY, status TEXT);\n"
            "ALTER TABLE almoxarifado_requisicoes",
        ))
        conn.commit()
        conn.close()
        assert "ordem_servico_id" in _colunas_de("almoxarifado_requisicoes")

        sql_capturado = []
        original = conexao._registrar_sql

        def espiao(sql, duracao_ms):
            sql_capturado.append(str(sql))
            return original(sql, duracao_ms)

        monkeypatch.setattr(conexao, "_registrar_sql", espiao)

        resultado_vinculaveis = requisicoes_mod.listar_requisicoes_vinculaveis()
        resultado_desdobramentos = requisicoes_mod.listar_requisicoes_por_ordem_servico(1)

        assert resultado_vinculaveis == []
        assert resultado_desdobramentos == []
        ddl = [
            sql for sql in sql_capturado
            if re.search(r"\b(ALTER\s+TABLE|CREATE\s+INDEX|CREATE\s+TABLE)\b", sql, re.IGNORECASE)
        ]
        assert ddl == [], (
            "listar_requisicoes_vinculaveis()/listar_requisicoes_por_ordem_"
            f"servico() emitiram DDL: {ddl}"
        )
        assert all(
            re.match(r"^\s*SELECT\b", sql, re.IGNORECASE) for sql in sql_capturado
        ), f"esperado apenas SELECT, capturado: {sql_capturado}"
