from decimal import Decimal

import pytest

from modules.expedicao import services as servicos_expedicao
from modules.producao import operacoes_op as operacoes
from test_p0_2_estorno_reabertura_op import banco  # noqa: F401  (fixture compartilhada)


SALDO_SQL = """SELECT COALESCE(SUM(CASE WHEN tipo LIKE 'ENTRADA%' THEN quantidade_bandejas
    WHEN tipo LIKE 'SAIDA%' THEN -quantidade_bandejas ELSE quantidade_bandejas END),0)
    FROM estoque_produto_intermediario WHERE op_id=7"""


def _estornar_op(chave="ESTORNAR-1"):
    return operacoes.estornar_op_integral(
        7, usuario="Gerente", perfil="gerencia", motivo="Estorno por engano",
        idempotency_key=chave, confirmacao=True, ip_origem="127.0.0.1",
    )


def _reverter(chave="REVERTER-1", **extras):
    dados = dict(usuario="Gerente", perfil="gerencia", motivo="Estorno feito por engano",
                 idempotency_key=chave, confirmacao=True, ip_origem="127.0.0.1")
    dados.update(extras)
    return operacoes.reverter_estorno_op(7, **dados)


@pytest.fixture()
def estornada(banco):  # noqa: F811
    # Antes do estorno a OP tem 12 bandejas de PI, todas consumidas pela caixa 1.
    _estornar_op()
    return banco


def _estado(conn):
    return (
        conn.execute("SELECT status,versao_operacional FROM ordens_producao WHERE id=7").fetchone()[:],
        conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario").fetchone()[0],
        conn.execute(SALDO_SQL).fetchone()[0],
    )


def test_a_reversao_restaura_pi_por_compensacao_e_preserva_caixas_historicas(estornada):
    conn = estornada()
    versao_antes = conn.execute("SELECT versao_operacional FROM ordens_producao").fetchone()[0]
    antes = conn.execute("SELECT * FROM estoque_produto_intermediario ORDER BY id").fetchall()
    assert conn.execute(SALDO_SQL).fetchone()[0] == 0
    conn.close()

    resultado = _reverter()

    conn = estornada()
    status, versao = conn.execute("SELECT status,versao_operacional FROM ordens_producao").fetchone()
    assert (status, versao) == ("Aberta", versao_antes + 1)
    assert conn.execute(SALDO_SQL).fetchone()[0] == 12
    caixa = conn.execute("SELECT status,estoque_operacional,disponibilidade FROM pa_caixas").fetchone()
    assert tuple(caixa) == ("Estornada", 0, "ESTORNADO")
    assert conn.execute("SELECT COUNT(*) FROM pa_caixa_composicao").fetchone()[0] == 1
    # Nenhum movimento anterior foi alterado ou apagado; apenas um foi acrescentado.
    depois = conn.execute("SELECT * FROM estoque_produto_intermediario ORDER BY id").fetchall()
    assert [tuple(l) for l in depois[:len(antes)]] == [tuple(l) for l in antes]
    assert len(depois) == len(antes) + 1
    novo = depois[-1]
    saida_estorno = conn.execute(
        "SELECT id,quantidade_bandejas FROM estoque_produto_intermediario WHERE tipo='SAIDA_ESTORNO_OP'").fetchone()
    assert novo["tipo"] == "ENTRADA_REVERSAO_ESTORNO_OP"
    assert novo["movimento_origem_id"] == saida_estorno["id"]
    assert novo["quantidade_bandejas"] == saida_estorno["quantidade_bandejas"] == 12
    assert Decimal(resultado["efeitos"]["pi_restaurado"]) == 12
    assert resultado["efeitos"]["hard_delete"] is False
    auditoria = conn.execute(
        "SELECT * FROM op_operacoes_auditoria WHERE tipo='REVERSAO_ESTORNO_OP'").fetchone()
    assert (auditoria["status_anterior"], auditoria["status_posterior"]) == ("Estornada", "Aberta")
    assert auditoria["usuario"] == "Gerente" and auditoria["motivo"] == "Estorno feito por engano"
    conn.close()


def test_b_idempotencia_nao_duplica_movimento(estornada):
    primeiro = _reverter()
    conn = estornada()
    estado = _estado(conn)
    conn.close()
    assert _reverter() == primeiro
    conn = estornada()
    assert _estado(conn) == estado
    assert conn.execute(
        "SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_REVERSAO_ESTORNO_OP'").fetchone()[0] == 1
    conn.close()


def test_b2_chave_de_outra_operacao_e_rejeitada(estornada):
    with pytest.raises(ValueError, match="outra operação"):
        _reverter(chave="ESTORNAR-1")


def test_c_op_nao_estornada_bloqueia(banco):  # noqa: F811
    with pytest.raises(ValueError, match="Somente OP Estornada"):
        _reverter()
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Encerrada"
    conn.close()


def test_c2_nao_permite_reverter_duas_vezes(estornada):
    _reverter()
    with pytest.raises(ValueError, match="Somente OP Estornada"):
        _reverter(chave="REVERTER-2")


