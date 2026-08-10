"""Contratos do relatório oficial de entregas por cliente."""

from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from pypdf import PdfReader

from config import EMPRESA_EMITENTE, MARCA_SISTEMA
from modules.expedicao.relatorio_entregas import (
    _totais_unidades,
    gerar_relatorio_entregas_pdf,
)
from modules.expedicao.routes import register_expedicao_routes


ROOT = Path(__file__).resolve().parents[1]


def _romaneio(indice=1, cliente="Liberaci Silva e Silva", destino="Liberaci", status="Concluído"):
    return {
        "id": indice,
        "numero_romaneio": f"ROM-202608{indice:02d}",
        "data": f"2026-08-{indice:02d}",
        "tipo_saida": "VENDA_DIRETA",
        "tipo_movimentacao": "VENDA_DIRETA",
        "cliente_nome": cliente,
        "cliente_fantasia": None,
        "destino": destino,
        "responsavel": "João da Expedição",
        "criado_por": "PCP",
        "status": status,
        "total_unidades": 5,
        "total_kg": 0,
        "total_itens": 1,
    }


def _pacote(indice=1):
    return {
        "id": indice,
        "caixa_id": indice,
        "sku": "Galinha Inteira",
        "unidade_estoque": "PACOTE",
        "quantidade_unidades": 5,
        "quantidade_pacotes": 5,
        "galinhas_por_pacote": 2,
        "quantidade_galinhas": 10,
        "quantidade_kg": None,
        "apresentacao": "Pacote com 2 galinhas",
        "op_id": 123,
        "lote": f"LOTE-{indice}",
    }


FILTROS = {
    "numero": "",
    "data_inicio": "2026-08-01",
    "data_fim": "2026-08-10",
    "status": "Concluído",
    "tipo": "VENDA_DIRETA",
    "cliente_id": "7",
    "produto": "Galinha",
    "destino": "Liberaci",
}


def test_unidades_incompativeis_ficam_separadas_e_pacotes_exibem_galinhas():
    itens = [
        _pacote(),
        {"unidade_estoque": "CAIXA", "quantidade_caixas": 3, "quantidade_kg": 42.5},
        {"unidade_estoque": "BANDEJA", "quantidade_bandejas": 8},
    ]
    assert _totais_unidades(itens) == {
        "pacotes": 5,
        "galinhas": 10,
        "caixas": 3,
        "bandejas": 8,
    }


def test_pdf_filtrado_traz_11_romaneios_sem_concatenar_cliente_e_destino():
    romaneios = [_romaneio(i) for i in range(1, 12)]
    with patch("modules.expedicao.relatorio_entregas.buscar_itens_expedicao", side_effect=lambda i: [_pacote(i)]):
        pdf = gerar_relatorio_entregas_pdf(
            romaneios, FILTROS, cliente_selecionado="Liberaci Silva e Silva",
            emissao="10/08/2026 às 12:00", usuario="Usuário Ágil",
        )
    leitor = PdfReader(BytesIO(pdf))
    texto = "\n".join(p.extract_text() or "" for p in leitor.pages)
    assert len(leitor.pages) >= 1
    assert texto.count("ROM-202608") == 11
    assert "Cliente: Liberaci Silva e Silva" in texto
    assert "Destino: Liberaci" in texto
    assert "Liberaci Silva e SilvaLiberaci" not in texto
    assert "10 galinhas" in texto
    assert "5 pacotes" in texto


def test_empresa_emitente_oficial_e_marca_frigodatta_ficam_separadas_no_pdf():
    with patch("modules.expedicao.relatorio_entregas.buscar_itens_expedicao", return_value=[_pacote()]):
        pdf = gerar_relatorio_entregas_pdf(
            [_romaneio()], FILTROS, cliente_selecionado="Liberaci Silva e Silva",
            emissao="10/08/2026 às 12:00", usuario="PCP Teste",
        )
    texto = "\n".join(p.extract_text() or "" for p in PdfReader(BytesIO(pdf)).pages)
    assert EMPRESA_EMITENTE == "LF Boratto Abatedouro de Aves Ltda."
    assert EMPRESA_EMITENTE in texto
    assert "FrigoDatta Abatedouro" not in texto
    assert "Frigo" in texto and "Datta" in texto
    assert MARCA_SISTEMA == "FrigoDatta"


