from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3

import pytest

from modules.expedicao import estornos_embalagem as estornos
from modules.expedicao import conferencia_embalagem as conferencia
from modules.producao import operacoes_op as operacoes


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "p0-2.db"

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

    for modulo in (estornos, operacoes):
        monkeypatch.setattr(modulo, "conectar", conectar)
        monkeypatch.setattr(modulo, "DATABASE_URL", None)
    monkeypatch.setattr(conferencia, "conectar", conectar)
    monkeypatch.setattr(conferencia, "DATABASE_URL", None)
    monkeypatch.setattr(estornos, "transaction", transacao)
    monkeypatch.setattr(operacoes, "transaction", transacao)
    monkeypatch.setattr(estornos, "_SCHEMA_ESTORNOS_INICIALIZADO", False)
    monkeypatch.setattr(operacoes, "_SCHEMA_INICIALIZADO", False)
    monkeypatch.setattr(operacoes, "invalidar_por_reabertura", lambda *args, **kwargs: None)
    monkeypatch.setenv("SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED", "true")
    monkeypatch.setenv("OP_REVERSAL_REOPEN_ENABLED", "true")

    conn = conectar()
    conn.executescript("""
        CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,status TEXT,sku TEXT,data TEXT);
        CREATE TABLE pa_caixas(
            id INTEGER PRIMARY KEY,codigo_caixa TEXT UNIQUE,sku TEXT,data_fabricacao TEXT,
            data_validade TEXT,peso_bruto REAL,peso_tara REAL,peso_liquido REAL,
            quantidade_bandejas REAL,status TEXT,origem TEXT,observacoes TEXT,
            local_estoque_id INTEGER,criado_em TEXT,estoque_operacional INTEGER,
            condicao TEXT,disponibilidade TEXT,reservado_expedicao_id INTEGER,
            quantidade_pacotes_reservados INTEGER DEFAULT 0
        );
        CREATE TABLE pa_caixa_composicao(id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,op_id INTEGER,quantidade_bandejas REAL,criado_em TEXT);
        CREATE TABLE estoque_produto_intermediario(
            id INTEGER PRIMARY KEY AUTOINCREMENT,data_movimentacao TEXT,tipo TEXT,op_id INTEGER,
            sku TEXT,quantidade_bandejas REAL,origem TEXT,observacoes TEXT,criado_em TEXT,
            caixa_id INTEGER,movimento_origem_id INTEGER,idempotency_key TEXT
        );
        CREATE TABLE estoque_eventos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,expedicao_id INTEGER,
            acao TEXT,situacao_anterior TEXT,situacao_nova TEXT,condicao_anterior TEXT,
            condicao_nova TEXT,quantidade REAL,peso REAL,justificativa TEXT,observacao TEXT,
            usuario TEXT,perfil TEXT,criado_em TEXT,idempotency_key TEXT UNIQUE
        );
        CREATE TABLE expedicoes(id INTEGER PRIMARY KEY,numero_romaneio TEXT,status TEXT);
        CREATE TABLE expedicao_itens(id INTEGER PRIMARY KEY,expedicao_id INTEGER,caixa_id INTEGER);
        CREATE TABLE pa_movimentacoes(id INTEGER PRIMARY KEY,caixa_id INTEGER,tipo TEXT);
        CREATE TABLE pa_nao_conformes(id INTEGER PRIMARY KEY,caixa_id INTEGER,status TEXT,saldo_destinado_g INTEGER DEFAULT 0);
        CREATE TABLE apontamentos_producao(id INTEGER PRIMARY KEY AUTOINCREMENT,op_id INTEGER,observacoes TEXT);

        INSERT INTO ordens_producao VALUES(7,'Encerrada','Galinha Cortada','2026-08-25');
        INSERT INTO pa_caixas VALUES(1,'CX-P02','Galinha Cortada','2026-08-25','2027-08-25',12.5,.5,12,12,'Em estoque','Embalagem Secundária','',1,'2026-08-25 08:00:00',1,'CONFORME','DISPONIVEL',NULL,0);
        INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(1,7,12);
        INSERT INTO estoque_produto_intermediario(data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,idempotency_key)
          VALUES('2026-08-25','ENTRADA_EMBALAGEM_PRIMARIA',7,'Galinha Cortada',12,'Embalagem Primária','Entrada original','PI-ORIGEM');
        INSERT INTO estoque_produto_intermediario(data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,caixa_id,idempotency_key)
          VALUES('2026-08-25','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',12,'Embalagem Secundária','Bandejas consumidas na formação da caixa PA #1.',1,'PI-SAIDA');
        INSERT INTO estoque_eventos(caixa_id,acao,idempotency_key) VALUES(1,'FORMACAO_ESTOQUE','FORM-1');
        INSERT INTO apontamentos_producao(op_id,observacoes) VALUES(7,'Produção final informada no encerramento da OP | P0.2');
    """)
    conn.commit(); conn.close()
    operacoes.criar_tabelas_operacoes_op()
    conn = conectar()
    conn.execute("""INSERT INTO embalagem_secundaria_conferencias(
        op_id,usuario,perfil,confirmado_em,caixas_ativas,caixas_estornadas,total_bandejas,
        peso_bruto,peso_tara,peso_liquido,saldo_pendente,caixas_ativas_json,duplicidades_json,
        hash_conferencia,confirmada) VALUES(7,'PCP','pcp','2026-08-25 09:00:00',1,0,'12','12.5',
        '.5','12','0','[1]','[]','HASH-P02',1)""")
    conn.commit(); conn.close()
    return conectar


