"""Concorrência real do romaneio; executar isoladamente com PostgreSQL descartável."""

from contextlib import contextmanager
import os
import threading
import time

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
REQUIRE_REAL_POSTGRESQL = os.getenv("REQUIRE_REAL_POSTGRESQL") == "1"
if not TEST_DATABASE_URL:
    if REQUIRE_REAL_POSTGRESQL:
        raise RuntimeError("PostgreSQL real é obrigatório para esta execução.")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL ausente; testes PostgreSQL-only",
)

# A aplicação lê DATABASE_URL no import. A URL nasce de TEST_DATABASE_URL apenas
# neste subprocesso e nunca é persistida em configuração ou evidência.
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
    import modules.expedicao.estoque_service as estoque  # noqa: E402
    import modules.pedidos_venda.services as pedidos  # noqa: E402
else:
    estoque = pedidos = None


DDL = """
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
CREATE TABLE expedicoes (
    id SERIAL PRIMARY KEY, numero_romaneio TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'Aberto', tipo_movimentacao TEXT NOT NULL
);
CREATE TABLE pa_caixas (
    id SERIAL PRIMARY KEY, codigo_caixa TEXT UNIQUE NOT NULL, sku TEXT NOT NULL,
    estoque_operacional INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'Em estoque',
    condicao TEXT NOT NULL DEFAULT 'CONFORME', disponibilidade TEXT NOT NULL DEFAULT 'DISPONIVEL',
    unidade_estoque TEXT NOT NULL DEFAULT 'PACOTE', galinhas_por_pacote INTEGER,
    quantidade_pacotes INTEGER, quantidade_galinhas INTEGER,
    quantidade_pacotes_reservados INTEGER NOT NULL DEFAULT 0,
    quantidade_bandejas INTEGER DEFAULT 0, peso_liquido NUMERIC,
    local_estoque_id INTEGER, reservado_expedicao_id INTEGER,
    apresentacao TEXT, peso_bruto NUMERIC, peso_tara NUMERIC
);
CREATE TABLE pa_caixa_composicao (
    id SERIAL PRIMARY KEY, caixa_id INTEGER NOT NULL, op_id INTEGER NOT NULL
);
CREATE TABLE expedicao_itens (
    id SERIAL PRIMARY KEY, expedicao_id INTEGER NOT NULL, caixa_id INTEGER NOT NULL,
    op_id INTEGER, sku TEXT NOT NULL, quantidade_unidades NUMERIC DEFAULT 0,
    quantidade_kg NUMERIC, situacao_anterior TEXT, condicao_anterior TEXT,
    local_anterior_id INTEGER, unidade_estoque TEXT, apresentacao TEXT,
    galinhas_por_pacote INTEGER, quantidade_pacotes INTEGER,
    quantidade_galinhas INTEGER, peso_bruto NUMERIC, peso_tara NUMERIC,
    lote TEXT, ativo INTEGER NOT NULL DEFAULT 1, removido_em TEXT,
    removido_por TEXT, motivo_remocao TEXT
);
CREATE TABLE estoque_eventos (
    id SERIAL PRIMARY KEY, caixa_id INTEGER, expedicao_id INTEGER, acao TEXT NOT NULL,
    situacao_anterior TEXT, situacao_nova TEXT, condicao_anterior TEXT,
    condicao_nova TEXT, quantidade NUMERIC, peso NUMERIC, justificativa TEXT,
    observacao TEXT, usuario TEXT, perfil TEXT, criado_em TEXT,
    idempotency_key TEXT UNIQUE
);
"""


def conectar():
    return psycopg2.connect(TEST_DATABASE_URL, cursor_factory=RealDictCursor)


class Hook:
    def __init__(self, trecho, *, falhar=False, ocorrencia=1):
        self.trecho = " ".join(trecho.upper().split())
        self.falhar = falhar
        self.ocorrencia = ocorrencia
        self.encontradas = 0
        self.atingido = threading.Event()
        self.liberar = threading.Event()
        self.usado = False

    def depois(self, sql):
        normalizado = " ".join(str(sql).upper().split())
        if self.usado or self.trecho not in normalizado:
            return
        self.encontradas += 1
        if self.encontradas < self.ocorrencia:
            return
        self.usado = True
        self.atingido.set()
        if self.falhar:
            raise RuntimeError("falha PostgreSQL controlada")
        if not self.liberar.wait(10):
            raise TimeoutError("barreira de teste não foi liberada")


