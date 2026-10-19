"""P2: contrato HTTP e visual de criação, consulta e identificação de pallets."""

import pytest

import app as aplicacao
from modules.expedicao import routes


def pallet_vazio(pallet_id=1, codigo="PALT-000001"):
    return {
        "id": pallet_id, "codigo": codigo, "status": "ABERTO",
        "localizacao_atual_id": 1, "localizacao_nome": "Câmara A",
        "posicao_atual": "A-01", "criado_em": "2026-10-19 10:00:00",
        "criado_por": "PCP", "observacao": None, "caixas": [], "ops": [],
        "totais": {"caixas": 0, "bandejas": 0, "peso_liquido": 0, "pacotes": 0, "aves": 0},
        "produtos": [], "produtos_texto": "-", "ops_texto": "-",
        "condicoes": [], "condicoes_texto": "-", "payload_identificacao": codigo,
    }


@pytest.fixture
def ambiente(monkeypatch):
    armazenados = []

    def criar(**dados):
        existente = next((p for p in armazenados if p["chave"] == dados["idempotency_key"]), None)
        if existente:
            return existente
        pallet = pallet_vazio(len(armazenados) + 1, f"PALT-{len(armazenados) + 1:06d}")
        pallet["chave"] = dados["idempotency_key"]
        armazenados.append(pallet)
        return pallet

    monkeypatch.setattr(routes, "criar_pallet", criar)
    monkeypatch.setattr(routes, "listar_pallets", lambda filtros=None: list(armazenados))
    monkeypatch.setattr(routes, "resumo_pallets", lambda: {
        "total": len(armazenados), "disponiveis": 0, "reservados": 0,
        "em_carregamento": 0, "encerrados": 0,
    })
    monkeypatch.setattr(routes, "listar_locais_pallet", lambda: [{"id": 1, "nome": "Câmara A", "tipo": "interno"}])
    monkeypatch.setattr(routes, "consultar_pallet", lambda pallet_id: next(p for p in armazenados if p["id"] == pallet_id))
    monkeypatch.setattr(routes, "buscar_pallet_por_codigo", lambda codigo: next(
        (p for p in armazenados if p["codigo"].lower() == codigo.strip().lower()), None,
    ))
    monkeypatch.setattr(routes, "listar_eventos_pallet", lambda pallet_id: [{
        "criado_em": "2026-10-19 10:00:00", "tipo_evento": "PALLET_CRIADO",
        "codigo_caixa": None, "pallet_origem_codigo": None,
        "pallet_destino_codigo": None, "usuario": "PCP", "justificativa": None,
    }])
    cliente = aplicacao.app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update(usuario_id=1, perfil="pcp", nome="PCP")
    return cliente, armazenados


def test_a_c_d_h_l_n_criacao_retry_lista_detalhe_historico_e_busca(ambiente):
    cliente, armazenados = ambiente
    formulario = cliente.get("/expedicao/pallets/novo")
    assert formulario.status_code == 200 and b"Criar pallet" in formulario.data
    with cliente.session_transaction() as sessao:
        chave = sessao["pallet_criacao_chave"]
    resposta = cliente.post("/expedicao/pallets/novo", data={
        "idempotency_key": chave, "localizacao_atual_id": "1", "posicao_atual": "A-01",
    })
    assert resposta.status_code == 302 and resposta.location.endswith("/expedicao/pallets/1")
    cliente.post("/expedicao/pallets/novo", data={"idempotency_key": chave})
    assert len(armazenados) == 1
    assert b"PALT-000001" in cliente.get("/expedicao/pallets").data
    detalhe = cliente.get("/expedicao/pallets/1")
    assert b"Este pallet ainda n\xc3\xa3o possui caixas vinculadas" in detalhe.data
    assert b"PALT-000001" in detalhe.data
    historico = cliente.get("/expedicao/pallets/1?aba=movimentacoes")
    assert b"Pallet Criado" in historico.data
    busca = cliente.get("/expedicao/pallets/localizar?codigo=%20palt-000001%20")
    assert busca.status_code == 302 and busca.location.endswith("/expedicao/pallets/1")


def test_m_permissao_consulta_sem_criacao_e_post_rejeitado(ambiente):
    cliente, armazenados = ambiente
    with cliente.session_transaction() as sessao:
        sessao.update(perfil="qualidade")
    lista = cliente.get("/expedicao/pallets")
    assert lista.status_code == 200 and b"Novo pallet" not in lista.data
    assert cliente.post("/expedicao/pallets/novo", data={}).status_code == 302
    assert armazenados == []