def _reabrir(**extras):
    dados = dict(usuario="Supervisora", perfil="pcp", motivo="Correção de pesagem",
                 etapa_destino="EMBALAGEM_SECUNDARIA", idempotency_key="REABRIR-1",
                 confirmacao=True, ip_origem="127.0.0.1")
    dados.update(extras)
    return operacoes.reabrir_op(7, **dados)


def _estornar(**extras):
    dados = dict(usuario="Gerente", perfil="gerencia", motivo="OP lançada em duplicidade",
                 idempotency_key="ESTORNAR-1", confirmacao=True, ip_origem="127.0.0.1")
    dados.update(extras)
    return operacoes.estornar_op_integral(7, **dados)


def test_preflight_em_lote_tem_contagem_sql_constante_com_volume(banco, monkeypatch):
    consultas = []

    def conectar_contado():
        conn = banco()
        conn.set_trace_callback(
            lambda sql: consultas.append(sql)
            if sql.lstrip().upper().startswith("SELECT") else None
        )
        return conn

    monkeypatch.setattr(operacoes, "conectar", conectar_contado)
    operacoes.preflight_operacao_op(7, "ESTORNO_INTEGRAL")
    uma_caixa = len(consultas)

    conn = banco()
    for caixa_id in range(2, 329):
        conn.execute("""INSERT INTO pa_caixas(
            id,codigo_caixa,sku,data_fabricacao,data_validade,peso_bruto,peso_tara,peso_liquido,
            quantidade_bandejas,status,origem,observacoes,local_estoque_id,criado_em,
            estoque_operacional,condicao,disponibilidade,reservado_expedicao_id,
            quantidade_pacotes_reservados) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            caixa_id, f"CX-P02-{caixa_id}", "Galinha Cortada", "2026-08-25", "2027-08-25",
            12.5, .5, 12, 12, "Em estoque", "Embalagem Secundária", "", 1,
            "2026-08-25 08:00:00", 1, "CONFORME", "DISPONIVEL", None, 0,
        ))
        conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(?,?,12)", (caixa_id, 7))
        conn.execute("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,caixa_id,idempotency_key)
            VALUES('2026-08-25','SAIDA_EMBALAGEM_SECUNDARIA',7,'Galinha Cortada',12,
                   'Embalagem Secundária',?,?,?)""",
            (f"Bandejas consumidas na formação da caixa PA #{caixa_id}.", caixa_id, f"PI-SAIDA-{caixa_id}"))
        conn.execute("INSERT INTO estoque_eventos(caixa_id,acao,idempotency_key) VALUES(?,'FORMACAO_ESTOQUE',?)",
                     (caixa_id, f"FORM-{caixa_id}"))
    conn.commit()
    conn.close()

    consultas.clear()
    resultado = operacoes.preflight_operacao_op(7, "ESTORNO_INTEGRAL")
    trezentas_e_vinte_e_oito_caixas = len(consultas)

    assert resultado["caixas_ativas"] == 328
    assert resultado["permitido"]
    assert uma_caixa == trezentas_e_vinte_e_oito_caixas
    assert trezentas_e_vinte_e_oito_caixas <= 15

    with ThreadPoolExecutor(max_workers=5) as executor:
        leituras = list(executor.map(
            lambda _: operacoes.preflight_operacao_op(7, "ESTORNO_INTEGRAL"), range(5)
        ))
    assert all(item["permitido"] and item["caixas_ativas"] == 328 for item in leituras)


