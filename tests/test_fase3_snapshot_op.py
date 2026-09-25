import json
from pathlib import Path

import pytest

import database.connection as dbc
from modules.engenharia_produtos import representacao_legada
from modules.engenharia_produtos import repositories as repo
from modules.engenharia_produtos import snapshot_op
from modules.producao.protecao_sku_op import validar_alteracao_sku


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    monkeypatch.setattr(dbc, "DB_NAME", str(tmp_path / "fase3.db"))
    monkeypatch.setattr(dbc, "DATABASE_URL", None)
    repo.criar_estrutura()
    conn = dbc.conectar()
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE ordens_producao(
        id INTEGER PRIMARY KEY AUTOINCREMENT,sku TEXT,status TEXT
    )""")
    cursor.execute("""INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo)
        VALUES('LEG-1','Galinha Cortada','PRODUTO_ACABADO','Kg','Sim')""")
    cursor.execute("""INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo)
        VALUES('LEG-2','Galinha Inteira','PRODUTO_ACABADO','Un','Sim')""")
    cursor.execute("""INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo)
        VALUES('NOVO','Terceiro SKU','PRODUTO_ACABADO','Un','Sim')""")
    cursor.execute("INSERT INTO ordens_producao(sku,status) VALUES('Galinha Cortada','Encerrada')")
    conn.commit()
    conn.close()
    representacao_legada.aplicar("Teste Fase 3")
    return dbc


def _nova_op_e_snapshot(banco, sku):
    with banco.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO ordens_producao(sku,status) VALUES(?, 'Aberta')", (sku,))
        op_id = cursor.lastrowid
        snapshot_op.gravar_snapshot(cursor, op_id, sku, 7, "Teste")
    return op_id


@pytest.mark.parametrize("sku,codigo,etapas", [
    ("Galinha Cortada", "LEG-1", 7),
    ("Galinha Inteira", "LEG-2", 5),
])
def test_nova_op_legada_cria_snapshot_autossuficiente(banco, sku, codigo, etapas):
    op_id = _nova_op_e_snapshot(banco, sku)
    conn = banco.conectar()
    row = conn.execute("SELECT * FROM op_config_snapshots WHERE op_id=?", (op_id,)).fetchone()
    dados = json.loads(row["snapshot_json"])
    assert row["schema_version"] == snapshot_op.SCHEMA_VERSION
    assert dados["sku"]["codigo"] == codigo
    assert dados["sku"]["nome"] == sku
    assert dados["autoridade_operacional"] == "LEGADO"
    assert dados["modo"] == "SOMBRA"
    assert len(dados["roteiro"]["etapas"]) == etapas
    assert [item["ordem"] for item in dados["roteiro"]["etapas"]] == list(range(1, etapas + 1))
    assert all("insumos" in item for item in dados["roteiro"]["etapas"])
    parametros = dados["roteiro"]["parametros"]
    assert parametros["encerramento"] in {"EMBALAGEM_PRIMARIA", "EMBALAGEM_SECUNDARIA"}
    assert "apresentacoes" in parametros and "exige_peso" in parametros
    conn.close()


def test_idempotencia_e_unicidade_por_op(banco):
    with banco.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO ordens_producao(sku,status) VALUES('Galinha Cortada','Aberta')")
        op_id = cursor.lastrowid
        primeiro = snapshot_op.gravar_snapshot(cursor, op_id, "Galinha Cortada", 1, "Teste")
        segundo = snapshot_op.gravar_snapshot(cursor, op_id, "Galinha Cortada", 1, "Teste")
        assert primeiro["id"] == segundo["id"]
    conn = banco.conectar()
    assert conn.execute("SELECT COUNT(*) n FROM op_config_snapshots WHERE op_id=?", (op_id,)).fetchone()["n"] == 1
    conn.close()


@pytest.mark.parametrize("sku", [None, "", "   ", "Terceiro SKU", "LEG-X"])
def test_sku_invalido_nao_gera_snapshot(banco, sku):
    conn = banco.conectar()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO ordens_producao(sku,status) VALUES(?, 'Aberta')", (sku,))
    op_id = cursor.lastrowid
    with pytest.raises(ValueError, match="SKU|suporte"):
        snapshot_op.gravar_snapshot(cursor, op_id, sku, 1, "Teste")
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) n FROM op_config_snapshots").fetchone()["n"] == 0
    conn.close()


def test_falha_de_snapshot_reverte_op_na_mesma_transacao(banco, monkeypatch):
    def falhar(*_args, **_kwargs):
        raise ValueError("falha controlada")

    monkeypatch.setattr(snapshot_op, "montar_snapshot", falhar)
    with pytest.raises(ValueError, match="falha controlada"):
        with banco.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO ordens_producao(sku,status) VALUES('Galinha Cortada','Aberta')")
            snapshot_op.gravar_snapshot(cursor, cursor.lastrowid, "Galinha Cortada")
    conn = banco.conectar()
    assert conn.execute("SELECT COUNT(*) n FROM ordens_producao").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) n FROM op_config_snapshots").fetchone()["n"] == 0
    conn.close()


def test_snapshot_bloqueia_troca_de_sku_mesmo_em_op_virgem(banco):
    op_id = _nova_op_e_snapshot(banco, "Galinha Cortada")
    conn = banco.conectar()
    with pytest.raises(ValueError, match="snapshot de configuração imutável") as erro:
        validar_alteracao_sku(conn.cursor(), op_id, "Galinha Cortada", "Galinha Inteira")
    assert erro.value.fatos_operacionais == ["op_config_snapshots"]
    conn.close()


def test_alteracoes_posteriores_nao_recalculam_snapshot(banco):
    op_id = _nova_op_e_snapshot(banco, "Galinha Cortada")
    conn = banco.conectar()
    cursor = conn.cursor()
    original = cursor.execute(
        "SELECT snapshot_json FROM op_config_snapshots WHERE op_id=?", (op_id,)
    ).fetchone()["snapshot_json"]
    cursor.execute("UPDATE roteiro_versoes SET observacoes='alteração posterior'")
    cursor.execute("UPDATE ordens_producao SET status='Encerrada' WHERE id=?", (op_id,))
    cursor.execute("UPDATE ordens_producao SET status='Aberta' WHERE id=?", (op_id,))
    cursor.execute("UPDATE ordens_producao SET status='Estornada' WHERE id=?", (op_id,))
    conn.commit()
    assert cursor.execute(
        "SELECT snapshot_json FROM op_config_snapshots WHERE op_id=?", (op_id,)
    ).fetchone()["snapshot_json"] == original
    conn.close()


def test_op_historica_nao_recebe_snapshot_e_novos_fluxos_nao_escrevem_operacao(banco):
    conn = banco.conectar()
    cursor = conn.cursor()
    assert cursor.execute("SELECT COUNT(*) n FROM op_config_snapshots WHERE op_id=1").fetchone()["n"] == 0
    for tabela in ("estoque_eventos", "cmv_eventos", "pa_nao_conformes", "expedicoes", "movimentacoes_financeiras"):
        cursor.execute(f"CREATE TABLE {tabela}(id INTEGER PRIMARY KEY, marcador TEXT)")
        cursor.execute(f"INSERT INTO {tabela} VALUES(1,'preservado')")
    conn.commit()
    antes = {tabela: cursor.execute(f"SELECT COUNT(*) n FROM {tabela}").fetchone()["n"] for tabela in (
        "estoque_eventos", "cmv_eventos", "pa_nao_conformes", "expedicoes", "movimentacoes_financeiras"
    )}
    conn.close()
    _nova_op_e_snapshot(banco, "Galinha Inteira")
    conn = banco.conectar()
    for tabela, quantidade in antes.items():
        assert conn.execute(f"SELECT COUNT(*) n FROM {tabela}").fetchone()["n"] == quantidade
    conn.close()


def test_guardrail_snapshot_nao_eh_lido_pelo_motor_operacional():
    raiz = Path(__file__).resolve().parents[1] / "modules"
    permitidos = {
        raiz / "engenharia_produtos" / "snapshot_op.py",
        raiz / "engenharia_produtos" / "fundacao.py",
        raiz / "engenharia_produtos" / "reconciliacao.py",
    }
    ocorrencias = []
    for caminho in raiz.rglob("*.py"):
        if caminho in permitidos:
            continue
        texto = caminho.read_text(encoding="utf-8")
        if "snapshot_json" in texto and "op_config_snapshots" in texto:
            ocorrencias.append(str(caminho.relative_to(raiz)))
    assert ocorrencias == []
