"""Contratos da reestruturação de Receitas dos SKUs."""

from pathlib import Path
import sqlite3

import pytest
from flask import Flask

import database.connection as db_connection
from modules.cadastros.routes import buscar_receitas_sku
from modules.engenharia_produtos import repositories as repo
from modules.engenharia_produtos import services
from modules.engenharia_produtos.routes import register_engenharia_produtos_routes


ROOT = Path(__file__).resolve().parents[1]
USUARIO = {"id": 42, "nome": "Pessoa PCP"}


@pytest.fixture()
def banco(tmp_path, monkeypatch):
    caminho = tmp_path / "engenharia.db"
    monkeypatch.setattr(db_connection, "DB_NAME", str(caminho))
    monkeypatch.setattr(db_connection, "DATABASE_URL", None)
    repo.criar_estrutura()
    conn = db_connection.conectar()
    conn.executemany(
        """INSERT INTO almoxarifado_insumos
           (descricao, categoria, unidade, ativo, observacoes)
           VALUES (?, ?, ?, ?, ?)""",
        [
            ("Filme ativo", "Embalagem", "Un", "Sim", ""),
            ("Filme inativo", "Embalagem", "Un", "Não", ""),
        ],
    )
    conn.commit()
    ativos = conn.execute("SELECT id FROM almoxarifado_insumos WHERE ativo='Sim'").fetchone()["id"]
    inativos = conn.execute("SELECT id FROM almoxarifado_insumos WHERE ativo='Não'").fetchone()["id"]
    conn.close()
    return {"caminho": caminho, "insumo_ativo": ativos, "insumo_inativo": inativos}


def form_produto(codigo="PA-001", nome="Produto Teste", **mudancas):
    dados = {
        "codigo": codigo,
        "nome": nome,
        "tipo_produto": "PRODUTO_ACABADO",
        "unidade_venda": "Kg",
        "ativo": "Sim",
        "observacoes": "Estrutura de teste",
    }
    dados.update(mudancas)
    return dados


def form_item(insumo_id, tipo="FIXO_UNIDADE", **mudancas):
    dados = {
        "insumo_id": str(insumo_id),
        "quantidade": "1.25",
        "unidade": "Un",
        "tipo_consumo": tipo,
        "fator_proporcao": "0.5",
        "percentual_perda": "2.5",
        "observacoes": "Consumo controlado",
        "status": "Ativo",
        "data_vigencia": "2026-07-27",
    }
    dados.update(mudancas)
    return dados


def test_criar_editar_inativar_e_impedir_codigo_duplicado(banco):
    produto_id = services.salvar_produto(form_produto(), USUARIO)
    services.salvar_produto(
        form_produto(nome="Produto Renomeado", observacoes="Editado"),
        USUARIO,
        produto_id,
    )
    produto = services.obter_produto(produto_id)
    assert produto["nome"] == "Produto Renomeado"
    assert produto["observacoes"] == "Editado"

    with pytest.raises(ValueError, match="código"):
        services.salvar_produto(form_produto(nome="Outro produto"), USUARIO)

    assert services.alternar_status_produto(produto_id, USUARIO) == "Não"
    assert services.obter_produto(produto_id)["ativo"] == "Não"
    assert services.alternar_status_produto(produto_id, USUARIO) == "Sim"
    assert services.obter_produto(produto_id)["ativo"] == "Sim"

    historico = repo.listar_historico_produto(produto_id)
    assert {"inclusao", "edicao", "inativacao", "reativacao"} <= {item["acao"] for item in historico}


def test_cadastrar_processo_em_entidade_separada(banco):
    processo_id = services.salvar_processo(
        {
            "codigo": "PROC-CORTE",
            "nome": "Corte",
            "descricao": "Separação das partes",
            "setor": "Sala de cortes",
            "status": "Ativo",
            "observacoes": "",
        },
        USUARIO,
    )
    processos = services.listar_processos()
    assert processos[0]["id"] == processo_id
    assert processos[0]["nome"] == "Corte"
    assert not repo.buscar_produto_por_codigo("PROC-CORTE")


@pytest.mark.parametrize("tipo", list(services.TIPOS_CONSUMO))
def test_todos_os_tipos_de_consumo_sao_aceitos_e_campos_inaplicaveis_sao_limpos(banco, tipo):
    produto_id = services.salvar_produto(form_produto(codigo=f"PA-{tipo}"), USUARIO)
    item_id = services.salvar_item_estrutura(
        form_item(banco["insumo_ativo"], tipo),
        USUARIO,
        produto_id,
    )
    item = repo.buscar_item(item_id)
    assert item["tipo_consumo"] == tipo
    assert (item["fator_proporcao"] is not None) == (tipo in {"PROPORCIONAL", "PERCENTUAL"})
    assert (item["percentual_perda"] is not None) == (tipo == "PERDA_ESPERADA")


def test_adicionar_editar_e_inativar_item_com_historico(banco):
    produto_id = services.salvar_produto(form_produto(), USUARIO)
    item_id = services.salvar_item_estrutura(form_item(banco["insumo_ativo"]), USUARIO, produto_id)
    services.salvar_item_estrutura(
        form_item(banco["insumo_ativo"], "POR_KG", quantidade="2.75", unidade="Kg"),
        USUARIO,
        produto_id,
        item_id,
    )
    item = repo.buscar_item(item_id)
    assert item["quantidade_por_unidade"] == 2.75
    assert item["tipo_consumo"] == "POR_KG"
    assert services.alternar_status_item(produto_id, item_id, USUARIO) == "Inativo"
    assert repo.buscar_item(item_id)["status"] == "Inativo"
    assert {"inclusao", "edicao", "inativacao"} <= {
        evento["acao"] for evento in repo.listar_historico_produto(produto_id)
    }