def test_reabertura_preserva_pi_pa_caixa_e_apontamento_e_invalida_conferencia(banco):
    conn = banco()
    antes = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in (
        "estoque_produto_intermediario", "pa_caixas", "apontamentos_producao")}
    conn.close()
    resultado = _reabrir()
    conn = banco()
    depois = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in antes}
    assert antes == depois
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=7").fetchone()[0] == "Aberta"
    assert conn.execute("SELECT status FROM pa_caixas WHERE id=1").fetchone()[0] == "Em estoque"
    assert conn.execute("SELECT confirmada FROM embalagem_secundaria_conferencias").fetchone()[0] == 0
    assert resultado["efeitos"]["pi_preservado"] and resultado["efeitos"]["apontamentos_preservados"]
    conn.close()


@pytest.mark.parametrize("perfil", ["admin", "pcp", "gerencia"])
def test_perfis_autorizados_reabrem(banco, perfil):
    assert _reabrir(perfil=perfil, idempotency_key=f"R-{perfil}")["sucesso"]


@pytest.mark.parametrize("perfil", ["producao", "qualidade", "manutencao", "", None])
def test_perfis_nao_autorizados_sao_negados_sem_mutacao(banco, perfil):
    with pytest.raises(PermissionError):
        _reabrir(perfil=perfil, idempotency_key=f"NEG-{perfil}")
    conn = banco(); assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Encerrada"; conn.close()


@pytest.mark.parametrize("etapa", ["EMBALAGEM_SECUNDARIA", "CONFERENCIA_FINAL"])
def test_etapas_de_destino_validas(banco, etapa):
    assert _reabrir(etapa_destino=etapa, idempotency_key=f"ET-{etapa}")["etapa_destino"] == etapa


@pytest.mark.parametrize("etapa", ["", "ABATE", "EXPEDICAO", None])
def test_etapa_invalida_rejeitada(banco, etapa):
    with pytest.raises(ValueError, match="etapa"):
        _reabrir(etapa_destino=etapa)


@pytest.mark.parametrize("motivo", ["", "x", "1234", None])
def test_motivo_curto_rejeitado(banco, motivo):
    with pytest.raises(ValueError, match="motivo"):
        _reabrir(motivo=motivo)


def test_confirmacao_explicita_obrigatoria_nas_duas_acoes(banco):
    with pytest.raises(ValueError, match="Confirme"):
        _reabrir(confirmacao=False)
    with pytest.raises(ValueError, match="Confirme"):
        _estornar(confirmacao=False)


@pytest.mark.parametrize("status", ["Aberta", "Estornada", "Cancelada", "Aguardando Embalagem Secundária"])
def test_reabertura_somente_de_encerrada(banco, status):
    conn = banco(); conn.execute("UPDATE ordens_producao SET status=?", (status,)); conn.commit(); conn.close()
    with pytest.raises(ValueError, match="Somente OP Encerrada"):
        _reabrir()