class Hooks:
    def __init__(self, *hooks):
        self.hooks = hooks

    def depois(self, sql):
        for hook in self.hooks:
            hook.depois(sql)


class CursorProxy:
    def __init__(self, cursor, hook):
        self._cursor = cursor
        self._hook = hook

    def execute(self, sql, parametros=None):
        resultado = self._cursor.execute(sql, parametros)
        if self._hook:
            self._hook.depois(sql)
        return resultado

    def __getattr__(self, nome):
        return getattr(self._cursor, nome)


class ConexaoProxy:
    def __init__(self, conexao, hook):
        self._conexao = conexao
        self._hook = hook

    def cursor(self):
        return CursorProxy(self._conexao.cursor(), self._hook)

    def __getattr__(self, nome):
        return getattr(self._conexao, nome)


@pytest.fixture(scope="module", autouse=True)
def schema_postgresql():
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute(DDL)
    yield


@pytest.fixture
def ambiente(monkeypatch):
    hooks = {}
    pids = {}
    pids_prontos = {}

    @contextmanager
    def transacao_independente():
        conn = conectar()
        nome = threading.current_thread().name
        try:
            conn.set_session(isolation_level="READ COMMITTED", autocommit=False)
            cursor = conn.cursor()
            cursor.execute("SET LOCAL lock_timeout = '8s'")
            cursor.execute("SET LOCAL statement_timeout = '15s'")
            cursor.execute("SELECT pg_backend_pid() AS pid")
            pids[nome] = int(cursor.fetchone()["pid"])
            pids_prontos.setdefault(nome, threading.Event()).set()
            yield ConexaoProxy(conn, hooks.get(nome))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(estoque, "transaction", transacao_independente)
    monkeypatch.setattr(estoque, "criar_tabelas_estoque_confiavel", lambda: None)
    monkeypatch.setattr(pedidos, "vincular_item_reservado_cursor", lambda *args: None)
    return {"hooks": hooks, "pids": pids, "pids_prontos": pids_prontos}


def limpar_e_criar(*, inicial=80, total=240, dois_itens=False):
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE estoque_eventos, expedicao_itens, pa_caixa_composicao, pa_caixas, expedicoes RESTART IDENTITY")
            cursor.execute("INSERT INTO expedicoes(numero_romaneio,status,tipo_movimentacao) VALUES ('R1','Aberto','TRANSFERENCIA') RETURNING id")
            expedicao_id = int(cursor.fetchone()["id"])
            quantidades = [total, total] if dois_itens else [total]
            caixas = []
            for indice, quantidade in enumerate(quantidades, 1):
                cursor.execute("""
                INSERT INTO pa_caixas(
                    codigo_caixa,sku,galinhas_por_pacote,quantidade_pacotes,
                    quantidade_galinhas,apresentacao,local_estoque_id
                ) VALUES (%s,'Produto configurado',1,%s,%s,'V1',1) RETURNING id
                """, (f"GI-{indice}", quantidade, quantidade))
                caixa_id = int(cursor.fetchone()["id"])
                caixas.append(caixa_id)
                cursor.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id) VALUES (%s,88)", (caixa_id,))
    for caixa_id in caixas:
        estoque.atualizar_reserva_quantitativa(expedicao_id, 88, caixa_id, inicial, 0)
    return expedicao_id, caixas


