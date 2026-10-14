from contextlib import contextmanager
import sqlite3

import pytest

from modules.expedicao import services as expedicao
from modules.expedicao import estoque_service
from modules.producao import operacoes_op as operacoes
from test_p0_2_estorno_reabertura_op import banco  # noqa: F401


@pytest.fixture()
def primaria(banco, monkeypatch):  # noqa: F811
    caminho = banco().execute("PRAGMA database_list").fetchone()[2]

    def conectar():
        conn = sqlite3.connect(caminho)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transacao():
        conn = conectar()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    monkeypatch.setattr(expedicao, "conectar", conectar)
    monkeypatch.setattr(expedicao, "transaction", transacao)
    monkeypatch.setattr(expedicao, "DATABASE_URL", None)
    monkeypatch.setattr(expedicao, "_SCHEMA_ESTOQUE_PI_PA_INICIALIZADO", False)
    monkeypatch.setattr(operacoes, "conectar", conectar)
    monkeypatch.setattr(operacoes, "transaction", transacao)
    monkeypatch.setattr(estoque_service, "criar_tabelas_estoque_confiavel", lambda: None)
    expedicao.criar_tabelas_estoque_pi_pa()
    conn = conectar()
    for ddl in (
        "ALTER TABLE ordens_producao ADD COLUMN quantidade_aves REAL DEFAULT 0",
        "ALTER TABLE ordens_producao ADD COLUMN mortes_antes_pendura REAL DEFAULT 0",
    ):
        try:
            conn.execute(ddl)
        except sqlite3.OperationalError:
            pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS apontamentos_descartes(
            id INTEGER PRIMARY KEY,op_id INTEGER,setor TEXT,categoria TEXT,motivo TEXT,
            quantidade REAL,unidade TEXT,criado_em TEXT);
        DELETE FROM pa_caixa_composicao;
        DELETE FROM pa_caixas;
        DELETE FROM estoque_produto_intermediario;
        DELETE FROM embalagem_primaria_apontamentos;
        UPDATE ordens_producao SET status='Aberta',quantidade_aves=100,
            mortes_antes_pendura=0,versao_operacional=2 WHERE id=7;
        INSERT INTO embalagem_primaria_apontamentos(
            id,op_id,data_apontamento,sku,quantidade_bandejas,observacoes,criado_em,vigente)
            VALUES(74,7,'2026-09-16','Galinha Cortada',103,'','2026-10-07 18:43:59',1);
        INSERT INTO estoque_produto_intermediario(
            id,data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,
            criado_em,apontamento_origem_id)
            VALUES(2585,'2026-09-16','ENTRADA_EMBALAGEM_PRIMARIA',7,'Galinha Cortada',103,
            'Embalagem Primária','PI incorreto','2026-10-07 18:43:59',74);
    """)
    conn.commit(); conn.close()
    return conectar


def _reverter(**extras):
    dados = dict(motivo="Quantidade informada incorretamente", usuario="Gerente",
                 perfil="gerencia", idempotency_key="REV-PRIMARIA-1",
                 versao_esperada=2, confirmacao=True)
    dados.update(extras)
    return operacoes.reverter_apontamento_embalagem_primaria(7, **dados)


def _limpar_apontamento(conectar):
    conn = conectar()
    conn.execute("DELETE FROM estoque_produto_intermediario")
    conn.execute("DELETE FROM embalagem_primaria_apontamentos")
    conn.execute("UPDATE ordens_producao SET status='Aberta',versao_operacional=2 WHERE id=7")
    conn.commit(); conn.close()


def test_a_reversao_preserva_historico_compensa_pi_e_retorna_a_primaria(primaria):
    resultado = _reverter()
    conn = primaria()
    apontamento = conn.execute("SELECT * FROM embalagem_primaria_apontamentos WHERE id=74").fetchone()
    compensacao = conn.execute("SELECT * FROM estoque_produto_intermediario WHERE tipo='SAIDA_REVERSAO_EMBALAGEM_PRIMARIA'").fetchone()
    op = conn.execute("SELECT status,versao_operacional FROM ordens_producao WHERE id=7").fetchone()
    assert apontamento["vigente"] == 0 and apontamento["invalidacao_motivo"]
    assert compensacao["movimento_origem_id"] == 2585 and compensacao["quantidade_bandejas"] == 103
    assert tuple(op) == ("Aberta", 3)
    assert resultado["efeitos"]["saldo_pi_posterior"] == "0"
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria WHERE tipo='REVERSAO_EMBALAGEM_PRIMARIA'").fetchone()[0] == 1
    conn.close()


def test_b_reversao_idempotente_nao_duplica_compensacao(primaria):
    primeiro = _reverter()
    assert _reverter() == primeiro
    conn = primaria()
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='SAIDA_REVERSAO_EMBALAGEM_PRIMARIA'").fetchone()[0] == 1
    conn.close()


def test_c_d_apontamento_acima_bloqueia_e_igual_a_entrada_aceita(primaria):
    _limpar_apontamento(primaria)
    conn = primaria(); op = conn.execute("SELECT * FROM ordens_producao WHERE id=7").fetchone(); conn.close()
    with pytest.raises(ValueError, match="possui 100 aves"):
        expedicao.registrar_apontamento_embalagem_primaria(op, 103)
    expedicao.registrar_apontamento_embalagem_primaria(op, 100)
    conn = primaria()
    assert conn.execute("SELECT quantidade_bandejas FROM embalagem_primaria_apontamentos").fetchone()[0] == 100
    conn.close()


def test_e_soma_de_multiplos_apontamentos_nao_ultrapassa_entrada(primaria):
    _limpar_apontamento(primaria)
    conn = primaria(); op = conn.execute("SELECT * FROM ordens_producao WHERE id=7").fetchone(); conn.close()
    expedicao.registrar_apontamento_embalagem_primaria(op, 60)
    with pytest.raises(ValueError, match="já possui 60"):
        expedicao.registrar_apontamento_embalagem_primaria(op, 41)
    expedicao.registrar_apontamento_embalagem_primaria(op, 40)


def test_f_reversao_bloqueia_pi_consumido_em_pa(primaria):
    conn = primaria()
    conn.execute("INSERT INTO pa_caixas(id,codigo_caixa,sku,status,estoque_operacional,disponibilidade,criado_em) VALUES(9,'CX-NOVA','Galinha Cortada','Em estoque',1,'DISPONIVEL','2026-10-08')")
    conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(9,7,12)")
    conn.execute("INSERT INTO estoque_produto_intermediario(data_movimentacao,tipo,op_id,sku,quantidade_bandejas,caixa_id,criado_em) VALUES('2026-10-08','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',12,9,'2026-10-08')")
    conn.commit(); conn.close()
    with pytest.raises(ValueError, match="consumido por PA"):
        _reverter()


def test_g_h_formacao_pa_bloqueia_saldo_negativo_e_pi_acima_da_entrada(primaria):
    conn = primaria()
    with pytest.raises(ValueError, match="acima da entrada válida"):
        expedicao._validar_lancamento_secundaria_cursor(conn.cursor(), {7: 1})
    conn.execute("UPDATE estoque_produto_intermediario SET quantidade_bandejas=100 WHERE id=2585")
    conn.execute("INSERT INTO estoque_produto_intermediario(data_movimentacao,tipo,op_id,sku,quantidade_bandejas) VALUES('2026-10-08','SAIDA_TESTE',7,'Galinha Cortada',101)")
    conn.commit()
    with pytest.raises(ValueError, match="saldo PI negativo"):
        expedicao._validar_lancamento_secundaria_cursor(conn.cursor(), {7: 1})
    conn.close()


def test_i_falha_intermediaria_reverte_op_pi_apontamento_e_auditoria(primaria, monkeypatch):
    monkeypatch.setattr(operacoes, "_auditar", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("falha controlada")))
    with pytest.raises(RuntimeError, match="falha controlada"):
        _reverter()
    conn = primaria()
    assert conn.execute("SELECT vigente FROM embalagem_primaria_apontamentos WHERE id=74").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='SAIDA_REVERSAO_EMBALAGEM_PRIMARIA'").fetchone()[0] == 0
    assert tuple(conn.execute("SELECT status,versao_operacional FROM ordens_producao WHERE id=7").fetchone()) == ("Aberta", 2)
    conn.close()


def test_j_pa_historico_estornado_nao_bloqueia_novo_pi_e_fluxo_secundaria(primaria, monkeypatch):
    _reverter()
    conn = primaria()
    for indice in range(1, 10):
        caixa_id = 100 + indice
        conn.execute("""INSERT INTO pa_caixas(
            id,codigo_caixa,sku,status,estoque_operacional,disponibilidade,
            peso_bruto,peso_liquido,quantidade_bandejas,criado_em)
            VALUES(?,?,?,'Estornada',0,'ESTORNADO',10,9.5,?,?)""",
            (caixa_id, f"CX-HIST-{indice}", "Galinha Cortada", 12 if indice < 9 else 7,
             "2026-10-08"))
        conn.execute("""INSERT INTO pa_caixa_composicao(
            caixa_id,op_id,quantidade_bandejas) VALUES(?,?,?)""",
            (caixa_id, 7, 12 if indice < 9 else 7))
    op = conn.execute("SELECT * FROM ordens_producao WHERE id=7").fetchone()
    conn.commit()
    conn.close()

    expedicao.registrar_apontamento_embalagem_primaria(op, 100)

    conn = primaria()
    assert conn.execute("""SELECT COUNT(*) FROM pa_caixas
        WHERE codigo_caixa LIKE 'CX-HIST-%' AND status='Estornada'
          AND disponibilidade='ESTORNADO' AND estoque_operacional=0""").fetchone()[0] == 9
    assert conn.execute("SELECT COUNT(*) FROM pa_caixa_composicao WHERE op_id=7").fetchone()[0] == 9
    assert conn.execute("SELECT COUNT(*) FROM embalagem_primaria_apontamentos WHERE op_id=7").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE op_id=7").fetchone()[0] == 3
    assert conn.execute("""SELECT COALESCE(SUM(CASE WHEN tipo LIKE 'ENTRADA%' THEN quantidade_bandejas
        ELSE -quantidade_bandejas END),0) FROM estoque_produto_intermediario WHERE op_id=7""").fetchone()[0] == 100
    conn.close()

    disponiveis = {int(item["op_id"]): float(item["saldo_bandejas"])
                   for item in expedicao.buscar_ops_com_saldo_pi()}
    assert disponiveis[7] == 100

    monkeypatch.setattr("modules.label_printing.services.criar_job_caixa_cursor",
                        lambda *args, **kwargs: None)
    monkeypatch.setattr(estoque_service, "marcar_pa_pendente", lambda *args, **kwargs: None)
    monkeypatch.setattr(expedicao, "obter_sku_op", lambda op_id: "Galinha Cortada")
    monkeypatch.setattr(expedicao, "buscar_op_por_id", lambda op_id: op)
    codigo = expedicao.registrar_caixa_pa_manual({
        "op_principal": "7", "bandejas_principal": "12",
        "peso_bruto": "10.500", "peso_liquido": "10.000",
        "data_fabricacao": str(op["data"]),
        "data_validade": expedicao.calcular_validade_padrao(str(op["data"])),
        "idempotency_key": "OP102-NOVO-PA",
    }, usuario="Operador")
    assert codigo


def test_k_uma_caixa_ativa_ainda_bloqueia_reapontamento(primaria):
    _reverter()
    conn = primaria()
    conn.execute("""INSERT INTO pa_caixas(
        id,codigo_caixa,sku,status,estoque_operacional,disponibilidade,criado_em)
        VALUES(201,'CX-ATIVA','Galinha Cortada','Em estoque',1,'DISPONIVEL','2026-10-14')""")
    conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(201,7,12)")
    op = conn.execute("SELECT * FROM ordens_producao WHERE id=7").fetchone()
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="já possui caixas PA vinculadas"):
        expedicao.registrar_apontamento_embalagem_primaria(op, 100)


def test_l_pa_historico_nao_remove_limite_da_entrada(primaria):
    _reverter()
    conn = primaria()
    conn.execute("""INSERT INTO pa_caixas(
        id,codigo_caixa,sku,status,estoque_operacional,disponibilidade,criado_em)
        VALUES(301,'CX-HIST-LIMITE','Galinha Cortada','Estornada',0,'ESTORNADO','2026-10-08')""")
    conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(301,7,100)")
    op = conn.execute("SELECT * FROM ordens_producao WHERE id=7").fetchone()
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="possui 100 aves"):
        expedicao.registrar_apontamento_embalagem_primaria(op, 103)
