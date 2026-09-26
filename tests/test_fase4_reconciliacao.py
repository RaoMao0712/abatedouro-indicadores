import copy
import json
from pathlib import Path

import pytest

import database.connection as dbc
from modules.engenharia_produtos import reconciliacao, representacao_legada, repositories, snapshot_op


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(dbc, "DB_NAME", str(tmp_path / "fase4.db"))
    monkeypatch.setattr(dbc, "DATABASE_URL", None)
    monkeypatch.setattr(reconciliacao, "DATABASE_URL", None)
    monkeypatch.setattr(snapshot_op, "DATABASE_URL", None)
    repositories.criar_estrutura()
    conn = dbc.conectar(); cur = conn.cursor()
    cur.execute("CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY AUTOINCREMENT,sku TEXT,status TEXT)")
    cur.execute("""INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES
        ('LEG-1','Galinha Cortada','PRODUTO_ACABADO','Kg','Sim'),
        ('LEG-2','Galinha Inteira','PRODUTO_ACABADO','Un','Sim')""")
    conn.commit(); conn.close()
    representacao_legada.aplicar("Teste Fase 4")
    reconciliacao.criar_estrutura()
    return dbc


def _criar(banco, sku):
    with banco.transaction() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO ordens_producao(sku,status) VALUES(?,'Aberta')", (sku,))
        op_id = cur.lastrowid
        snapshot_op.gravar_snapshot(cur, op_id, sku, 1, "Teste")
        registro = reconciliacao.reconciliar_op(cur, op_id)
    return op_id, registro


def _criar_sem_reconciliar(banco, sku):
    with banco.transaction() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO ordens_producao(sku,status) VALUES(?,'Aberta')", (sku,))
        op_id = cur.lastrowid
        snapshot_op.gravar_snapshot(cur, op_id, sku, 1, "Teste")
    return op_id


@pytest.mark.parametrize("sku,esperado", [
    ("Galinha Cortada", {"bandejas_por_caixa", "tara_caixa_kg", "exigencia_peso", "regra_encerramento"}),
    ("Galinha Inteira", {"fatores_conversao", "exigencia_peso", "regra_encerramento"}),
])
def test_paridade_integral_dos_skus_legados(banco, sku, esperado):
    _op_id, registro = _criar(banco, sku)
    assert registro["resultado_geral"] == "PARIDADE"
    dimensoes = json.loads(registro["dimensoes_json"])
    assert esperado <= {item["dimensao"] for item in dimensoes}
    assert all(item["resultado"] == "PARIDADE" for item in dimensoes)


@pytest.mark.parametrize("dimensao,mutacao", [
    ("identidade_sku", lambda s: s["sku"].update(codigo="OUTRO")),
    ("roteiro_etapas", lambda s: s["roteiro"]["etapas"].pop()),
    ("ordem_etapas", lambda s: s["roteiro"]["etapas"][0].update(ordem=99)),
    ("obrigatoriedade", lambda s: s["roteiro"]["etapas"][0].update(obrigatoria=False)),
    ("unidades_etapas", lambda s: s["roteiro"]["etapas"][0].update(unidade_saida="CX")),
    ("apresentacoes", lambda s: s["roteiro"]["parametros"].update(apresentacoes=["PACOTE"])),
    ("unidade_operacional", lambda s: s["roteiro"]["parametros"].update(unidade_operacional="CAIXA")),
    ("exigencia_peso", lambda s: s["roteiro"]["parametros"].update(exige_peso=False)),
    ("regra_encerramento", lambda s: s["roteiro"]["parametros"].update(encerramento="CORTE")),
    ("bandejas_por_caixa", lambda s: s["roteiro"]["parametros"].update(bandejas_por_caixa=10)),
    ("tara_caixa_kg", lambda s: s["roteiro"]["parametros"].update(tara_caixa_kg=0.7)),
])
def test_divergencia_critica_explicita_em_cada_dimensao(dimensao, mutacao):
    # A comparação é pura e não altera nenhum dos objetos recebidos.
    snapshot = snapshot_op_snapshot("Galinha Cortada")
    original = copy.deepcopy(snapshot)
    mutacao(snapshot)
    resultado = reconciliacao.comparar_snapshot({"sku": "Galinha Cortada"}, snapshot)
    ocorrencia = next(item for item in resultado["dimensoes"] if item["dimensao"] == dimensao)
    assert resultado["resultado_geral"] == "DIVERGENCIA"
    assert ocorrencia["resultado"] == "DIVERGENCIA"
    assert ocorrencia["severidade"] == "CRITICA"
    assert original != snapshot