def estado(expedicao_id, op_id=88):
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COALESCE(SUM(quantidade_pacotes_reservados),0) AS reservado, COALESCE(SUM(quantidade_pacotes),0) AS fisico FROM pa_caixas")
            saldo = cursor.fetchone()
            cursor.execute("""
            SELECT COALESCE(SUM(quantidade_pacotes),0) AS itens, COUNT(*) AS ativos
            FROM expedicao_itens WHERE expedicao_id=%s AND op_id=%s AND COALESCE(ativo,1)=1
            """, (expedicao_id, op_id))
            itens = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) AS total FROM estoque_eventos WHERE acao='REMOCAO_RESERVA'")
            eventos = int(cursor.fetchone()["total"])
    return {
        "reservado": int(saldo["reservado"]), "fisico": int(saldo["fisico"]),
        "itens": int(itens["itens"]), "ativos": int(itens["ativos"]),
        "eventos_remocao": eventos,
    }


def executar_thread(nome, funcao, erros, retornos):
    def alvo():
        try:
            retornos[nome] = funcao()
        except Exception as erro:  # resultado concorrente é verificado pelo chamador
            erros[nome] = erro
    thread = threading.Thread(name=nome, target=alvo)
    thread.start()
    return thread


def aguardar_lock(pid):
    limite = time.monotonic() + 8
    while time.monotonic() < limite:
        with conectar() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s", (pid,))
                linha = cursor.fetchone()
        if linha and linha["wait_event_type"] == "Lock":
            return True
        time.sleep(0.02)
    return False


def concorrencia(ambiente, primeira, segunda, trecho_primeira="SELECT * FROM EXPEDICOES"):
    erros, retornos = {}, {}
    hook = Hook(trecho_primeira)
    ambiente["hooks"]["primeira"] = hook
    t1 = executar_thread("primeira", primeira, erros, retornos)
    assert hook.atingido.wait(5)
    t2 = executar_thread("segunda", segunda, erros, retornos)
    assert ambiente["pids_prontos"].setdefault("segunda", threading.Event()).wait(5)
    assert ambiente["pids"]["primeira"] != ambiente["pids"]["segunda"]
    assert aguardar_lock(ambiente["pids"]["segunda"]), "segunda sessão não aguardou row lock"
    hook.liberar.set()
    t1.join(10)
    t2.join(10)
    assert not t1.is_alive() and not t2.is_alive()
    return erros, retornos


def assert_invariante_zero(expedicao_id, eventos=1):
    atual = estado(expedicao_id)
    assert atual["reservado"] == atual["itens"] == atual["ativos"] == 0
    assert atual["fisico"] == 240
    assert atual["eventos_remocao"] == eventos


def test_for_update_bloqueia_entre_backends_reais(ambiente):
    expedicao_id, _ = limpar_e_criar()
    a, b = conectar(), conectar()
    try:
        ca, cb = a.cursor(), b.cursor()
        ca.execute("SELECT pg_backend_pid() AS pid")
        pid_a = int(ca.fetchone()["pid"])
        cb.execute("SELECT pg_backend_pid() AS pid")
        pid_b = int(cb.fetchone()["pid"])
        assert pid_a != pid_b
        ca.execute("SELECT id FROM expedicoes WHERE id=%s FOR UPDATE", (expedicao_id,))
        terminou = threading.Event()

        def alterar():
            cb.execute("UPDATE expedicoes SET status=status WHERE id=%s", (expedicao_id,))
            b.commit()
            terminou.set()

        thread = threading.Thread(target=alterar)
        thread.start()
        assert aguardar_lock(pid_b)
        assert not terminou.is_set()
        a.commit()
        thread.join(5)
        assert terminou.is_set()
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("repeticao", range(20))
def test_edicao_primeiro_remove_quantidade_recarregada(ambiente, repeticao):
    expedicao_id, caixas = limpar_e_criar()
    erros, _ = concorrencia(
        ambiente,
        lambda: estoque.atualizar_reserva_quantitativa(expedicao_id, 88, caixas[0], 100, 80),
        lambda: estoque.remover_itens_reservados_op(expedicao_id, 88),
    )
    assert erros == {}
    assert_invariante_zero(expedicao_id)


