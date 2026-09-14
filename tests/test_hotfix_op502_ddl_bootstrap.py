"""DDL redundante de ordens_producao no bootstrap; executar isoladamente com PostgreSQL descartável.

Cobre a Etapa B do hotfix do 502/WORKER TIMEOUT em /op/<id>/editar (ver
output/hotfix-op97-502-auditoria-etapa-a.md). A Etapa A identificou que, a
cada novo worker Gunicorn, `inicializar_schema_aplicacao()` (app.py) reexecuta
cinco comandos ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS ... —
redundantes em produção, pois as colunas já são provisionadas pelas
migrations versionadas — e que, no PostgreSQL, cada um desses comandos exige
lock ACCESS EXCLUSIVE na tabela, o que pode enfileirar leituras concorrentes
(como a de /op/<id>/editar) atrás do DDL.

TestPostgresBootstrapSemDDLRedundante chama diretamente, contra um
PostgreSQL real e descartável, as três funções auditadas na Etapa A —
criar_tabelas_estoque_confiavel, criar_tabelas_operacoes_op,
criar_tabelas_correcoes_administrativas_op — e prova, pelo SQL efetivamente
executado, que nenhum ALTER TABLE ordens_producao roda mais (nem na primeira
chamada nem numa segunda simulando reinício de worker), que as migrations
existentes provisionam as colunas em um ambiente novo, e que as demais
tabelas/índices continuam sendo criados.

TestPostgresParceirosSemDDLRedundante cobre uma quarta função, descoberta
durante a implementação da Etapa B e fora do escopo original de "5 DDLs em 3
inicializadores": `criar_tabelas_parceiros()`
(modules/parceiros/services.py), que também executa
`ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS fornecedor_parceiro_id`
e, diferente das outras três, NÃO tem nenhuma guarda de processo — ela é
chamada a cada requisição por `listar_parceiros_elegiveis()` e
`obter_parceiro_por_papel()`, ambas usadas por `/op/<id>/editar` na branch
`main` (a que está em produção). Isso é mais grave do que o achado original
da Etapa A (que via o DDL só no boot do worker): aqui o DDL redundante
rodaria em TODA requisição à tela de edição de OP. A coluna já é provisionada
pela migration `database/20260909_p3_4_migracao_clientes_fornecedores_parceiros.sql`.
Ver a nota de divergência no relatório da Etapa B para mais contexto.

Não usa `app.py`/`inicializar_schema_aplicacao()` inteiros: outros módulos do
bootstrap completo (ex.: `criar_banco`, `criar_tabelas_expedicao`) têm
comportamento pré-existente e fora de escopo ao rodar contra um banco
totalmente vazio (ver nota em `_preparar_schema_minimo`), e reproduzi-los não
é necessário para provar o fix — ver critério de escopo no prompt da Etapa B,
item 16. O teste funcional de `/op/<id>/editar` (equivalente à OP 97, via
SQLite) vive em tests/test_hotfix_op502_editar_op_sqlite.py, em processo
próprio, para não misturar os dois backends de banco na mesma importação.
"""

from pathlib import Path
import os
import re
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ALTER_ORDENS_PRODUCAO = re.compile(r"ALTER\s+TABLE\s+ordens_producao", re.IGNORECASE)

MIGRATIONS_ORDENS_PRODUCAO = [
    ROOT / "database" / "20260724_marco_zero_estoque.sql",
    ROOT / "database" / "20260729_correcao_administrativa_op.sql",
    ROOT / "database" / "20260825_p0_2_estorno_reabertura_op.sql",
]

MIGRATION_PARCEIROS = ROOT / "database" / "20260909_p3_4_migracao_clientes_fornecedores_parceiros.sql"


def _sql_com_alter_ordens_producao(comandos):
    return [sql for sql in comandos if ALTER_ORDENS_PRODUCAO.search(str(sql))]


# ---------------------------------------------------------------------------
# Suíte PostgreSQL: executar isoladamente com PostgreSQL descartável.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REQUIRE_REAL_POSTGRESQL = os.getenv("REQUIRE_REAL_POSTGRESQL") == "1"
if not TEST_DATABASE_URL:
    if REQUIRE_REAL_POSTGRESQL:
        raise RuntimeError("PostgreSQL real é obrigatório para esta execução.")

pytestmark_pg = pytest.mark.skipif(
    not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente; suíte PostgreSQL-only"
)

