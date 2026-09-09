import json
import sqlite3
from pathlib import Path

import pytest

import database.connection as db
import modules.clientes.services as clientes
import modules.parceiros.services as parceiros
import modules.pedidos_venda.services as pedidos


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = str(tmp_path / "p3-4.sqlite")
    monkeypatch.setattr(db, "DB_NAME", caminho)
    monkeypatch.setattr(db, "DATABASE_URL", None)
    monkeypatch.setattr(clientes, "DATABASE_URL", None)
    monkeypatch.setattr(parceiros, "DATABASE_URL", None)
    monkeypatch.setattr(pedidos, "DATABASE_URL", None)
    pedidos._SCHEMA_INICIALIZADO = False
    conn = sqlite3.connect(caminho)
    conn.executescript("""
      CREATE TABLE apontamentos_mao_obra(id INTEGER PRIMARY KEY,op_id INTEGER,data TEXT,colaborador TEXT,funcao TEXT,setor TEXT);
      CREATE TABLE expedicoes(id INTEGER PRIMARY KEY,data TEXT,tipo_movimentacao TEXT,status TEXT,
        cliente_id INTEGER,cliente_snapshot TEXT);
      CREATE TABLE ordens_producao(id INTEGER PRIMARY KEY,data TEXT,fornecedor TEXT,gta TEXT);
      CREATE TABLE fornecedores(id INTEGER PRIMARY KEY AUTOINCREMENT,nome TEXT NOT NULL);
    """)
    conn.close()
    clientes.criar_tabelas_clientes()
    parceiros.criar_tabelas_parceiros()
    yield caminho
    pedidos._SCHEMA_INICIALIZADO = False


def executar(caminho, sql, params=()):
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    conn.execute(sql, params)
    conn.commit()
    conn.close()


def consultar(caminho, sql, params=()):
    conn = sqlite3.connect(caminho)
    conn.row_factory = sqlite3.Row
    linhas = [dict(x) for x in conn.execute(sql, params).fetchall()]
    conn.close()
    return linhas


def cliente(caminho, nome="Cliente Teste", documento=None, status="Ativo"):
    agora = "2026-09-09 08:00:00"
    executar(caminho, """INSERT INTO clientes(razao_social,nome_fantasia,tipo_pessoa,documento,status,
      criado_por,atualizado_por,criado_em,atualizado_em) VALUES(?,?,?,?,?,?,?,?,?)""",
      (nome, nome, "PJ", documento, status, "Teste", "Teste", agora, agora))
    return consultar(caminho, "SELECT max(id) id FROM clientes")[0]["id"]


def fornecedor(caminho, nome="Granja Teste", documento=None, status="Ativo"):
    executar(caminho, "INSERT INTO fornecedores(nome,documento,status,tipo_pessoa) VALUES(?,?,?,'PJ')",
             (nome, documento, status))
    return consultar(caminho, "SELECT max(id) id FROM fornecedores")[0]["id"]


def parceiro(caminho, nome, documento=None, status="Ativo", papeis=()):
    agora = "2026-09-09 08:00:00"
    executar(caminho, """INSERT INTO parceiros(uuid,tipo_pessoa,razao_social,documento,status,
      criado_por,atualizado_por,criado_em,atualizado_em) VALUES(hex(randomblob(16)),'PJ',?,?,?,?,?,?,?)""",
      (nome, documento, status, "Teste", "Teste", agora, agora))
    pid = consultar(caminho, "SELECT max(id) id FROM parceiros")[0]["id"]
    for papel in papeis:
        executar(caminho, "INSERT INTO parceiro_papeis(parceiro_id,papel,ativo,adicionado_por,adicionado_em) VALUES(?,?,1,'Teste',?)",
                 (pid, papel, agora))
    return pid


def test_01_02_cliente_e_fornecedor_sem_parceiro_criam_cadastro(banco):
    cid, fid = cliente(banco), fornecedor(banco)
    resumo = parceiros.migrar_clientes_fornecedores_legados(executor="pytest")
    assert resumo["criados"] == 2 and resumo["migrados"] == 2
    assert consultar(banco, "SELECT parceiro_id FROM clientes WHERE id=?", (cid,))[0]["parceiro_id"]
    assert consultar(banco, "SELECT parceiro_id FROM fornecedores WHERE id=?", (fid,))[0]["parceiro_id"]


