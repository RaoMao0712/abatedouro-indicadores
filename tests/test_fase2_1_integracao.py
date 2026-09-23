import sqlite3

import pytest

import database.connection as dbc
from modules.engenharia_produtos import repositories as legado
from modules.engenharia_produtos import representacao_legada
from modules.producao.services import setores_por_sku
from modules.producao.skus_legados import validar_sku_operacional


def test_fase_0_1_fundacao_e_sombra_coexistem_sem_mudar_motor_legado(tmp_path, monkeypatch):
    monkeypatch.setattr(dbc, "DB_NAME", str(tmp_path / "fase2_1.db"))
    monkeypatch.setattr(dbc, "DATABASE_URL", None)
    legado.criar_estrutura()
    conn = dbc.conectar()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES('LEG-1','Galinha Cortada','PRODUTO_ACABADO','Kg','Sim')")
    cursor.execute("INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES('LEG-2','Galinha Inteira','PRODUTO_ACABADO','Un','Sim')")
    cursor.execute("INSERT INTO skus(codigo,nome,tipo_produto,unidade_venda,ativo) VALUES('NOVO','Terceiro SKU','PRODUTO_ACABADO','Un','Sim')")
    cursor.execute("CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,sku TEXT,status TEXT)")
    cursor.execute("INSERT INTO ordens_producao VALUES(1,'Galinha Cortada','Encerrada')")
    for tabela in ("estoque_eventos", "cmv_eventos", "pa_nao_conformes", "expedicoes", "movimentacoes_financeiras"):
        cursor.execute(f"CREATE TABLE {tabela}(id INTEGER PRIMARY KEY,marcador TEXT)")
        cursor.execute(f"INSERT INTO {tabela} VALUES(1,'preservado')")
    conn.commit()
    antes = {
        tabela: [tuple(linha) for linha in cursor.execute(f"SELECT * FROM {tabela}").fetchall()]
        for tabela in ("ordens_producao", "estoque_eventos", "cmv_eventos", "pa_nao_conformes", "expedicoes", "movimentacoes_financeiras")
    }
    conn.close()

    resultado = representacao_legada.aplicar("Teste integrado Fase 2.1")
    assert resultado["comparacao"]["paridade"] is True
    assert "Corte" in setores_por_sku("Galinha Cortada")
    assert "Corte" not in setores_por_sku("Galinha Inteira")
    for invalido in (None, "", "   ", "Terceiro SKU", "LEG-X"):
        with pytest.raises(ValueError):
            validar_sku_operacional(invalido)

    conn = dbc.conectar()
    cursor = conn.cursor()
    tabelas = {linha["name"] for linha in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"sku_versoes", "etapas_catalogo", "roteiro_versoes", "roteiro_etapas", "roteiro_etapa_insumos", "op_config_snapshots"} <= tabelas
    cursor.execute("SELECT nome,parametros_json FROM sku_versoes ORDER BY nome")
    versoes = cursor.fetchall()
    assert [linha["nome"] for linha in versoes] == ["Galinha Cortada", "Galinha Inteira"]
    assert all('"autoridade_operacional":"LEGADO"' in linha["parametros_json"] for linha in versoes)
    assert cursor.execute("SELECT COUNT(*) n FROM op_config_snapshots").fetchone()["n"] == 0
    assert cursor.execute("SELECT COUNT(*) n FROM sku_versoes sv JOIN skus s ON s.id=sv.sku_id WHERE s.codigo='NOVO'").fetchone()["n"] == 0
    for tabela, linhas in antes.items():
        assert [tuple(linha) for linha in cursor.execute(f"SELECT * FROM {tabela}").fetchall()] == linhas
    conn.close()


def test_rollbacks_sqlite_preservam_todas_as_tabelas_legadas(tmp_path):
    caminho = tmp_path / "rollback.db"
    conn = sqlite3.connect(caminho)
    conn.executescript("""
        CREATE TABLE skus(id INTEGER PRIMARY KEY,codigo TEXT);
        CREATE TABLE almoxarifado_insumos(id INTEGER PRIMARY KEY,descricao TEXT);
        CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,sku TEXT);
        CREATE TABLE estoque_eventos(id INTEGER PRIMARY KEY,marcador TEXT);
        CREATE TABLE cmv_eventos(id INTEGER PRIMARY KEY,marcador TEXT);
        INSERT INTO skus VALUES(1,'LEG-1');
        INSERT INTO ordens_producao VALUES(1,'Galinha Cortada');
        INSERT INTO estoque_eventos VALUES(1,'preservado');
        INSERT INTO cmv_eventos VALUES(1,'preservado');
    """)
    raiz = __import__("pathlib").Path(__file__).resolve().parents[1] / "database"
    fase1 = (raiz / "20260922_fase1_fundacao_sku_roteiro_sqlite.sql").read_text(encoding="utf-8")
    fase2 = (raiz / "20260923_fase2_representacao_skus_legados_sqlite.sql").read_text(encoding="utf-8")
    rollback2 = (raiz / "20260923_fase2_representacao_skus_legados_sqlite_rollback.sql").read_text(encoding="utf-8")
    rollback1 = (raiz / "20260922_fase1_fundacao_sku_roteiro_sqlite_rollback.sql").read_text(encoding="utf-8")
    conn.executescript(fase1)
    conn.executescript(fase2)
    conn.executescript(rollback2)
    conn.executescript(rollback1)
    assert conn.execute("SELECT * FROM ordens_producao").fetchall() == [(1, "Galinha Cortada")]
    assert conn.execute("SELECT * FROM estoque_eventos").fetchall() == [(1, "preservado")]
    assert conn.execute("SELECT * FROM cmv_eventos").fetchall() == [(1, "preservado")]
    conn.close()