def test_divergencia_critica_nos_fatores_v1_v2():
    snapshot = snapshot_op_snapshot("Galinha Inteira")
    snapshot["roteiro"]["parametros"]["aves_por_pacote"] = {"V1": 1, "V2": 3}
    resultado = reconciliacao.comparar_snapshot({"sku": "Galinha Inteira"}, snapshot)
    ocorrencia = next(item for item in resultado["dimensoes"] if item["dimensao"] == "fatores_conversao")
    assert ocorrencia["resultado"] == "DIVERGENCIA"
    assert ocorrencia["severidade"] == "CRITICA"


def snapshot_op_snapshot(sku):
    legado = representacao_legada.ESPECIFICACOES[sku]
    return {
        "schema_version": 1, "autoridade_operacional": "LEGADO", "modo": "SOMBRA",
        "sku": {"nome": sku, "codigo": legado["codigo"]},
        "roteiro": {
            "parametros": {chave: copy.deepcopy(valor) for chave, valor in legado.items()
                           if chave not in {"codigo", "tipo", "unidade", "etapas"}},
            "etapas": [{
                "ordem": ordem, "codigo": etapa[0], "nome": etapa[1],
                "unidade_entrada": etapa[2], "unidade_saida": etapa[3],
                "obrigatoria": True, "insumos": [],
            } for ordem, etapa in enumerate(legado["etapas"], 1)],
        },
    }


def test_inconclusivo_quando_falta_dado():
    resultado = reconciliacao.comparar_snapshot(
        {"sku": "Galinha Cortada"}, {"sku": {"nome": "Galinha Cortada", "codigo": "LEG-1"}}
    )
    assert resultado["resultado_geral"] == "INCONCLUSIVO"
    assert resultado["dimensoes"][0]["motivo"]


def test_idempotencia_e_historico_sem_apagar_evidencia(banco):
    op_id, primeiro = _criar(banco, "Galinha Cortada")
    with banco.transaction() as conn:
        segundo = reconciliacao.reconciliar_op(conn.cursor(), op_id)
    assert primeiro["id"] == segundo["id"]
    conn = banco.conectar(); cur = conn.cursor()
    row = cur.execute("SELECT * FROM op_config_snapshots WHERE op_id=?", (op_id,)).fetchone()
    alterado = json.loads(row["snapshot_json"])
    alterado["roteiro"]["parametros"]["tara_caixa_kg"] = 0.75
    cur.execute("UPDATE op_config_snapshots SET snapshot_json=? WHERE op_id=?", (json.dumps(alterado), op_id))
    conn.commit()
    with banco.transaction() as tx:
        terceiro = reconciliacao.reconciliar_op(tx.cursor(), op_id)
    assert terceiro["id"] != primeiro["id"]
    assert terceiro["revisao"] == 2
    assert cur.execute("SELECT COUNT(*) n FROM op_config_reconciliacoes WHERE op_id=?", (op_id,)).fetchone()["n"] == 2
    conn.close()