def test_03_04_correspondencias_por_documento_sao_reutilizadas(banco):
    p1 = parceiro(banco, "Cliente Existente", "12345678000190")
    p2 = parceiro(banco, "Fornecedor Existente", "98765432000110")
    cid = cliente(banco, "Outro nome", "12.345.678/0001-90")
    fid = fornecedor(banco, "Outro fornecedor", "98.765.432/0001-10")
    resumo = parceiros.migrar_clientes_fornecedores_legados(executor="pytest")
    assert resumo["criados"] == 0
    assert consultar(banco, "SELECT parceiro_id FROM clientes WHERE id=?", (cid,))[0]["parceiro_id"] == p1
    assert consultar(banco, "SELECT parceiro_id FROM fornecedores WHERE id=?", (fid,))[0]["parceiro_id"] == p2


def test_05_23_26_mesmo_documento_gera_um_parceiro_com_dois_papeis(banco):
    cliente(banco, "Empresa Dupla", "12345678000190")
    fornecedor(banco, "Empresa Dupla", "12.345.678/0001-90")
    parceiros.migrar_clientes_fornecedores_legados(executor="pytest")
    assert len(consultar(banco, "SELECT * FROM parceiros")) == 1
    assert {x["papel"] for x in consultar(banco, "SELECT papel FROM parceiro_papeis")} == {"CLIENTE", "FORNECEDOR"}
    assert consultar(banco, "SELECT count(*) n FROM parceiro_migracoes_legado")[0]["n"] == 2


def test_06_registro_sem_documento_usa_nome_exato_normalizado(banco):
    pid = parceiro(banco, "São Pedro Km 30")
    fid = fornecedor(banco, "  SAO   PEDRO KM 30  ")
    parceiros.migrar_clientes_fornecedores_legados(executor="pytest")
    assert consultar(banco, "SELECT parceiro_id FROM fornecedores WHERE id=?", (fid,))[0]["parceiro_id"] == pid


def test_07_migracao_dupla_e_idempotente(banco):
    cliente(banco); fornecedor(banco)
    parceiros.migrar_clientes_fornecedores_legados(executor="primeira")
    primeira = [len(consultar(banco, f"SELECT * FROM {t}")) for t in ("parceiros", "parceiro_papeis", "parceiro_migracoes_legado")]
    parceiros.migrar_clientes_fornecedores_legados(executor="segunda")
    assert primeira == [len(consultar(banco, f"SELECT * FROM {t}")) for t in ("parceiros", "parceiro_papeis", "parceiro_migracoes_legado")]


def test_08_rollback_e_conservador_e_sem_drop_de_legado():
    raiz = Path(__file__).parents[1] / "database"
    for nome in ("20260909_p3_4_migracao_clientes_fornecedores_parceiros_rollback.sql",
                 "20260909_p3_4_migracao_clientes_fornecedores_parceiros_sqlite_rollback.sql"):
        texto = (raiz / nome).read_text(encoding="utf-8").upper()
        assert "DROP TABLE CLIENTES" not in texto and "DROP TABLE FORNECEDORES" not in texto
        assert "NOT EXISTS" in texto


@pytest.mark.parametrize("papel,ativo,em_clientes,em_fornecedores", [
    ("CLIENTE", True, True, False), ("FORNECEDOR", True, False, True),
    ("PRESTADOR_SERVICOS", True, False, False), ("CLIENTE", False, False, False),
    ("FORNECEDOR", False, False, False),
])
def test_09_10_11_16_17_18_24_listas_oficiais_respeitam_papel_e_status(
        banco, papel, ativo, em_clientes, em_fornecedores):
    pid = parceiro(banco, f"Parceiro {papel} {ativo}", status="Ativo" if ativo else "Inativo", papeis=(papel,))
    assert (pid in {x["id"] for x in parceiros.listar_clientes_ativos()}) is em_clientes
    assert (pid in {x["id"] for x in parceiros.listar_fornecedores_ativos()}) is em_fornecedores