def test_d_saldo_pi_diferente_de_zero_bloqueia(estornada):
    conn = estornada()
    conn.execute("""INSERT INTO estoque_produto_intermediario(data_movimentacao,tipo,op_id,sku,quantidade_bandejas,idempotency_key)
        VALUES('2026-08-26','ENTRADA_OP',7,'Galinha Cortada',3,'RESIDUO')""")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="saldo líquido atual de PI"):
        _reverter()
    conn = estornada()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Estornada"
    assert conn.execute(
        "SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='ENTRADA_REVERSAO_ESTORNO_OP'").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize("sql,trecho", [
    ("UPDATE pa_caixas SET estoque_operacional=1", "estoque operacional ativo"),
    ("UPDATE pa_caixas SET disponibilidade='DISPONIVEL'", "disponibilidade DISPONIVEL"),
    ("UPDATE pa_caixas SET disponibilidade='RESERVADO'", "disponibilidade RESERVADO"),
    ("UPDATE pa_caixas SET disponibilidade='EXPEDIDO'", "disponibilidade EXPEDIDO"),
    ("UPDATE pa_caixas SET status='Em estoque'", "não está estornada"),
    ("UPDATE pa_caixas SET reservado_expedicao_id=5", "reserva ativa"),
    ("UPDATE pa_caixas SET quantidade_pacotes_reservados=2", "reserva ativa"),
    ("INSERT INTO expedicoes VALUES(9,'RM-9','Aberto'); INSERT INTO expedicao_itens VALUES(1,9,1)", "Romaneio"),
    ("INSERT INTO pa_movimentacoes VALUES(1,1,'SAIDA')", "movimentação de PA posterior"),
])
def test_e_caixa_operacional_reservada_ou_expedida_bloqueia(estornada, sql, trecho):
    conn = estornada()
    conn.executescript(sql)
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match=trecho):
        _reverter()
    conn = estornada()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Estornada"
    assert conn.execute(SALDO_SQL).fetchone()[0] == 0
    conn.close()


def test_f_ausencia_do_movimento_saida_estorno_op_bloqueia(estornada):
    conn = estornada()
    conn.execute("DELETE FROM estoque_produto_intermediario WHERE tipo='SAIDA_ESTORNO_OP'")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="SAIDA_ESTORNO_OP"):
        _reverter()


def test_f2_divergencia_com_a_auditoria_do_estorno_bloqueia(estornada):
    conn = estornada()
    conn.execute("UPDATE estoque_produto_intermediario SET quantidade_bandejas=11 WHERE tipo='SAIDA_ESTORNO_OP'")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="ambígua"):
        _reverter()


def test_f3_sem_auditoria_de_estorno_integral_bloqueia(estornada):
    conn = estornada()
    conn.execute("DELETE FROM op_operacoes_auditoria WHERE tipo='ESTORNO_INTEGRAL'")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="registro auditado"):
        _reverter()


def test_g_falha_intermediaria_faz_rollback_integral(estornada, monkeypatch):
    def falhar(*args, **kwargs):
        raise RuntimeError("falha controlada")

    monkeypatch.setattr(operacoes, "_auditar", falhar)
    conn = estornada()
    antes = _estado(conn)
    conn.close()
    with pytest.raises(RuntimeError, match="falha controlada"):
        _reverter()
    conn = estornada()
    assert _estado(conn) == antes
    conn.close()


def test_g2_versao_desatualizada_bloqueia_sem_mutacao(estornada):
    with pytest.raises(ValueError, match="alterada por outra solicitação"):
        _reverter(versao_esperada=999)
    conn = estornada()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Estornada"
    conn.close()


def test_perfil_sem_permissao_e_motivo_obrigatorio(estornada):
    with pytest.raises(PermissionError):
        _reverter(perfil="producao")
    with pytest.raises(ValueError, match="motivo"):
        _reverter(motivo="  ")
    with pytest.raises(ValueError, match="Confirme"):
        _reverter(confirmacao=False)


def test_conferencia_valida_e_invalidada(estornada):
    conn = estornada()
    conn.execute("UPDATE embalagem_secundaria_conferencias SET confirmada=1")
    conn.commit(); conn.close()
    resultado = _reverter()
    conn = estornada()
    assert conn.execute("SELECT COUNT(*) FROM embalagem_secundaria_conferencias WHERE confirmada=1").fetchone()[0] == 0
    assert resultado["efeitos"]["conferencias_invalidadas"] >= 0
    conn.close()


def test_preflight_e_somente_leitura(estornada):
    conn = estornada()
    antes = _estado(conn)
    conn.close()
    preflight = operacoes.preflight_reversao_estorno_op(7)
    assert preflight["permitido"] is True and Decimal(preflight["pi_a_restaurar"]) == 12
    conn = estornada()
    assert _estado(conn) == antes
    conn.close()


def test_h_apos_reverter_a_op_aceita_nova_caixa_e_ignora_caixas_historicas(estornada, monkeypatch):
    # Antes da reversão, a OP Estornada não aceita nova caixa.
    conn = estornada()
    with pytest.raises(ValueError, match="não aceita novas caixas"):
        servicos_expedicao._validar_lancamento_secundaria_cursor(conn.cursor(), {7: 5})
    conn.close()

    _reverter()

    conn = estornada()
    ops = servicos_expedicao._validar_lancamento_secundaria_cursor(conn.cursor(), {7: 12})
    assert ops[7]["status"] == "Aberta"
    # O saldo de 12 já é suficiente; consumir 13 continua bloqueado.
    with pytest.raises(ValueError, match="possui apenas 12"):
        servicos_expedicao._validar_lancamento_secundaria_cursor(conn.cursor(), {7: 13})
    # A caixa antiga segue estornada e fora dos totais da OP.
    assert conn.execute("SELECT status FROM pa_caixas WHERE id=1").fetchone()[0] == "Estornada"
    conn.close()
