from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
import sqlite3

import pytest

from modules.expedicao import estoque_service
from modules.expedicao import reconciliacao_marco_zero as hotfix


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "hotfix-op-71.db"

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

    monkeypatch.setattr(hotfix, "conectar", conectar)
    monkeypatch.setattr(hotfix, "transaction", transacao)
    monkeypatch.setattr(hotfix, "DATABASE_URL", None)
    monkeypatch.setattr(hotfix, "criar_tabelas_estoque_pi_pa", lambda: None)
    monkeypatch.setattr(hotfix, "criar_tabelas_estoque_confiavel", lambda: None)
    monkeypatch.setattr(hotfix, "criar_tabelas_operacoes_op", lambda: None)
    monkeypatch.setattr(estoque_service, "conectar", conectar)
    monkeypatch.setattr(estoque_service, "DATABASE_URL", None)

    def gerar_stub(op, data_lancamento, hora_inicio, hora_fim, unidades_produzidas,
                   kg_produzidos=None, descontar_almoco=False, conn=None):
        conn.execute(
            "INSERT INTO apontamentos_producao(op_id,data,setor,quantidade,unidade,observacoes) VALUES(?,?,?,?,?,?)",
            (op["id"], data_lancamento, "Expedição", unidades_produzidas, "unidades",
             "Produção final informada no encerramento da OP | HOTFIX OP 71"),
        )
        conn.execute(
            "INSERT INTO apontamentos_producao(op_id,data,setor,quantidade,unidade,observacoes) VALUES(?,?,?,?,?,?)",
            (op["id"], data_lancamento, "Expedição", kg_produzidos, "kg",
             "Kg final produzido informado no encerramento da OP | HOTFIX OP 71"),
        )

    monkeypatch.setattr(hotfix, "gerar_producao_automatica_setores", gerar_stub)

    conn = conectar()
    conn.executescript("""
        CREATE TABLE estoque_marcos(
          id INTEGER PRIMARY KEY,tipo TEXT,referencia_data TEXT,fuso_horario TEXT,
          legacy_max_op_id INTEGER,ativado_por TEXT,ativado_em TEXT,status TEXT);
        CREATE TABLE ordens_producao(
          id INTEGER PRIMARY KEY,data TEXT,fornecedor TEXT,quantidade_aves INTEGER,
          mortes_antes_pendura INTEGER,peso_vivo REAL,peso_medio REAL,status TEXT,sku TEXT,
          estoque_classificacao TEXT,estoque_marco_id INTEGER,versao_operacional INTEGER DEFAULT 0);
        CREATE TABLE embalagem_primaria_apontamentos(
          id INTEGER PRIMARY KEY,op_id INTEGER,data_apontamento TEXT,sku TEXT,
          quantidade_bandejas REAL,observacoes TEXT,criado_em TEXT);
        CREATE TABLE pa_caixas(
          id INTEGER PRIMARY KEY,codigo_caixa TEXT UNIQUE,sku TEXT,data_fabricacao TEXT,
          data_validade TEXT,peso_bruto REAL,peso_tara REAL,peso_liquido REAL,
          quantidade_bandejas REAL,status TEXT,origem TEXT,observacoes TEXT,
          local_estoque_id INTEGER,criado_em TEXT,estoque_operacional INTEGER,
          condicao TEXT,disponibilidade TEXT,zona_estoque TEXT,motivo_nao_conformidade TEXT,
          reservado_expedicao_id INTEGER,formado_por TEXT,formado_em TEXT,
          unidade_estoque TEXT,quantidade_pacotes REAL,quantidade_pacotes_reservados INTEGER DEFAULT 0);
        CREATE TABLE pa_caixa_composicao(
          id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,op_id INTEGER,
          quantidade_bandejas REAL,criado_em TEXT);
        CREATE TABLE estoque_produto_intermediario(
          id INTEGER PRIMARY KEY AUTOINCREMENT,data_movimentacao TEXT,tipo TEXT,op_id INTEGER,
          sku TEXT,quantidade_bandejas REAL,origem TEXT,observacoes TEXT,criado_em TEXT,
          caixa_id INTEGER,movimento_origem_id INTEGER,idempotency_key TEXT);
        CREATE TABLE estoque_eventos(
          id INTEGER PRIMARY KEY AUTOINCREMENT,caixa_id INTEGER,expedicao_id INTEGER,
          acao TEXT,situacao_anterior TEXT,situacao_nova TEXT,condicao_anterior TEXT,
          condicao_nova TEXT,quantidade REAL,peso REAL,justificativa TEXT,observacao TEXT,
          usuario TEXT,perfil TEXT,criado_em TEXT,idempotency_key TEXT UNIQUE);
        CREATE TABLE pa_movimentacoes(id INTEGER PRIMARY KEY,caixa_id INTEGER,tipo TEXT);
        CREATE TABLE expedicao_itens(id INTEGER PRIMARY KEY,expedicao_id INTEGER,caixa_id INTEGER);
        CREATE TABLE apontamentos_descartes(
          id INTEGER PRIMARY KEY,op_id INTEGER,categoria TEXT,motivo TEXT,quantidade REAL,unidade TEXT);
        CREATE TABLE apontamentos_producao(
          id INTEGER PRIMARY KEY AUTOINCREMENT,op_id INTEGER,data TEXT,setor TEXT,
          quantidade REAL,unidade TEXT,observacoes TEXT);
        CREATE TABLE op_operacoes_auditoria(
          id INTEGER PRIMARY KEY AUTOINCREMENT,op_id INTEGER,tipo TEXT,idempotency_key TEXT UNIQUE,
          usuario TEXT,perfil TEXT,motivo TEXT,etapa_destino TEXT,status_anterior TEXT,
          status_posterior TEXT,preflight_json TEXT,efeitos_json TEXT,resultado_json TEXT,
          ip_origem TEXT,criado_em TEXT);
        CREATE TABLE financeiro_guard(id INTEGER PRIMARY KEY,estado TEXT,versao INTEGER);

        INSERT INTO estoque_marcos VALUES(
          1,'MARCO_ZERO','2026-07-24','America/Manaus',69,'Sistema','2026-07-24 10:23:38','ATIVO');
        INSERT INTO ordens_producao VALUES(
          71,'2026-08-01','São Pedro',500,0,926.5,1.853,'Aberta','Galinha Cortada','POS_MARCO',NULL,0);
        INSERT INTO ordens_producao VALUES(
          83,'2026-08-13','São Pedro',2000,0,3320,1.66,'Aberta','Galinha Cortada','POS_MARCO',NULL,1);
        INSERT INTO embalagem_primaria_apontamentos VALUES(
          50,71,'2026-08-01','Galinha Cortada',314,'','2026-08-27 18:17:10');
        INSERT INTO estoque_produto_intermediario(
          data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,criado_em)
          VALUES('2026-08-01','ENTRADA_EMBALAGEM_PRIMARIA',71,'Galinha Cortada',314,
                 'Embalagem Primária','Entrada original','2026-08-27 18:17:10');
        INSERT INTO apontamentos_descartes VALUES(360,71,'Descarte','Morte na gaiola',78,'aves');
        INSERT INTO apontamentos_descartes VALUES(361,71,'Descarte','Outra',84,'aves');
        INSERT INTO apontamentos_descartes VALUES(362,71,'Descarte','Hematomas',24,'aves');
        INSERT INTO financeiro_guard VALUES(1,'FINANCEIRO_EM_RECONSTRUCAO',7);
    """)
    pesos = [14.0] * 25 + [14.66] + [1.94]
    for indice, peso in enumerate(pesos, start=1):
        bandejas = 2 if indice == 27 else 12
        conn.execute("""INSERT INTO pa_caixas(
          id,codigo_caixa,sku,data_fabricacao,data_validade,peso_bruto,peso_tara,peso_liquido,
          quantidade_bandejas,status,origem,observacoes,local_estoque_id,criado_em,
          estoque_operacional,condicao,disponibilidade,zona_estoque,reservado_expedicao_id,
          formado_por,formado_em,unidade_estoque,quantidade_pacotes,quantidade_pacotes_reservados)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            indice, f"CX-20260827-{indice:03d}", "Galinha Cortada", "2026-08-01", "2027-08-01",
            peso + 0.5, 0.5, peso, bandejas, "Em estoque", "Embalagem Secundária", "",
            1, "2026-08-27 18:24:31", 0, "CONFORME", "PENDENTE_OP", "Conforme",
            None, None, None, "CAIXA", None, 0,
        ))
        conn.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas,criado_em) VALUES(?,?,?,?)",
                     (indice, 71, bandejas, "2026-08-27 18:24:31"))
        conn.execute("""INSERT INTO estoque_produto_intermediario(
          data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,criado_em,
          caixa_id,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?)""", (
            "2026-08-27", "SAIDA_EMBALAGEM_SECUNDARIA", 71, "Galinha Cortada", bandejas,
            "Embalagem Secundária", "Saída original", "2026-08-27 18:24:31", indice,
            f"SAIDA-PI-CAIXA-{indice}-OP-71",
        ))
    conn.commit()
    conn.close()
    return conectar


def fotografia(conectar):
    conn = conectar()
    resultado = {
        "op83": dict(conn.execute("SELECT * FROM ordens_producao WHERE id=83").fetchone()),
        "financeiro": dict(conn.execute("SELECT * FROM financeiro_guard").fetchone()),
        "caixas": [dict(item) for item in conn.execute("SELECT * FROM pa_caixas ORDER BY id")],
        "pi": [dict(item) for item in conn.execute("SELECT * FROM estoque_produto_intermediario ORDER BY id")],
    }
    conn.close()
    return resultado


def executar(**extras):
    args = dict(usuario="Codex Hotfix P0", perfil="admin", commit="abc123",
                idempotency_key=hotfix.CHAVE_PADRAO,
                confirmacao=hotfix.CONFIRMACAO_OP_71)
    args.update(extras)
    return hotfix.reconciliar_op_71(**args)


def test_preflight_fecha_27_caixas_314_bandejas_sem_duplicidade(banco):
    preflight = hotfix.preflight_reconciliacao_op(71)
    assert preflight["permitido"] and preflight["caminho"] == "A_RECONCILIAR_PA_EXISTENTE"
    assert preflight["op"]["ciclo"] == estoque_service.CICLO_OPERACIONAL
    assert preflight["caixas"]["total"] == 27
    assert preflight["caixas"]["bandejas"] == "314.0"
    assert preflight["caixas"]["padrao_12"] == 26
    assert preflight["caixas"]["parciais"] == 1
    assert len(preflight["caixas"]["itens"]) == 27
    assert preflight["caixas"]["itens"][0]["codigo"] == "CX-20260827-001"
    assert Decimal(preflight["caixas"]["peso_liquido"]) == Decimal("366.60")
    assert preflight["pi"]["entradas"] == preflight["pi"]["saidas"] == "314.0"
    assert preflight["pi"]["saldo"] == "0.0"
    assert preflight["vinculos"] == {"estoque_eventos": 0, "pa_movimentacoes": 0, "expedicao_itens": 0}


def test_reconciliacao_reaproveita_caixas_e_pi_e_preserva_op83_financeiro_datas(banco):
    antes = fotografia(banco)
    resultado = executar()
    depois = fotografia(banco)
    assert resultado["caixas_reaproveitadas"] == 27
    assert resultado["caixas_criadas"] == resultado["pi_criado"] == resultado["pi_consumido_novamente"] == 0
    assert antes["pi"] == depois["pi"]
    assert antes["op83"] == depois["op83"]
    assert antes["financeiro"] == depois["financeiro"]
    for anterior, atual in zip(antes["caixas"], depois["caixas"]):
        for campo in ("id", "codigo_caixa", "peso_bruto", "peso_liquido", "quantidade_bandejas",
                      "data_fabricacao", "data_validade", "sku"):
            assert anterior[campo] == atual[campo]
        assert atual["estoque_operacional"] == 1 and atual["disponibilidade"] == "DISPONIVEL"
    conn = banco()
    assert conn.execute("SELECT status FROM ordens_producao WHERE id=71").fetchone()[0] == "Encerrada"
    assert conn.execute("SELECT COUNT(*) FROM apontamentos_producao WHERE op_id=71").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM estoque_eventos WHERE acao=?", (hotfix.ACAO_RECONCILIACAO,)).fetchone()[0] == 27
    evento = conn.execute(
        "SELECT quantidade,peso FROM estoque_eventos WHERE acao=? ORDER BY caixa_id LIMIT 1",
        (hotfix.ACAO_RECONCILIACAO,),
    ).fetchone()
    assert evento["quantidade"] == 12 and Decimal(str(evento["peso"])) == Decimal("14.0")
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria WHERE op_id=71").fetchone()[0] == 1
    conn.close()


def test_segunda_execucao_e_idempotente(banco):
    primeiro = executar()
    segundo = executar()
    assert segundo == primeiro
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM pa_caixas").fetchone()[0] == 27
    assert conn.execute("SELECT COUNT(*) FROM estoque_produto_intermediario").fetchone()[0] == 28
    assert conn.execute("SELECT COUNT(*) FROM op_operacoes_auditoria").fetchone()[0] == 1
    conn.close()


@pytest.mark.parametrize("preparar,trecho", [
    (lambda c: c.execute("UPDATE pa_caixas SET reservado_expedicao_id=9 WHERE id=1"), "reservada"),
    (lambda c: c.execute("INSERT INTO pa_movimentacoes VALUES(1,1,'TRANSFERENCIA')"), "movimentação"),
    (lambda c: c.execute("INSERT INTO expedicao_itens VALUES(1,1,1)"), "expedição"),
    (lambda c: c.execute("INSERT INTO estoque_eventos(caixa_id,acao,idempotency_key) VALUES(1,'FORMACAO_ESTOQUE','F-1')"), "eventos"),
    (lambda c: c.execute("INSERT INTO pa_caixa_composicao(caixa_id,op_id,quantidade_bandejas) VALUES(1,83,1)"), "composição"),
])
def test_preflight_bloqueia_reserva_expedicao_movimento_evento_ou_origem_mista(banco, preparar, trecho):
    conn = banco(); preparar(conn); conn.commit(); conn.close()
    preflight = hotfix.preflight_reconciliacao_op(71)
    assert not preflight["permitido"] and trecho.lower() in " ".join(preflight["bloqueios"]).lower()
    with pytest.raises(ValueError, match="Reconciliação bloqueada"):
        executar(idempotency_key=f"BLOQ-{trecho}")


def test_saldo_parcial_permanece_disponivel_sem_promover_caixas(banco):
    conn = banco()
    conn.execute("DELETE FROM estoque_produto_intermediario WHERE caixa_id=27")
    conn.execute("DELETE FROM pa_caixa_composicao WHERE caixa_id=27")
    conn.execute("DELETE FROM pa_caixas WHERE id=27")
    conn.commit(); conn.close()
    preflight = hotfix.preflight_reconciliacao_op(71)
    assert preflight["permitido"] and preflight["caminho"] == "B_SALDO_REAL_PARA_PESAGEM"
    assert preflight["pi"]["saldo"] == "2.0"
    with pytest.raises(ValueError, match="caminho B"):
        executar(idempotency_key="PARCIAL")


def test_rollback_integral_em_falha_intermediaria(banco):
    antes = fotografia(banco)
    def falhar(etapa):
        if etapa == "depois_formacao_estoque":
            raise RuntimeError("falha simulada")
    with pytest.raises(RuntimeError, match="falha simulada"):
        executar(idempotency_key="ROLLBACK", checkpoint=falhar)
    depois = fotografia(banco)
    assert antes == depois
    conn = banco()
    assert conn.execute("SELECT COUNT(*) FROM apontamentos_producao").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM estoque_eventos").fetchone()[0] == 0
    conn.close()


def test_classificador_preserva_historica_transicao_operacional_e_reabertura_fail_closed(banco):
    conn = banco(); cursor = conn.cursor(); marco = cursor.execute("SELECT * FROM estoque_marcos").fetchone()
    cursor.execute("INSERT INTO ordens_producao VALUES(1,'2026-07-01','F',1,0,1,1,'Encerrada','X','LEGADA',1,0)")
    cursor.execute("INSERT INTO ordens_producao VALUES(2,'2026-07-01','F',1,0,1,1,'Aberta','X','TRANSICAO_OPERACIONAL',1,0)")
    cursor.execute("INSERT INTO ordens_producao VALUES(70,'2026-07-25','F',1,0,1,1,'Aberta','X','POS_MARCO',1,0)")
    conn.commit()
    ops = {item["id"]: item for item in cursor.execute("SELECT * FROM ordens_producao WHERE id IN (1,2,70)")}
    assert estoque_service.classificar_ciclo_operacional_op(cursor, ops[1], marco) == estoque_service.CICLO_HISTORICA
    assert estoque_service.classificar_ciclo_operacional_op(cursor, ops[2], marco) == estoque_service.CICLO_TRANSICAO
    assert estoque_service.classificar_ciclo_operacional_op(cursor, ops[70], marco) == estoque_service.CICLO_OPERACIONAL
    cursor.execute("""INSERT INTO op_operacoes_auditoria(
      op_id,tipo,idempotency_key,usuario,perfil,motivo,preflight_json,efeitos_json,
      resultado_json,criado_em) VALUES(1,'REABERTURA','R-1','u','admin','m','{}','{}','{}','2026-07-25 10:00:00')""")
    conn.commit()
    assert estoque_service.classificar_ciclo_operacional_op(cursor, ops[1], marco) == estoque_service.CICLO_HISTORICA_REABERTA
    assert estoque_service.classificar_ciclo_operacional_op(
        cursor, ops[1], marco, movimento_em="2026-07-25 11:00:00"
    ) == estoque_service.CICLO_OPERACIONAL
    conn.close()


def test_template_nao_chama_pa_pendente_de_historico():
    texto = Path(hotfix.__file__).resolve().parents[2] / "templates" / "estoque_produtos.html"
    conteudo = texto.read_text(encoding="utf-8")
    assert "caixa.disponibilidade == 'LEGADO'" in conteudo
    assert "Aguardando encerramento da OP" in conteudo