def test_validacoes_de_quantidade_insumo_status_ids_e_duplicidade(banco):
    produto_id = services.salvar_produto(form_produto(), USUARIO)
    with pytest.raises(ValueError, match="maior|mínimo"):
        services.salvar_item_estrutura(
            form_item(banco["insumo_ativo"], quantidade="0"), USUARIO, produto_id
        )
    with pytest.raises(ValueError, match="não encontrado"):
        services.salvar_item_estrutura(form_item(999999), USUARIO, produto_id)
    with pytest.raises(ValueError, match="inativo"):
        services.salvar_item_estrutura(form_item(banco["insumo_inativo"]), USUARIO, produto_id)
    with pytest.raises(ValueError, match="válido"):
        services.salvar_item_estrutura(form_item("abc"), USUARIO, produto_id)
    with pytest.raises(ValueError, match="Tipo de consumo"):
        services.salvar_item_estrutura(
            form_item(banco["insumo_ativo"], "INVALIDO"), USUARIO, produto_id
        )

    services.salvar_item_estrutura(form_item(banco["insumo_ativo"]), USUARIO, produto_id)
    with pytest.raises(ValueError, match="Já existe"):
        services.salvar_item_estrutura(form_item(banco["insumo_ativo"]), USUARIO, produto_id)


def test_produto_usado_nao_tem_exclusao_fisica(banco):
    produto_id = services.salvar_produto(form_produto(), USUARIO)
    services.salvar_item_estrutura(form_item(banco["insumo_ativo"]), USUARIO, produto_id)
    assert not hasattr(services, "excluir_produto")
    services.alternar_status_produto(produto_id, USUARIO)
    assert services.obter_produto(produto_id)["ativo"] == "Não"
    assert repo.listar_itens(produto_id)


def test_migracao_preserva_receita_legada_e_consulta_existente(tmp_path, monkeypatch):
    caminho = tmp_path / "legado.db"
    conn = sqlite3.connect(caminho)
    conn.executescript("""
        CREATE TABLE almoxarifado_insumos (
            id INTEGER PRIMARY KEY, descricao TEXT, categoria TEXT, unidade TEXT,
            ativo TEXT, observacoes TEXT, criado_em TEXT
        );
        CREATE TABLE skus (
            id INTEGER PRIMARY KEY, nome TEXT UNIQUE, unidade_venda TEXT,
            ativo TEXT, observacoes TEXT, criado_em TEXT
        );
        CREATE TABLE receitas_sku (
            id INTEGER PRIMARY KEY, sku_id INTEGER, insumo_id INTEGER,
            quantidade_por_unidade REAL, tipo_consumo TEXT, observacoes TEXT, criado_em TEXT
        );
        INSERT INTO almoxarifado_insumos VALUES
            (7, 'Caixa legada', 'Embalagem', 'Cx', 'Sim', '', '2025-01-01');
        INSERT INTO skus VALUES
            (3, 'Galinha Legada', 'Kg', 'Sim', 'Preservar', '2025-01-01');
        INSERT INTO receitas_sku VALUES
            (9, 3, 7, 4.5, 'Embalagem secundária - proporcional', 'Preservar', '2025-01-02');
    """)
    conn.commit()
    conn.close()
    monkeypatch.setattr(db_connection, "DB_NAME", str(caminho))
    monkeypatch.setattr(db_connection, "DATABASE_URL", None)

    repo.criar_estrutura()
    produto = repo.buscar_produto(3)
    item = repo.buscar_item(9)
    assert produto["codigo"] == "LEG-3"
    assert produto["nome"] == "Galinha Legada"
    assert item["tipo_consumo"] == "PROPORCIONAL"
    assert item["unidade"] == "Cx"
    receitas = buscar_receitas_sku()
    assert receitas[0]["sku"] == "Galinha Legada"
    assert receitas[0]["itens"][0]["id"] == 9


@pytest.fixture()
def app_rotas(banco):
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    app.secret_key = "teste"
    app.add_url_rule("/", "login", lambda: "login")
    app.add_url_rule("/inicio", "inicio", lambda: "inicio")
    app.add_url_rule("/sair", "sair", lambda: "sair")
    register_engenharia_produtos_routes(app)
    return app


def sessao(client, perfil):
    with client.session_transaction() as session:
        session["usuario_id"] = 10
        session["nome"] = f"Usuário {perfil}"
        session["perfil"] = perfil


@pytest.mark.parametrize("perfil", ["producao", "qualidade"])
def test_producao_e_qualidade_consultam_mas_nao_editam(app_rotas, perfil):
    client = app_rotas.test_client()
    sessao(client, perfil)
    assert client.get("/engenharia-produtos").status_code == 200
    resposta = client.post("/engenharia-produtos/novo", data=form_produto())
    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/inicio")
    assert repo.listar_produtos() == []


@pytest.mark.parametrize("perfil", ["pcp", "gerencia", "admin"])
def test_pcp_gerencia_e_admin_podem_editar(app_rotas, perfil):
    client = app_rotas.test_client()
    sessao(client, perfil)
    resposta = client.post("/engenharia-produtos/novo", data=form_produto())
    assert resposta.status_code == 302
    assert "/engenharia-produtos/" in resposta.headers["Location"]
    assert len(repo.listar_produtos()) == 1
