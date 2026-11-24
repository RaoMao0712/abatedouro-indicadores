import sqlite3

import pytest
from flask import Flask

from modules.navegacao.services import montar_navegacao
from modules.producao import repositories
from modules.producao.routes import register_producao_routes


@pytest.fixture
def relatorio(tmp_path, monkeypatch):
    def conectar():
        conexao = sqlite3.connect(tmp_path / "ordens.db")
        conexao.row_factory = sqlite3.Row
        return conexao

    with conectar() as conexao:
        conexao.executescript("""
            CREATE TABLE ordens_producao (
                id INTEGER PRIMARY KEY, status TEXT, sku TEXT, quantidade_aves INTEGER
            );
            INSERT INTO ordens_producao VALUES
                (10, 'Aberta', 'Galinha Cortada', 4321),
                (11, 'Encerrada', 'Galinha Inteira', 7654),
                (12, 'Estornada', 'Galinha Inteira', 9999);
        """)

    monkeypatch.setattr(repositories, "conectar", conectar)
    monkeypatch.setattr(repositories, "q", lambda sql: sql)
    return conectar


def test_relatorio_dados_e_filtros(relatorio):
    def consultar(situacao="", produto="", numero=""):
        ordens, produtos, total, *_ = repositories.consultar_relatorio_ordens(
            situacao, produto, numero, 1,
        )
        return [tuple(ordem) for ordem in ordens], produtos, total

    aberta = (10, "ABERTA", "Galinha Cortada", 4321)
    encerrada = (11, "ENCERRADA", "Galinha Inteira", 7654)
    assert consultar() == ([encerrada, aberta], ["Galinha Cortada", "Galinha Inteira"], 2)
    assert consultar(situacao="ABERTA")[0] == [aberta]
    assert consultar(situacao="ENCERRADA")[0] == [encerrada]
    assert consultar(produto="Galinha Cortada")[0] == [aberta]
    assert consultar(numero="11")[0] == [encerrada]
    assert consultar(numero="1")[2] == 0
    assert consultar(situacao="ABERTA", produto="Galinha Inteira")[2] == 0


def test_relatorio_paginacao_e_impressao(relatorio):
    with relatorio() as conexao:
        conexao.executemany(
            "INSERT INTO ordens_producao VALUES (?, 'Aberta', 'Galinha Cortada', 1)",
            [(numero,) for numero in range(20, 47)],
        )
    primeira, _, total, pagina, paginas = repositories.consultar_relatorio_ordens("", "", "", 1)
    segunda, _, _, _, _ = repositories.consultar_relatorio_ordens("", "", "", 2)
    impressao, _, _, _, _ = repositories.consultar_relatorio_ordens("", "", "", 1, imprimir=True)
    assert (len(primeira), len(segunda), total, pagina, paginas) == (25, 4, 29, 1, 2)
    assert [ordem["id"] for ordem in impressao] == [ordem["id"] for ordem in primeira + segunda]


@pytest.mark.parametrize("perfil", ["admin", "pcp", "qualidade", "producao", "gerencia", "manutencao"])
def test_relatorio_permissao_e_navegacao(relatorio, monkeypatch, perfil):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="teste")
    app.add_url_rule("/login", "login", lambda: "")
    register_producao_routes(app)
    app.url_build_error_handlers.append(lambda erro, endpoint, valores: f"/{endpoint}")
    monkeypatch.setattr("modules.producao.routes.render_template", lambda nome, **_: nome)
    cliente = app.test_client()
    rota = "/producao/relatorio-ordens"
    assert cliente.get(rota).location == "/login"
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=1, perfil="sem_acesso")
    assert cliente.get(rota).location == "/login"
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=1, perfil=perfil)
    assert cliente.get(rota).data == b"relatorio_ordens_producao.html"
    with app.test_request_context(rota):
        navegacao = montar_navegacao(perfil, "relatorio_ordens_producao")
        assert rota in str(navegacao)
