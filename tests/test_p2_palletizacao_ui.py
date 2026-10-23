"""P2: contrato HTTP e visual de criação, consulta e identificação de pallets."""

from pathlib import Path

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
    monkeypatch.setattr(routes, "estado_etiqueta_pallet", lambda pallet_id: {
        "ultima_versao": 0, "ultima_impressao": None,
        "desatualizada": False, "proxima_versao": 1,
    })
    def visao(filtros=None, filtros_sem_pallet=None):
        for pallet in armazenados:
            pallet.setdefault("disponibilidade_agregada", "VAZIO")
            pallet.setdefault("alertas", [])
        return {
            "pallets": list(armazenados), "sem_pallet": [],
            "indicadores": {"pallets_ativos": len(armazenados), "pallets_disponiveis": 0,
                            "pallets_com_restricao": 0, "posicoes_palletizadas": 0,
                            "posicoes_sem_pallet": 0, "peso_palletizado": 0, "peso_sem_pallet": 0},
        }
    monkeypatch.setattr(routes, "visao_estoque_por_pallet", visao)
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


def test_p8_rota_protegida_get_sem_mutacao_post_audita_e_exige_motivo(ambiente, monkeypatch):
    cliente, armazenados = ambiente
    pallet = pallet_vazio()
    pallet["totais"]["peso_bruto"] = 0
    armazenados.append(pallet)
    chamadas = []

    def registrar(pallet_id, **dados):
        chamadas.append((pallet_id, dados))
        return {"versao": 1, "tipo": "PRIMEIRA_IMPRESSAO"}

    monkeypatch.setattr(routes, "registrar_impressao_etiqueta", registrar)
    resposta = cliente.get("/expedicao/pallets/1/etiqueta")
    assert resposta.status_code == 200
    assert b"Etiqueta log\xc3\xadstica" in resposta.data
    assert b"data:image/svg+xml;base64," in resposta.data
    assert chamadas == []  # GET é estritamente leitura
    with cliente.session_transaction() as sessao:
        chave = sessao["pallet_1_etiqueta_chave"]
    resposta = cliente.post("/expedicao/pallets/1/etiqueta", data={"idempotency_key": chave})
    assert resposta.status_code == 302 and "versao=1" in resposta.location
    assert chamadas[0][0] == 1 and chamadas[0][1]["idempotency_key"] == chave
    with cliente.session_transaction() as sessao:
        sessao["perfil"] = "qualidade"
    assert cliente.get("/expedicao/pallets/1/etiqueta").status_code == 302


def test_p3_contrato_visual_selecao_em_massa_e_permissao(ambiente, monkeypatch):
    cliente, armazenados = ambiente
    pallet = pallet_vazio()
    pallet["caixas"] = [{
        "caixa_id": 1, "codigo_caixa": "CX-1", "ops": [121], "ops_texto": "121",
        "sku": "Galinha Cortada", "peso_liquido": 22, "condicao": "CONFORME",
        "localizacao_nome": "Câmara A", "status": "Em estoque",
    }]
    pallet["ops"] = [{
        "op_id": 121, "produto": "Galinha Cortada", "quantidade_posicoes": 1,
        "peso": 22, "bandejas": 12, "pacotes": 0, "aves": 0,
    }]
    pallet["totais"].update(caixas=1, peso_liquido=22, bandejas=12)
    armazenados.append(pallet)
    monkeypatch.setattr(routes, "listar_caixas_disponiveis_palletizacao", lambda filtros=None: [{
        "id": 2, "codigo_caixa": "CX-2", "ops": [121], "ops_texto": "121",
        "sku": "Galinha Cortada", "peso_liquido": 14, "condicao": "CONFORME",
        "localizacao_nome": "Câmara A", "status": "Em estoque",
    }])
    monkeypatch.setattr(routes, "listar_pallets_destino", lambda pallet_id: [pallet_vazio(2, "PALT-000002")])
    detalhe = cliente.get("/expedicao/pallets/1?aba=caixas")
    assert detalhe.status_code == 200
    for texto in (b"Adicionar caixas", b"Transferir caixas", b"Remover do pallet", b"Selecionar todas da OP"):
        assert texto in detalhe.data
    adicao = cliente.get("/expedicao/pallets/1/adicionar")
    assert b'data-select-op="121"' in adicao.data and b'data-caixa' in adicao.data
    transferencia = cliente.get("/expedicao/pallets/1/transferir?caixa_ids=1")
    assert transferencia.status_code == 200 and b"PALT-000002" in transferencia.data
    with cliente.session_transaction() as sessao:
        sessao["perfil"] = "qualidade"
    assert cliente.get("/expedicao/pallets/1/adicionar").status_code == 302
    assert b"Adicionar caixas" not in cliente.get("/expedicao/pallets/1?aba=caixas").data