@pytest.mark.parametrize("preparar,mensagem", [
    (lambda c: c.executescript("INSERT INTO expedicoes VALUES(1,'ROM-77','Aberto'); INSERT INTO expedicao_itens VALUES(1,1,1);"), "Romaneio nº ROM-77"),
    (lambda c: c.execute("INSERT INTO pa_movimentacoes VALUES(1,1,'TRANSFERENCIA')"), "movimentação posterior TRANSFERENCIA"),
    (lambda c: c.execute("INSERT INTO estoque_eventos(caixa_id,acao,idempotency_key) VALUES(1,'AJUSTE_PESO','AJ-1')"), "evento sucessor AJUSTE_PESO"),
    (lambda c: c.execute("UPDATE pa_caixas SET reservado_expedicao_id=9 WHERE id=1"), "reserva operacional ativa"),
    (lambda c: c.execute("UPDATE pa_caixas SET quantidade_pacotes_reservados=2 WHERE id=1"), "reserva operacional ativa"),
    (lambda c: c.execute("INSERT INTO pa_nao_conformes VALUES(1,1,'DESCARTADO',0)"), "PNC nº 1"),
    (lambda c: c.execute("INSERT INTO pa_nao_conformes VALUES(1,1,'BLOQUEADO',100)"), "PNC nº 1"),
    (lambda c: c.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(1,99,1)"), "composição mista"),
])
def test_preflight_reabertura_bloqueia_sucessores_sem_mutar(banco, preparar, mensagem):
    conn = banco(); preparar(conn); conn.commit(); conn.close()
    preflight = operacoes.preflight_operacao_op(7, "REABERTURA")
    assert not preflight["permitido"] and any(mensagem in item for item in preflight["bloqueios"])
    with pytest.raises(ValueError, match="Reabertura bloqueada"):
        _reabrir()
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Encerrada"
    assert conn.execute("SELECT confirmada FROM embalagem_secundaria_conferencias").fetchone()[0] == 1
    conn.close()


def test_pnc_ativo_sem_destinacao_nao_superbloqueia_reabertura(banco):
    conn = banco(); conn.execute("INSERT INTO pa_nao_conformes VALUES(1,1,'BLOQUEADO',0)"); conn.commit(); conn.close()
    assert operacoes.preflight_operacao_op(7, "REABERTURA")["permitido"]


def test_estorno_integral_compensa_pi_estorna_pa_e_invalida_indicador_sem_delete(banco):
    resultado = _estornar()
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Estornada"
    caixa = conn.execute("SELECT status,estoque_operacional,disponibilidade FROM pa_caixas").fetchone()
    assert tuple(caixa) == ("Estornada", 0, "ESTORNADO")
    assert conn.execute("SELECT COUNT(*) FROM apontamentos_producao").fetchone()[0] == 1
    assert conn.execute("SELECT vigente FROM apontamentos_producao").fetchone()[0] == 0
    saldo = conn.execute("""SELECT SUM(CASE WHEN tipo LIKE 'ENTRADA%' THEN quantidade_bandejas ELSE -quantidade_bandejas END)
        FROM estoque_produto_intermediario WHERE op_id=7""").fetchone()[0]
    assert saldo == 0
    assert resultado["efeitos"]["hard_delete"] is False
    assert len(resultado["efeitos"]["compensacoes_pi"]) == 1
    conn.close()


@pytest.mark.parametrize("perfil", ["admin", "pcp", "gerencia"])
def test_perfis_autorizados_estornam_integralmente(banco, perfil):
    assert _estornar(perfil=perfil, idempotency_key=f"E-{perfil}")["status_op_posterior"] == "Estornada"


@pytest.mark.parametrize("preparar,trecho", [
    (lambda c: c.executescript("INSERT INTO expedicoes VALUES(1,'ROM-88','Concluído'); INSERT INTO expedicao_itens VALUES(1,1,1);"), "ROM-88"),
    (lambda c: c.execute("INSERT INTO pa_movimentacoes VALUES(1,1,'TRANSFERENCIA')"), "TRANSFERENCIA"),
    (lambda c: c.execute("INSERT INTO pa_nao_conformes VALUES(1,1,'BLOQUEADO',0)"), "Produto Não Conforme"),
    (lambda c: c.execute("INSERT INTO estoque_eventos(caixa_id,acao,idempotency_key) VALUES(1,'REPROCESSAMENTO','REP-1')"), "REPROCESSAMENTO"),
    (lambda c: c.execute("UPDATE pa_caixas SET reservado_expedicao_id=22 WHERE id=1"), "reservada"),
    (lambda c: c.execute("UPDATE pa_caixas SET disponibilidade='TRANSFERIDA' WHERE id=1"), "TRANSFERIDA"),
])
def test_estorno_integral_bloqueado_e_atomico(banco, preparar, trecho):
    conn = banco(); preparar(conn); conn.commit(); conn.close()
    with pytest.raises(ValueError) as erro:
        _estornar()
    assert trecho in str(erro.value)
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Encerrada"
    assert conn.execute("SELECT status FROM pa_caixas").fetchone()[0] == "Em estoque"
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria").fetchone()[0] == 0
    conn.close()


def test_movimento_pi_incompleto_bloqueia_antes_de_mutar(banco):
    conn = banco(); conn.execute("UPDATE estoque_produto_intermediario SET quantidade_bandejas=11 WHERE tipo='SAIDA_EMBALAGEM_SECUNDARIA'"); conn.commit(); conn.close()
    with pytest.raises(ValueError, match="não estão íntegros"):
        _estornar()
    conn = banco(); assert conn.execute("SELECT status FROM pa_caixas").fetchone()[0] == "Em estoque"; conn.close()


def test_entrada_pi_ausente_bloqueia_antes_de_mutar(banco):
    conn = banco(); conn.execute("DELETE FROM estoque_produto_intermediario WHERE tipo='ENTRADA_EMBALAGEM_PRIMARIA'"); conn.commit(); conn.close()
    with pytest.raises(ValueError, match="movimento original de entrada de PI"):
        _estornar()
    conn = banco(); assert conn.execute("SELECT status FROM pa_caixas").fetchone()[0] == "Em estoque"; conn.close()


def test_op_com_caixa_ja_estornada_preserva_historico_e_compensa_saldo_residual(banco):
    conn = banco()
    conn.execute("UPDATE pa_caixas SET status='Estornada',estoque_operacional=0,disponibilidade='ESTORNADO' WHERE id=1")
    conn.execute("""INSERT INTO estoque_produto_intermediario(data_movimentacao,tipo,op_id,sku,
        quantidade_bandejas,origem,observacoes,caixa_id,movimento_origem_id,idempotency_key)
        VALUES('2026-08-25','ENTRADA_ESTORNO_CAIXA',7,'Galinha Cortada',12,'Estorno anterior',
        'Histórico preservado',1,2,'ESTORNO-ANTERIOR')""")
    conn.commit(); conn.close()
    resultado = _estornar()
    assert resultado["efeitos"]["caixas_estornadas"] == 0
    assert resultado["efeitos"]["caixas_ja_estornadas_preservadas"] == 1
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE idempotency_key='ESTORNO-ANTERIOR'").fetchone()[0] == 1
    saldo = conn.execute("""SELECT SUM(CASE WHEN tipo LIKE 'ENTRADA%' THEN quantidade_bandejas ELSE -quantidade_bandejas END)
        FROM estoque_produto_intermediario WHERE op_id=7""").fetchone()[0]
    assert saldo == 0
    conn.close()


def test_falha_injetada_depois_do_estorno_da_caixa_faz_rollback_integral(banco, monkeypatch):
    original = operacoes._estornar_caixa_cursor

    def falhar_depois(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("falha controlada")

    monkeypatch.setattr(operacoes, "_estornar_caixa_cursor", falhar_depois)
    with pytest.raises(RuntimeError, match="falha controlada"):
        _estornar()
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Encerrada"
    assert conn.execute("SELECT status FROM pa_caixas").fetchone()[0] == "Em estoque"
    assert conn.execute("SELECT COUNT(*) FROM embalagem_secundaria_estornos").fetchone()[0] == 0
    conn.close()


def test_idempotencia_reabertura_retorna_mesmo_resultado_sem_duplicar_auditoria(banco):
    primeiro = _reabrir()
    segundo = _reabrir()
    conn = banco()
    assert primeiro == segundo
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria").fetchone()[0] == 1
    assert conn.execute("SELECT versao_operacional FROM ordens_producao").fetchone()[0] == 1
    conn.close()


def test_idempotencia_estorno_nao_duplica_compensacoes(banco):
    primeiro = _estornar()
    segundo = _estornar()
    conn = banco()
    assert primeiro == segundo
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario WHERE tipo='SAIDA_ESTORNO_OP'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria").fetchone()[0] == 1
    conn.close()


def test_feature_flags_interrompem_operacoes_sem_mutacao(banco, monkeypatch):
    monkeypatch.setenv("OP_REVERSAL_REOPEN_ENABLED", "false")
    with pytest.raises(PermissionError):
        _reabrir()
    monkeypatch.setenv("OP_REVERSAL_REOPEN_ENABLED", "true")
    monkeypatch.setenv("SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED", "false")
    with pytest.raises(PermissionError):
        _estornar()


def test_auditoria_registra_identidade_motivo_preflight_efeitos_e_ip(banco):
    _reabrir()
    conn = banco(); evento = conn.execute("SELECT * FROM op_operacoes_auditoria").fetchone(); conn.close()
    assert (evento["usuario"], evento["perfil"], evento["ip_origem"]) == ("Supervisora", "pcp", "127.0.0.1")
    assert json.loads(evento["preflight_json"])["permitido"]
    assert json.loads(evento["efeitos_json"])["pi_preservado"]


def test_preflight_e_read_only(banco):
    conn = banco(); antes = conn.total_changes; conn.close()
    resultado = operacoes.preflight_operacao_op(7, "ESTORNO_INTEGRAL")
    conn = banco()
    assert resultado["permitido"]
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria").fetchone()[0] == 0
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Encerrada"
    conn.close()


def _preparar_op_parcial_para_retomada(banco):
    conn = banco()
    conn.execute("UPDATE ordens_producao SET status='Aguardando Embalagem Secundária' WHERE id=7")
    conn.execute("UPDATE estoque_produto_intermediario SET quantidade_bandejas=24 WHERE tipo='ENTRADA_EMBALAGEM_PRIMARIA'")
    conn.execute("""INSERT INTO pa_caixas(
        id,codigo_caixa,sku,data_fabricacao,data_validade,peso_bruto,peso_tara,peso_liquido,
        quantidade_bandejas,status,origem,observacoes,local_estoque_id,criado_em,
        estoque_operacional,condicao,disponibilidade,reservado_expedicao_id,
        quantidade_pacotes_reservados) VALUES(
        2,'CX-P02-EST','Galinha Cortada','2026-08-25','2027-08-25',12.5,.5,12,12,
        'Estornada','Embalagem Secundária','',1,'2026-08-25 08:05:00',0,
        'CONFORME','ESTORNADO',NULL,0)""")
    conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(2,7,12)")
    conn.commit()
    conn.close()


def test_retomada_parcial_preserva_caixas_pi_pa_estornos_e_invalida_conferencia(banco):
    _preparar_op_parcial_para_retomada(banco)
    preflight = operacoes.preflight_retomada_embalagem_secundaria(7)
    assert preflight["permitido"]
    assert preflight["caixas_ativas"] == 1
    assert preflight["caixas_estornadas"] == 1
    assert preflight["saldo_pi"] == "12.0"
    resultado = operacoes.retomar_embalagem_secundaria(
        7, usuario="Supervisora", perfil="pcp", idempotency_key="RETOMAR-PARCIAL-1",
        confirmacao=True, ip_origem="127.0.0.1",
    )
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=7").fetchone()[0] == "Aberta"
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas").fetchone()[0] == 2
    assert conn.execute("SELECT status FROM pa_caixas WHERE id=2").fetchone()[0] == "Estornada"
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario").fetchone()[0] == 2
    assert conn.execute("SELECT confirmada FROM embalagem_secundaria_conferencias").fetchone()[0] == 0
    auditoria = conn.execute("SELECT tipo,status_anterior,status_posterior FROM op_operacoes_auditoria").fetchone()
    assert tuple(auditoria) == ("RETOMADA_EMBALAGEM_SECUNDARIA", "Aguardando Embalagem Secundária", "Aberta")
    conn.close()
    assert resultado["efeitos"]["hard_delete"] is False
    assert resultado["efeitos"]["caixas_ativas_preservadas"] == 1
    assert resultado["efeitos"]["caixas_estornadas_preservadas"] == 1


def test_retomada_e_idempotente_e_segunda_acao_concorrente_e_rejeitada(banco):
    _preparar_op_parcial_para_retomada(banco)
    argumentos = dict(usuario="Supervisora", perfil="pcp", idempotency_key="RETOMAR-IDEM", confirmacao=True)
    primeiro = operacoes.retomar_embalagem_secundaria(7, **argumentos)
    assert operacoes.retomar_embalagem_secundaria(7, **argumentos) == primeiro
    with pytest.raises(ValueError, match="Retomada bloqueada"):
        operacoes.retomar_embalagem_secundaria(7, **dict(argumentos, idempotency_key="RETOMAR-CONCORRENTE"))
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria").fetchone()[0] == 1
    assert conn.execute("SELECT versao_operacional FROM ordens_producao").fetchone()[0] == 1
    conn.close()


def test_retomada_sem_saldo_ou_sem_caixa_ativa_e_bloqueada_sem_mutacao(banco):
    conn = banco()
    conn.execute("UPDATE ordens_producao SET status='Aguardando Embalagem Secundária' WHERE id=7")
    conn.commit(); conn.close()
    preflight = operacoes.preflight_retomada_embalagem_secundaria(7)
    assert not preflight["permitido"]
    assert any("saldo pendente" in item for item in preflight["bloqueios"])
    with pytest.raises(ValueError, match="Retomada bloqueada"):
        operacoes.retomar_embalagem_secundaria(
            7, usuario="Supervisora", perfil="pcp", idempotency_key="RETOMAR-SEM-SALDO",
            confirmacao=True,
        )
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao").fetchone()[0] == "Aguardando Embalagem Secundária"
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria").fetchone()[0] == 0
    conn.close()


def test_regressao_postgresql_for_update_nao_usa_distinct(monkeypatch):
    class CursorPostgres:
        def __init__(self):
            self.sql = ""

        def execute(self, sql, parametros):
            self.sql = sql
            if "DISTINCT" in sql.upper() and "FOR UPDATE" in sql.upper():
                raise RuntimeError("psycopg2.errors.FeatureNotSupported: FOR UPDATE is not allowed with DISTINCT clause")

        def fetchall(self):
            return []

    monkeypatch.setattr(operacoes, "DATABASE_URL", "postgresql://teste")
    monkeypatch.setattr(estornos, "DATABASE_URL", "postgresql://teste")
    cursor = CursorPostgres()
    assert operacoes._caixas_op(cursor, 83, bloquear=True) == []
    assert "EXISTS" in cursor.sql.upper()
    assert "FOR UPDATE" in cursor.sql.upper()
    assert "DISTINCT" not in cursor.sql.upper()


def test_migration_sqlite_aditiva_e_rollback_reversivel():
    raiz = Path(__file__).resolve().parents[1]
    conn = sqlite3.connect(":memory:")
    conn.executescript("""CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,status TEXT);
        CREATE TABLE apontamentos_producao(id INTEGER PRIMARY KEY,op_id INTEGER);""")
    conn.executescript((raiz / "database/20260825_p0_2_estorno_reabertura_op_sqlite.sql").read_text(encoding="utf-8"))
    assert "op_operacoes_auditoria" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"vigente", "invalidado_em", "invalidado_por"} <= {r[1] for r in conn.execute("PRAGMA table_info(apontamentos_producao)")}
    conn.executescript((raiz / "database/20260825_p0_2_estorno_reabertura_op_sqlite_rollback.sql").read_text(encoding="utf-8"))
    assert "op_operacoes_auditoria" not in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "vigente" not in {r[1] for r in conn.execute("PRAGMA table_info(apontamentos_producao)")}
    conn.close()