def test_12_13_14_19_20_21_26_historicos_e_snapshots_permanecem(banco):
    cid, fid = cliente(banco), fornecedor(banco)
    snapshot = json.dumps({"razao_social": "Nome da época", "valor": 12345})
    executar(banco, "INSERT INTO expedicoes(id,data,cliente_id,cliente_snapshot) VALUES(1,'2026-01-01',?,?)", (cid, snapshot))
    executar(banco, "INSERT INTO ordens_producao(id,data,fornecedor,gta) VALUES(1,'2026-01-01','Granja Teste','GTA-001')")
    parceiros.migrar_clientes_fornecedores_legados(executor="pytest")
    exp = consultar(banco, "SELECT * FROM expedicoes WHERE id=1")[0]
    op = consultar(banco, "SELECT * FROM ordens_producao WHERE id=1")[0]
    assert exp["cliente_snapshot"] == snapshot and exp["cliente_parceiro_id"]
    assert op["fornecedor"] == "Granja Teste" and op["gta"] == "GTA-001" and op["fornecedor_parceiro_id"]


def test_15_22_32_rotas_antigas_nao_gravam_legado():
    clientes_src = (Path(__file__).parents[1] / "modules/clientes/routes.py").read_text(encoding="utf-8")
    fornecedores_src = (Path(__file__).parents[1] / "modules/cadastros/routes.py").read_text(encoding="utf-8")
    assert "salvar_cliente(" not in clientes_src
    assert "INSERT INTO fornecedores" not in fornecedores_src
    assert "url_for(\"novo_parceiro\"" in clientes_src and "url_for(\"novo_parceiro\"" in fornecedores_src


def test_25_documento_e_papel_nao_duplicam(banco):
    cliente(banco, documento="12345678000190"); fornecedor(banco, documento="12345678000190")
    parceiros.migrar_clientes_fornecedores_legados(executor="pytest")
    assert consultar(banco, "SELECT documento,count(*) n FROM parceiros GROUP BY documento HAVING count(*)>1") == []
    assert consultar(banco, "SELECT parceiro_id,papel,count(*) n FROM parceiro_papeis GROUP BY parceiro_id,papel HAVING count(*)>1") == []


def test_27_28_29_menu_tem_somente_parceiros():
    from modules.navegacao.services import NAVEGACAO
    titulos = [item["titulo"] for grupo in NAVEGACAO for item in grupo.get("itens", [])]
    assert "Parceiros" in titulos and "Clientes" not in titulos and "Fornecedores" not in titulos


def test_30_31_rotas_legadas_sao_redirects():
    raiz = Path(__file__).parents[1]
    clientes_src = (raiz / "modules/clientes/routes.py").read_text(encoding="utf-8")
    fornecedores_src = (raiz / "modules/cadastros/routes.py").read_text(encoding="utf-8")
    assert "redirect(url_for(\"parceiros\", papel=\"CLIENTE\"))" in clientes_src
    assert "redirect(url_for(\"parceiros\", papel=\"FORNECEDOR\"))" in fornecedores_src


def test_ambiguidade_e_conflito_de_status_ficam_auditados(banco):
    parceiro(banco, "Nome Ambíguo"); parceiro(banco, "NOME AMBIGUO")
    cliente(banco, "Nome Ambíguo")
    pid = parceiro(banco, "Inativo divergente", "11222333000181", status="Inativo")
    fornecedor(banco, "Ativo divergente", "11222333000181", status="Ativo")
    resumo = parceiros.migrar_clientes_fornecedores_legados(executor="pytest")
    assert resumo["ambiguos"] == 1 and resumo["conflitos"] == 1
    resultados = {x["resultado"] for x in consultar(banco, "SELECT resultado FROM parceiro_migracoes_legado")}
    assert resultados == {"AMBIGUO", "CONFLITO_STATUS"}
    assert consultar(banco, "SELECT status FROM parceiros WHERE id=?", (pid,))[0]["status"] == "Inativo"