def test_inconclusivo_pode_ser_reexecutado_com_nova_revisao(banco, monkeypatch):
    op_id = _criar_sem_reconciliar(banco, "Galinha Cortada")
    comparar_original = reconciliacao.comparar_snapshot
    monkeypatch.setattr(reconciliacao, "comparar_snapshot", lambda _op, _snapshot: {
        "resultado_geral": "INCONCLUSIVO",
        "dimensoes": [{
            "dimensao": "insumos", "resultado": "INCONCLUSIVO", "severidade": "ALTA",
            "valor_legado": None, "valor_sombra": None, "motivo": "Dado comparável ainda ausente.",
        }],
    })
    primeira = reconciliacao.executar_reconciliacao_segura(op_id, "CRIACAO_OP")
    assert primeira["status"] == "SUCESSO"
    assert primeira["reconciliacao"]["resultado_geral"] == "INCONCLUSIVO"
    monkeypatch.setattr(reconciliacao, "comparar_snapshot", comparar_original)
    segunda = reconciliacao.executar_reconciliacao_segura(op_id, "MANUAL")
    assert segunda["status"] == "SUCESSO"
    assert segunda["reconciliacao"]["resultado_geral"] == "PARIDADE"
    assert segunda["reconciliacao"]["revisao"] == 2
    conn = banco.conectar(); cur = conn.cursor()
    assert [item["resultado_geral"] for item in cur.execute(
        "SELECT resultado_geral FROM op_config_reconciliacoes WHERE op_id=? ORDER BY revisao", (op_id,)
    ).fetchall()] == ["INCONCLUSIVO", "PARIDADE"]
    conn.close()


def test_erro_tecnico_fica_auditado_e_retry_idempotente_recupera(banco, monkeypatch):
    op_id = _criar_sem_reconciliar(banco, "Galinha Inteira")
    original = reconciliacao.reconciliar_op
    monkeypatch.setattr(reconciliacao, "reconciliar_op", lambda *_args, **_kwargs: (_ for _ in ()).throw(TimeoutError("timeout controlado")))
    falha = reconciliacao.executar_reconciliacao_segura(op_id, "CRIACAO_OP")
    assert falha["status"] == "ERRO" and falha["registrado"] is True
    monkeypatch.setattr(reconciliacao, "reconciliar_op", original)
    sucesso = reconciliacao.executar_reconciliacao_segura(op_id, "RETRY")
    repeticao = reconciliacao.executar_reconciliacao_segura(op_id, "RETRY")
    assert sucesso["status"] == repeticao["status"] == "SUCESSO"
    assert sucesso["reconciliacao"]["id"] == repeticao["reconciliacao"]["id"]
    conn = banco.conectar(); cur = conn.cursor()
    estados = [item["status"] for item in cur.execute(
        "SELECT status FROM op_config_reconciliacao_execucoes WHERE op_id=? ORDER BY id", (op_id,)
    ).fetchall()]
    assert estados == ["ERRO", "SUCESSO", "SUCESSO"]
    assert cur.execute("SELECT COUNT(*) n FROM op_config_reconciliacoes WHERE op_id=?", (op_id,)).fetchone()["n"] == 1
    conn.close()


def test_divergencia_nao_autocorrige_nem_escreve_em_modulos_operacionais(banco):
    op_id, _registro = _criar(banco, "Galinha Inteira")
    conn = banco.conectar(); cur = conn.cursor()
    for tabela in ("estoque_eventos", "pa_nao_conformes", "expedicoes", "cmv_eventos",
                   "oee_resultados", "movimentacoes_financeiras"):
        cur.execute(f"CREATE TABLE {tabela}(id INTEGER PRIMARY KEY,valor TEXT)")
        cur.execute(f"INSERT INTO {tabela} VALUES(1,'preservado')")
    snapshot_antes = cur.execute("SELECT snapshot_json FROM op_config_snapshots WHERE op_id=?", (op_id,)).fetchone()["snapshot_json"]
    roteiro_antes = cur.execute("SELECT parametros_json FROM roteiro_versoes ORDER BY id DESC LIMIT 1").fetchone()["parametros_json"]
    op_antes = dict(cur.execute("SELECT * FROM ordens_producao WHERE id=?", (op_id,)).fetchone())
    snapshot_divergente = json.loads(snapshot_antes)
    snapshot_divergente["roteiro"]["parametros"]["aves_por_pacote"] = {"V1": 9, "V2": 9}
    cur.execute("UPDATE op_config_snapshots SET snapshot_json=? WHERE op_id=?", (json.dumps(snapshot_divergente), op_id))
    conn.commit()
    execucao = reconciliacao.executar_reconciliacao_segura(op_id, "FATO_POSTERIOR")
    assert execucao["status"] == "SUCESSO"
    assert execucao["reconciliacao"]["resultado_geral"] == "DIVERGENCIA"
    assert dict(cur.execute("SELECT * FROM ordens_producao WHERE id=?", (op_id,)).fetchone()) == op_antes
    assert cur.execute("SELECT parametros_json FROM roteiro_versoes ORDER BY id DESC LIMIT 1").fetchone()["parametros_json"] == roteiro_antes
    assert cur.execute("SELECT snapshot_json FROM op_config_snapshots WHERE op_id=?", (op_id,)).fetchone()["snapshot_json"] == json.dumps(snapshot_divergente)
    for tabela in ("estoque_eventos", "pa_nao_conformes", "expedicoes", "cmv_eventos", "oee_resultados", "movimentacoes_financeiras"):
        assert cur.execute(f"SELECT valor FROM {tabela}").fetchone()["valor"] == "preservado"
    conn.close()