if TEST_DATABASE_URL:
    # A aplicação lê DATABASE_URL no import. A URL nasce de TEST_DATABASE_URL
    # apenas neste subprocesso e nunca é persistida em configuração ou evidência.
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    import database.connection as conexao  # noqa: E402
    import modules.expedicao.estoque_service as estoque_mod  # noqa: E402
    import modules.producao.operacoes_op as operacoes_op_mod  # noqa: E402
    import modules.producao.correcoes_administrativas as correcoes_mod  # noqa: E402
    import modules.parceiros.services as parceiros_mod  # noqa: E402
    from database import q  # noqa: E402
else:
    conexao = estoque_mod = operacoes_op_mod = correcoes_mod = parceiros_mod = q = None


def _limpar_schema_publico():
    conn = conexao.get_connection()
    cursor = conn.cursor()
    cursor.execute("DROP SCHEMA public CASCADE")
    cursor.execute("CREATE SCHEMA public")
    conn.commit()
    conn.close()


def _preparar_schema_minimo():
    """Cria só o schema que as três funções auditadas efetivamente lêem/escrevem.

    Propositalmente não roda `app.py`/`inicializar_schema_aplicacao()` (que
    também executa `criar_banco`, `criar_tabelas_expedicao` e ~15 outras
    rotinas de outros módulos). Contra um PostgreSQL totalmente vazio, essas
    outras rotinas expõem um bug pré-existente e fora do escopo desta Etapa
    B — por exemplo, `criar_banco()` roda, na mesma transação,
    `CREATE TABLE IF NOT EXISTS usuarios (... perfil ...)` seguido de
    `ALTER TABLE usuarios ADD COLUMN perfil` (sem IF NOT EXISTS); em um banco
    vazio isso falha com "duplicate column" e o rollback desfaz também os
    CREATE TABLE recém-feitos na mesma transação. Isso nunca ocorre em
    produção real porque as tabelas já existem há anos antes dessas ALTERs
    redundantes. Reproduzir esse bootstrap completo aqui não testaria nosso
    fix e exigiria contornar um problema não relacionado; testamos as três
    funções diretamente, como o item 16 do prompt da Etapa B permite.
    """
    conn = conexao.get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE ordens_producao (
        id SERIAL PRIMARY KEY, data TEXT NOT NULL, status TEXT DEFAULT 'Aberta'
    )""")
    cursor.execute("CREATE TABLE pa_caixas (id SERIAL PRIMARY KEY)")
    cursor.execute("CREATE TABLE pa_caixa_composicao (id SERIAL PRIMARY KEY, caixa_id INTEGER, op_id INTEGER)")
    cursor.execute("""
    CREATE TABLE expedicoes (
        id SERIAL PRIMARY KEY, tipo_movimentacao TEXT, status TEXT, data TEXT
    )""")
    cursor.execute("CREATE TABLE expedicao_itens (id SERIAL PRIMARY KEY)")
    cursor.execute("CREATE TABLE embalagem_primaria_apontamentos (id SERIAL PRIMARY KEY)")
    cursor.execute("CREATE TABLE apontamentos_producao (id SERIAL PRIMARY KEY, op_id INTEGER)")
    # Tabelas adicionais exigidas só por criar_tabelas_parceiros() (ALTER em
    # apontamentos_mao_obra/clientes/fornecedores) e pela migration P3.4
    # (FK para parceiros(id), ALTER em pedidos_venda). Existem em produção
    # há muito tempo; aqui só precisam existir para o DDL rodar.
    cursor.execute("CREATE TABLE apontamentos_mao_obra (id SERIAL PRIMARY KEY, op_id INTEGER)")
    cursor.execute("CREATE TABLE clientes (id SERIAL PRIMARY KEY)")
    cursor.execute("CREATE TABLE fornecedores (id SERIAL PRIMARY KEY)")
    cursor.execute("CREATE TABLE pedidos_venda (id SERIAL PRIMARY KEY, cliente_id INTEGER, data_pedido TEXT)")
    # A "marco zero" de estoque (2026-07-24) já é fato consumado em produção:
    # pré-semear a linha evita reexecutar aqui um backfill histórico de
    # dados que não faz parte do escopo desta Etapa B (ver
    # criar_tabelas_estoque_confiavel, bloco `if not marco:`).
    cursor.execute("""
    CREATE TABLE estoque_marcos (
        id SERIAL PRIMARY KEY, tipo TEXT UNIQUE NOT NULL, referencia_data TEXT NOT NULL,
        fuso_horario TEXT NOT NULL, legacy_max_op_id INTEGER NOT NULL,
        ativado_por TEXT NOT NULL, ativado_em TIMESTAMP NOT NULL,
        status TEXT NOT NULL DEFAULT 'ATIVO'
    )""")
    cursor.execute(q("""
    INSERT INTO estoque_marcos (tipo, referencia_data, fuso_horario, legacy_max_op_id, ativado_por, ativado_em)
    VALUES ('MARCO_ZERO', '2026-07-24', 'America/Manaus', 0, 'seed-teste', '2026-07-24 00:00:00')
    """))
    conn.commit()
    conn.close()


def _aplicar_migrations_ordens_producao():
    conn = conexao.get_connection()
    cursor = conn.cursor()
    try:
        for caminho in MIGRATIONS_ORDENS_PRODUCAO:
            cursor.execute(caminho.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _colunas_de_ordens_producao():
    conn = conexao.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'ordens_producao'"
    )
    colunas = {linha["column_name"] for linha in cursor.fetchall()}
    conn.close()
    return colunas


def _resetar_guards_em_memoria():
    """Reseta os guards em memória, reproduzindo um processo worker novo."""
    estoque_mod._SCHEMA_ESTOQUE_CONFIAVEL_INICIALIZADO = False
    operacoes_op_mod._SCHEMA_INICIALIZADO = False


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente; suíte PostgreSQL-only")
class TestPostgresBootstrapSemDDLRedundante:
    def setup_method(self, _metodo):
        _limpar_schema_publico()
        _preparar_schema_minimo()
        _resetar_guards_em_memoria()

    def _rodar_tres_inicializadores(self, monkeypatch, capturar_em):
        # criar_tabelas_operacoes_op() também aciona, no início, os
        # inicializadores de estornos de embalagem e conferência de
        # embalagem (outros módulos, fora do escopo desta Etapa B). Eles não
        # tocam ordens_producao; neutralizamos apenas para manter o teste
        # focado nas três funções auditadas, sem depender do schema desses
        # módulos vizinhos.
        monkeypatch.setattr(operacoes_op_mod, "criar_tabelas_estornos_embalagem", lambda: None)
        import modules.expedicao.conferencia_embalagem as conferencia_mod
        monkeypatch.setattr(conferencia_mod, "criar_tabelas_conferencia_embalagem", lambda: None)

        original = conexao._registrar_sql

        def espiao(sql, duracao_ms):
            capturar_em.append(str(sql))
            return original(sql, duracao_ms)

        monkeypatch.setattr(conexao, "_registrar_sql", espiao)

        estoque_mod.criar_tabelas_estoque_confiavel()
        operacoes_op_mod.criar_tabelas_operacoes_op()
        correcoes_mod.criar_tabelas_correcoes_administrativas_op()

    def test_migrations_existentes_provisionam_colunas_em_ambiente_novo(self):
        antes = _colunas_de_ordens_producao()
        for coluna in (
            "estoque_classificacao", "estoque_marco_id",
            "versao_operacional", "bloqueada_administrativamente",
        ):
            assert coluna not in antes, f"{coluna} já existia antes da migration"

        _aplicar_migrations_ordens_producao()
        depois = _colunas_de_ordens_producao()
        for coluna in (
            "estoque_classificacao", "estoque_marco_id",
            "versao_operacional", "bloqueada_administrativamente",
        ):
            assert coluna in depois, f"Migration não provisionou {coluna}"

    def test_primeira_chamada_nao_executa_alter_table_ordens_producao(self, monkeypatch):
        _aplicar_migrations_ordens_producao()
        colunas_antes = _colunas_de_ordens_producao()

        sql_capturado = []
        self._rodar_tres_inicializadores(monkeypatch, sql_capturado)

        alters = _sql_com_alter_ordens_producao(sql_capturado)
        assert alters == [], f"Bootstrap executou ALTER TABLE ordens_producao: {alters}"
        assert _colunas_de_ordens_producao() == colunas_antes

        # Demais tabelas/estruturas dos três inicializadores continuam sendo criadas.
        sql_junto = " \n ".join(sql_capturado)
        for esperado in (
            "estoque_marcos", "estoque_eventos", "op_operacoes_auditoria",
            "op_encerramento_tentativas", "correcoes_administrativas_op",
            "tentativas_correcao_administrativa_op",
        ):
            assert esperado in sql_junto, f"{esperado} deixou de ser criada no boot"

    def test_reinicio_de_worker_e_idempotente_e_nao_reexecuta_ddl(self, monkeypatch):
        _aplicar_migrations_ordens_producao()

        primeira_rodada = []
        self._rodar_tres_inicializadores(monkeypatch, primeira_rodada)
        assert _sql_com_alter_ordens_producao(primeira_rodada) == []

        colunas_antes = _colunas_de_ordens_producao()

        # Simula um novo worker Gunicorn: os guards em memória são resetados,
        # mas o schema (já migrado) permanece o mesmo.
        _resetar_guards_em_memoria()
        segunda_rodada = []
        self._rodar_tres_inicializadores(monkeypatch, segunda_rodada)

        alters = _sql_com_alter_ordens_producao(segunda_rodada)
        assert alters == [], f"Reinício de worker executou ALTER TABLE ordens_producao: {alters}"
        assert _colunas_de_ordens_producao() == colunas_antes


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL ausente; suíte PostgreSQL-only")
class TestPostgresParceirosSemDDLRedundante:
    """Cobre a quarta função (achado da Etapa B, fora do escopo original — ver
    docstring do módulo): `criar_tabelas_parceiros()`, que não tem guarda de
    processo e é chamada a cada requisição a /op/<id>/editar via
    `listar_parceiros_elegiveis()`/`obter_parceiro_por_papel()`.
    """

    def setup_method(self, _metodo):
        _limpar_schema_publico()
        _preparar_schema_minimo()

    def test_migration_p3_4_provisiona_coluna_em_ambiente_novo(self):
        # A migration referencia parceiros(id) via FK; criamos um stub
        # independente da função Python para provar que a migration por si
        # só, sem rodar criar_tabelas_parceiros(), já provisiona a coluna.
        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE parceiros (id SERIAL PRIMARY KEY)")
        conn.commit()
        conn.close()

        antes = _colunas_de_ordens_producao()
        assert "fornecedor_parceiro_id" not in antes

        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute(MIGRATION_PARCEIROS.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()

        depois = _colunas_de_ordens_producao()
        assert "fornecedor_parceiro_id" in depois

    def test_chamadas_repetidas_nunca_executam_alter_table_ordens_producao(self, monkeypatch):
        """criar_tabelas_parceiros() não tem guarda — simula 3 requisições
        seguidas a /op/<id>/editar (cada uma chamando a função de novo) e
        confirma que nenhuma executa ALTER TABLE ordens_producao."""
        # Estado real de produção: as migrations já rodaram, incluindo a
        # P3.4. Pré-criamos parceiros com o schema completo que
        # criar_tabelas_parceiros() também define, para que a chamada da
        # função abaixo seja um no-op de verdade (senão CREATE TABLE
        # IF NOT EXISTS parceiros(...) tornaria o teste inconclusivo).
        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE parceiros (
            id SERIAL PRIMARY KEY, uuid TEXT NOT NULL UNIQUE, tipo_pessoa TEXT NOT NULL,
            razao_social TEXT NOT NULL, nome_fantasia TEXT, documento TEXT,
            telefone TEXT, email TEXT, endereco TEXT, complemento TEXT,
            bairro TEXT, cidade TEXT, uf TEXT, cep TEXT, observacoes TEXT,
            status TEXT NOT NULL DEFAULT 'Ativo', criado_por TEXT NOT NULL,
            atualizado_por TEXT NOT NULL, criado_em TIMESTAMP NOT NULL,
            atualizado_em TIMESTAMP NOT NULL
        )""")
        conn.commit()
        conn.close()

        _aplicar_migrations_ordens_producao()
        conn = conexao.get_connection()
        cursor = conn.cursor()
        cursor.execute(MIGRATION_PARCEIROS.read_text(encoding="utf-8"))
        conn.commit()
        conn.close()

        assert "fornecedor_parceiro_id" in _colunas_de_ordens_producao()

        sql_capturado = []
        original = conexao._registrar_sql

        def espiao(sql, duracao_ms):
            sql_capturado.append(str(sql))
            return original(sql, duracao_ms)

        monkeypatch.setattr(conexao, "_registrar_sql", espiao)

        for _rodada in range(3):  # simula 3 requisições seguidas
            parceiros_mod.criar_tabelas_parceiros()

        alters = _sql_com_alter_ordens_producao(sql_capturado)
        assert alters == [], (
            f"criar_tabelas_parceiros() executou ALTER TABLE ordens_producao: {alters}"
        )