def test_pdf_multipagina_repete_cabecalho_e_identificacao_de_pagina():
    romaneios = [_romaneio(i, cliente=f"Cliente {i % 3}") for i in range(1, 41)]
    with patch("modules.expedicao.relatorio_entregas.buscar_itens_expedicao", side_effect=lambda i: [_pacote(i), _pacote(i + 100)]):
        pdf = gerar_relatorio_entregas_pdf(romaneios, {**FILTROS, "cliente_id": None}, usuario="PCP Teste")
    leitor = PdfReader(BytesIO(pdf))
    assert len(leitor.pages) > 1
    for numero, pagina in enumerate(leitor.pages, 1):
        texto = pagina.extract_text() or ""
        assert "Frigo" in texto
        assert f"Página {numero}" in texto
    assert sum((pagina.extract_text() or "").count("Romaneio") for pagina in leitor.pages) >= len(leitor.pages)


def _app():
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    app.secret_key = "teste"
    app.config["TESTING"] = True
    app.add_url_rule("/login", "login", lambda: "login")
    app.add_url_rule("/inicio", "inicio", lambda: "inicio")
    register_expedicao_routes(app)
    return app


def _cliente(app, perfil="pcp"):
    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update({"usuario_id": 1, "nome": "PCP Teste", "perfil": perfil})
    return cliente


def test_endpoint_repassa_exatamente_os_oito_filtros_e_nao_muta_dados():
    app = _app()
    pdf_minimo = b"%PDF-1.4\n%%EOF\n"
    with (
        patch("modules.expedicao.routes.buscar_expedicoes", return_value=[]) as buscar,
        patch("modules.expedicao.routes.listar_clientes", return_value=[{"id": 7, "razao_social": "Liberaci Silva e Silva"}]),
        patch("modules.expedicao.routes.gerar_relatorio_entregas_pdf", return_value=pdf_minimo) as gerar,
    ):
        resposta = _cliente(app).get("/expedicao/relatorio-entregas.pdf", query_string=FILTROS)
    assert resposta.status_code == 200
    assert resposta.mimetype == "application/pdf"
    buscar.assert_called_once_with(
        "2026-08-01", "2026-08-10", "Concluído", "VENDA_DIRETA",
        "", "7", "Galinha", "Liberaci",
    )
    assert gerar.call_args.kwargs["cliente_selecionado"] == "Liberaci Silva e Silva"


def test_usuario_sem_permissao_nao_recebe_pdf():
    app = _app()
    resposta = _cliente(app, "producao").get("/expedicao/relatorio-entregas.pdf")
    assert resposta.status_code == 302
    assert "/inicio" in resposta.headers["Location"]


def test_tela_envia_o_mesmo_formulario_e_separa_cliente_do_destino():
    template = (ROOT / "templates" / "expedicao.html").read_text(encoding="utf-8")
    assert 'formaction="{{ url_for(\'relatorio_entregas_expedicao\') }}"' in template
    assert 'formtarget="_blank"' in template
    assert "Cliente: {{ item.cliente_nome" in template
    assert "Destino: {{ item.destino" in template
    assert "|safe" not in template


def test_relatorios_oficiais_usam_configuracao_central_da_empresa():
    templates = [
        ROOT / "templates" / "manutencao_ordem_impressao.html",
        ROOT / "templates" / "manutencao_ordens_impressao.html",
        ROOT / "templates" / "sgi_consolidado.html",
    ]
    for caminho in templates:
        conteudo = caminho.read_text(encoding="utf-8")
        assert "{{ empresa_emitente }}" in conteudo
        assert "FrigoDatta Abatedouro" not in conteudo

    relatorio = (ROOT / "modules" / "expedicao" / "relatorio_entregas.py").read_text(encoding="utf-8")
    assert "from config import EMPRESA_EMITENTE" in relatorio
    assert "FrigoDatta Abatedouro" not in relatorio

    repositorio_sgi = (ROOT / "modules" / "qualidade" / "repositories.py").read_text(encoding="utf-8")
    assert repositorio_sgi.count("FrigoDatta Abatedouro") == 1
    assert "EMPRESA_EMITENTE_LEGADA" in repositorio_sgi
