from flask import Flask
import pytest

from modules.expedicao import routes


@pytest.fixture
def cliente(monkeypatch):
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY="teste")
    app.add_url_rule("/login", "login", lambda: "")
    app.add_url_rule("/consultar-op", "consultar_op", lambda: "")
    routes.register_expedicao_routes(app)
    monkeypatch.setattr(routes, "_validar_organizacao_encerramento", lambda *args, **kwargs: None)
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=9, perfil="producao", nome="Operador")
    return cliente


@pytest.mark.parametrize("divergencia", [False, True])
def test_consultar_op_retorna_do_encerramento_oficial_secundario(cliente, monkeypatch, divergencia):
    chamadas = []

    def encerrar(op_id, **dados):
        chamadas.append((op_id, dados))
        if divergencia:
            raise ValueError("Balanço de aves divergente em 12 aves.")
        return {"caixas_liberadas": 1, "peso_liquido_total": 10, "bandejas_consumidas": 12}

    monkeypatch.setattr(routes, "finalizar_embalagem_secundaria_op", encerrar)
    resposta = cliente.post("/embalagem-secundaria/123/finalizar", data={
        "retorno_consulta": "1", "conferencia_hash": "hash", "versao_operacional": "2",
    })
    assert resposta.location == "/consultar-op?op_id=123"
    [(op_id, dados)] = chamadas
    assert op_id == 123
    assert dados["exigir_conferencia"]
    assert dados["conferencia_hash"] == "hash"
    assert dados["versao_esperada"] == "2"
    with cliente.session_transaction() as sessao:
        mensagem = sessao["_flashes"][0][1]
    assert ("divergente" if divergencia else "encerrada com sucesso") in mensagem


def test_retorno_da_primaria_preserva_o_servico_existente(cliente, monkeypatch):
    op = {"id": 123, "sku": "Galinha Inteira"}
    monkeypatch.setattr(routes, "buscar_op_por_id", lambda op_id: op)

    def registrar(**dados):
        assert dados["op"] is op
        assert dados["pacotes_1_ave"] == "8"
        raise ValueError("Já possui posições PA vinculadas.")

    monkeypatch.setattr(routes, "registrar_apontamento_embalagem_primaria", registrar)
    resposta = cliente.post("/embalagem-primaria", data={
        "retorno_consulta": "1", "op_id": "123", "pacotes_1_ave": "8",
        "pallet_justificativa": "Motivo de teste",
    })
    assert resposta.location == "/consultar-op?op_id=123"
    with cliente.session_transaction() as sessao:
        assert "posições PA vinculadas" in sessao["_flashes"][0][1]