def test_p3_javascript_op_independente_excecao_e_indeterminate():
    javascript = (Path(__file__).resolve().parents[1] / "static" / "palletizacao.js").read_text(encoding="utf-8")
    assert "belongsTo(box, selector.dataset.selectOp)" in javascript
    assert "box.checked = selector.checked" in javascript
    assert "selector.indeterminate = checked > 0 && checked < group.length" in javascript


def test_p5_visao_estoque_hierarquia_filtros_indicadores_e_sem_acoes(ambiente, monkeypatch):
    cliente, _ = ambiente
    caixa = {"codigo_caixa": "CX-10", "sku": "Galinha Cortada", "peso_liquido": 22,
             "unidade_estoque": "CAIXA", "condicao": "CONFORME", "status": "Em estoque",
             "disponibilidade": "DISPONIVEL", "romaneio_ativo_id": None,
             "reserva_ativa": False, "localizacao_nome": "Câmara A"}
    pallet = pallet_vazio()
    pallet.update(disponibilidade_agregada="DISPONIVEL", alertas=["MISTO POR OP"],
                  produtos_texto="Galinha Cortada", condicoes_texto="CONFORME", ops_texto="121")
    pallet["totais"].update(caixas=1, peso_liquido=22, peso_bruto=23, bandejas=12)
    pallet["ops"] = [{"op_id": 121, "produto": "Galinha Cortada", "quantidade_posicoes": 1,
                      "peso": 22, "disponibilidade_agregada": "DISPONIVEL", "caixas": [caixa]}]
    monkeypatch.setattr(routes, "visao_estoque_por_pallet", lambda *args: {
        "pallets": [pallet], "sem_pallet": [dict(caixa, id=20, ops_texto="122")],
        "indicadores": {"pallets_ativos": 1, "pallets_disponiveis": 1,
                        "pallets_com_restricao": 0, "posicoes_palletizadas": 1,
                        "posicoes_sem_pallet": 1, "peso_palletizado": 22, "peso_sem_pallet": 22},
    })
    resposta = cliente.get("/expedicao/pallets?op=121&disponibilidade=DISPONIVEL")
    assert resposta.status_code == 200
    for texto in (b"Estoque por pallet", b"Pallets ativos", b"Limpar filtros", b"Estoque sem pallet",
                  b"OP #121", b"CX-10", b"MISTO POR OP"):
        assert texto in resposta.data
    assert b"Remover do pallet" not in resposta.data


def test_p4_tela_organizacao_selecao_em_massa_criacao_e_retomada(ambiente, monkeypatch):
    cliente, armazenados = ambiente
    armazenados.append(pallet_vazio())
    caixas = [{
        "id": indice, "codigo_caixa": f"CX-{indice}", "unidade_estoque": "CAIXA",
        "peso_liquido": 20, "quantidade_bandejas": 12,
        "quantidade_pacotes": 0, "quantidade_galinhas": 0,
    } for indice in range(1, 4)]
    estado = {"sem_pallet": list(caixas), "pallets": []}

    def resumo(_op_id):
        return {
            "op": {"id": 121, "sku": "Galinha Cortada", "status": "Aberta"},
            "caixas": caixas, "sem_pallet": list(estado["sem_pallet"]),
            "pallets": list(estado["pallets"]),
            "totais": {"posicoes": 3, "peso": 60, "bandejas": 36, "pacotes": 0, "aves": 0},
            "organizadas": 3 - len(estado["sem_pallet"]),
            "nao_organizadas": len(estado["sem_pallet"]),
            "percentual": (3 - len(estado["sem_pallet"])) * 100 / 3,
            "completa": not estado["sem_pallet"],
        }

    monkeypatch.setattr(routes, "buscar_op_por_id", lambda op_id: {"id": op_id, "sku": "Galinha Cortada"})
    monkeypatch.setattr(routes, "resumo_organizacao_op", resumo)

    def adicionar(pallet_id, ids, **_kwargs):
        selecionadas = {int(item) for item in ids}
        estado["sem_pallet"] = [item for item in estado["sem_pallet"] if item["id"] not in selecionadas]
        estado["pallets"] = [{"id": pallet_id, "codigo": "PALT-000001",
                              "totais": {"posicoes": len(selecionadas), "peso": 40,
                                         "bandejas": 24, "pacotes": 0, "aves": 0}}]
        return armazenados[0]

    monkeypatch.setattr(routes, "adicionar_caixas", adicionar)
    pagina = cliente.get("/op/121/pallets/organizar")
    assert pagina.status_code == 200
    for texto in (b"Organiza", b"Selecionar todas", b"CX-1", b"Criar novo pallet"):
        assert texto in pagina.data
    with cliente.session_transaction() as sessao:
        chave = sessao["op_121_palletizacao_chave"]
    resposta = cliente.post("/op/121/pallets/organizar", data={
        "idempotency_key": chave, "pallet_id": "1", "acao": "vincular",
        "caixa_ids": ["1", "2"],
    })
    assert resposta.status_code == 302
    retomada = cliente.get("/op/121/pallets/organizar")
    assert b"1 / 3" not in retomada.data and b"CX-3" in retomada.data