@pytest.mark.parametrize("repeticao", range(20))
def test_remocao_primeiro_impede_recriacao(ambiente, repeticao):
    expedicao_id, caixas = limpar_e_criar()
    erros, _ = concorrencia(
        ambiente,
        lambda: estoque.remover_itens_reservados_op(expedicao_id, 88),
        lambda: estoque.atualizar_reserva_quantitativa(expedicao_id, 88, caixas[0], 100, 80),
    )
    assert "segunda" in erros
    assert "alterada ou removida" in str(erros["segunda"])
    assert_invariante_zero(expedicao_id)


@pytest.mark.parametrize("repeticao", range(20))
def test_duas_remocoes_sao_idempotentes(ambiente, repeticao):
    expedicao_id, _ = limpar_e_criar()
    erros, retornos = concorrencia(
        ambiente,
        lambda: estoque.remover_itens_reservados_op(expedicao_id, 88),
        lambda: estoque.remover_itens_reservados_op(expedicao_id, 88),
    )
    assert erros == {}
    assert sorted(map(len, retornos.values())) == [0, 1]
    assert_invariante_zero(expedicao_id)


@pytest.mark.parametrize("edicao_primeiro", [True, False])
@pytest.mark.parametrize("repeticao", range(20))
def test_edicao_para_baixo_contra_remocao(ambiente, repeticao, edicao_primeiro):
    expedicao_id, caixas = limpar_e_criar(inicial=100)
    editar = lambda: estoque.atualizar_reserva_quantitativa(expedicao_id, 88, caixas[0], 60, 100)
    remover = lambda: estoque.remover_itens_reservados_op(expedicao_id, 88)
    erros, _ = concorrencia(
        ambiente, editar if edicao_primeiro else remover,
        remover if edicao_primeiro else editar,
    )
    if edicao_primeiro:
        assert erros == {}
    else:
        assert "segunda" in erros and "alterada ou removida" in str(erros["segunda"])
    assert_invariante_zero(expedicao_id)


@pytest.mark.parametrize("repeticao", range(20))
def test_remocao_individual_contra_integral(ambiente, repeticao):
    expedicao_id, caixas = limpar_e_criar()
    erros, _ = concorrencia(
        ambiente,
        lambda: estoque.remover_item_reservado(expedicao_id, caixas[0], 88),
        lambda: estoque.remover_itens_reservados_op(expedicao_id, 88),
    )
    assert erros == {}
    assert_invariante_zero(expedicao_id)


def test_multiplos_itens_ordem_deterministica_e_rollback(ambiente):
    expedicao_id, caixas = limpar_e_criar(dois_itens=True)
    assert caixas == sorted(caixas)
    estoque.remover_itens_reservados_op(expedicao_id, 88)
    final = estado(expedicao_id)
    assert final["reservado"] == final["itens"] == 0
    assert final["fisico"] == 480 and final["eventos_remocao"] == 2

    for trecho in (
        "UPDATE PA_CAIXAS",
        "DELETE FROM EXPEDICAO_ITENS",
        "INSERT INTO ESTOQUE_EVENTOS",
    ):
        expedicao_id, _ = limpar_e_criar()
        ambiente["hooks"][threading.current_thread().name] = Hook(trecho, falhar=True)
        with pytest.raises(RuntimeError, match="controlada"):
            estoque.remover_itens_reservados_op(expedicao_id, 88)
        assert estado(expedicao_id)["reservado"] == estado(expedicao_id)["itens"] == 80
        ambiente["hooks"].clear()

    expedicao_id, _ = limpar_e_criar(dois_itens=True)
    ambiente["hooks"][threading.current_thread().name] = Hook(
        "UPDATE PA_CAIXAS", falhar=True, ocorrencia=2
    )
    with pytest.raises(RuntimeError, match="controlada"):
        estoque.remover_itens_reservados_op(expedicao_id, 88)
    depois = estado(expedicao_id)
    assert depois["reservado"] == depois["itens"] == 160
    assert depois["ativos"] == 2 and depois["eventos_remocao"] == 0