def test_migration_sqlite_apply_reapply_rollback_reapply_preserva_legado(tmp_path):
    import sqlite3
    conn = sqlite3.connect(tmp_path / "migration.db")
    conn.executescript("""PRAGMA foreign_keys=ON;
        CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,sku TEXT);
        CREATE TABLE op_config_snapshots(id INTEGER PRIMARY KEY,op_id INTEGER UNIQUE);
        INSERT INTO ordens_producao VALUES(1,'Galinha Cortada');
        INSERT INTO op_config_snapshots VALUES(1,1);""")
    raiz = Path(__file__).resolve().parents[1] / "database"
    apply = (raiz / "20260924_fase4_reconciliacao_sombra_sqlite.sql").read_text(encoding="utf-8")
    rollback = (raiz / "20260924_fase4_reconciliacao_sombra_sqlite_rollback.sql").read_text(encoding="utf-8")
    apply_41 = (raiz / "20260925_fase4_1_execucoes_reconciliacao_sqlite.sql").read_text(encoding="utf-8")
    rollback_41 = (raiz / "20260925_fase4_1_execucoes_reconciliacao_sqlite_rollback.sql").read_text(encoding="utf-8")
    conn.executescript(apply); conn.executescript(apply_41); conn.executescript(apply_41)
    conn.executescript(rollback_41); conn.executescript(rollback); conn.executescript(apply); conn.executescript(apply_41)
    assert conn.execute("SELECT sku FROM ordens_producao WHERE id=1").fetchone()[0] == "Galinha Cortada"
    assert conn.execute("SELECT op_id FROM op_config_snapshots WHERE id=1").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='op_config_reconciliacoes'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='op_config_reconciliacao_execucoes'").fetchone()[0] == 1
    conn.close()


def test_visao_administrativa_somente_leitura(monkeypatch):
    from flask import Flask
    from modules.engenharia_produtos import routes as engenharia_routes

    app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[1] / "templates"))
    app.secret_key = "teste"
    engenharia_routes.register_engenharia_produtos_routes(app)
    registro = {
        "id": 1, "op_id": 10, "sku": "Galinha Cortada", "resultado_geral": "PARIDADE",
        "versao_comparacao": 1, "revisao": 1, "executado_em": "2026-09-24 12:00:00",
        "dimensoes_json": "[]", "divergencias_json": "[]",
    }
    monkeypatch.setattr(reconciliacao, "listar_reconciliacoes", lambda filtros: ([registro], {
        "reconciliadas": 1, "paridade": 1, "divergencias": 0, "inconclusivos": 0,
        "ultima_divergencia": None, "sequencia_paridade": 1,
    }))
    monkeypatch.setattr(reconciliacao, "listar_execucoes_tecnicas", lambda filtros: ([], {
        "pendentes": 0, "erros": 0,
    }))
    monkeypatch.setattr(engenharia_routes, "render_template", lambda _nome, **contexto: (
        f"Reconciliações {contexto['registros'][0]['resultado_geral']}"
    ))
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao["usuario_id"] = 1; sessao["perfil"] = "gerencia"; sessao["nome"] = "Teste"
    resposta = cliente.get("/engenharia-produtos/reconciliacoes?resultado=PARIDADE")
    assert resposta.status_code == 200
    assert b"Reconcilia" in resposta.data and b"PARIDADE" in resposta.data
    assert cliente.post("/engenharia-produtos/reconciliacoes").status_code == 405