@pytest.mark.parametrize("repeticao", range(20))
def test_edicao_de_um_item_contra_remocao_de_op_com_multiplos_itens(ambiente, repeticao):
    expedicao_id, caixas = limpar_e_criar(dois_itens=True)
    erros, _ = concorrencia(
        ambiente,
        lambda: estoque.atualizar_reserva_quantitativa(expedicao_id, 88, caixas[0], 100, 80),
        lambda: estoque.remover_itens_reservados_op(expedicao_id, 88),
    )
    assert erros == {}
    final = estado(expedicao_id)
    assert final["reservado"] == final["itens"] == final["ativos"] == 0
    assert final["fisico"] == 480 and final["eventos_remocao"] == 2


def test_rollback_da_detentora_libera_operacao_que_aguardava(ambiente):
    expedicao_id, caixas = limpar_e_criar()
    pausa = Hook("SELECT * FROM EXPEDICOES")
    falha = Hook("UPDATE PA_CAIXAS", falhar=True)
    ambiente["hooks"]["primeira"] = Hooks(pausa, falha)
    erros, retornos = {}, {}
    primeira = executar_thread(
        "primeira",
        lambda: estoque.remover_itens_reservados_op(expedicao_id, 88),
        erros, retornos,
    )
    assert pausa.atingido.wait(5)
    segunda = executar_thread(
        "segunda",
        lambda: estoque.atualizar_reserva_quantitativa(expedicao_id, 88, caixas[0], 100, 80),
        erros, retornos,
    )
    assert ambiente["pids_prontos"].setdefault("segunda", threading.Event()).wait(5)
    assert aguardar_lock(ambiente["pids"]["segunda"])
    pausa.liberar.set()
    primeira.join(10)
    segunda.join(10)
    assert "primeira" in erros and "segunda" not in erros
    final = estado(expedicao_id)
    assert final["reservado"] == final["itens"] == 100
    assert final["ativos"] == 1 and final["eventos_remocao"] == 0


def test_multiplas_ops_e_fluxo_misto_preservados(ambiente):
    expedicao_id, caixas_88 = limpar_e_criar()
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
            INSERT INTO pa_caixas(codigo_caixa,sku,galinhas_por_pacote,quantidade_pacotes,
                quantidade_galinhas,apresentacao,local_estoque_id)
            VALUES ('GI-89','Produto configurado',1,100,100,'V1',1) RETURNING id
            """)
            saldo_89 = int(cursor.fetchone()["id"])
            cursor.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id) VALUES (%s,89)", (saldo_89,))
            cursor.execute("""
            INSERT INTO pa_caixas(codigo_caixa,sku,unidade_estoque,quantidade_bandejas,
                peso_liquido,apresentacao,local_estoque_id)
            VALUES ('CX-83','Cortada','CAIXA',12,2.5,'Caixa',1) RETURNING id
            """)
            caixa_83 = int(cursor.fetchone()["id"])
            cursor.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id) VALUES (%s,83)", (caixa_83,))
    estoque.atualizar_reserva_quantitativa(expedicao_id, 89, saldo_89, 40, 0)
    # Reserva física sintética para verificar que a remoção da OP 88 não cruza origens.
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE pa_caixas SET disponibilidade='RESERVADO', reservado_expedicao_id=%s WHERE id=%s", (expedicao_id, caixa_83))
            cursor.execute("""
            INSERT INTO expedicao_itens(expedicao_id,caixa_id,op_id,sku,quantidade_unidades,
                situacao_anterior,condicao_anterior,unidade_estoque,ativo)
            VALUES (%s,%s,83,'Cortada',12,'DISPONIVEL','CONFORME','CAIXA',1)
            """, (expedicao_id, caixa_83))
    estoque.remover_itens_reservados_op(expedicao_id, 88)
    with conectar() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT op_id,caixa_id FROM expedicao_itens WHERE COALESCE(ativo,1)=1 ORDER BY op_id")
            restantes = [(int(x["op_id"]), int(x["caixa_id"])) for x in cursor.fetchall()]
            cursor.execute("SELECT disponibilidade FROM pa_caixas WHERE id=%s", (caixa_83,))
            disponibilidade = cursor.fetchone()["disponibilidade"]
    assert restantes == [(83, caixa_83), (89, saldo_89)]
    assert disponibilidade == "RESERVADO"
    assert caixas_88[0] not in {item[1] for item in restantes}
