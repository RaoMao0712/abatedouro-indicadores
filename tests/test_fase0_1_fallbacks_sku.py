from pathlib import Path

import pytest
from flask import Flask
from jinja2 import Environment

from modules.producao import routes as producao_routes
from modules.producao.services import setores_por_sku
from modules.producao.skus_legados import validar_sku_operacional


RAIZ = Path(__file__).resolve().parents[1]
INVALIDOS = [None, "", "   ", "Produto Novo", "LEG-X"]


@pytest.mark.parametrize("sku", INVALIDOS)
def test_servico_rejeita_sku_ausente_vazio_ou_desconhecido(sku):
    with pytest.raises(ValueError, match="SKU|suporte"):
        validar_sku_operacional(sku)
    with pytest.raises(ValueError, match="SKU|suporte"):
        setores_por_sku(sku)


@pytest.mark.parametrize("sku", ["", "   ", "Produto Novo", "LEG-X"])
def test_rota_de_criacao_rejeita_sku_invalido_sem_gravar(monkeypatch, sku):
    app = Flask(__name__)
    app.secret_key = "teste-fase-0-1"
    monkeypatch.setattr(producao_routes, "buscar_ordens", lambda: [])
    monkeypatch.setattr(producao_routes, "buscar_fornecedores", lambda: [])
    monkeypatch.setattr(producao_routes, "render_template", lambda *a, **k: "FORMULARIO_INVALIDO")
    producao_routes.register_producao_routes(app)

    cliente = app.test_client()
    with cliente.session_transaction() as sessao:
        sessao.update({"usuario_id": 1, "perfil": "admin", "nome": "Teste"})

    resposta = cliente.post("/ordem-producao", data={"data": "2026-09-23", "sku": sku})
    assert resposta.status_code == 200
    assert resposta.get_data(as_text=True) == "FORMULARIO_INVALIDO"
    with cliente.session_transaction() as sessao:
        mensagens = [mensagem for _categoria, mensagem in sessao.get("_flashes", [])]
    assert mensagens and ("SKU" in mensagens[-1] or "suporte" in mensagens[-1])


@pytest.mark.parametrize("sku", [None, "", "   ", "Produto Novo", "LEG-X"])
def test_template_de_op_exibe_estado_neutro_para_sku_invalido(sku):
    fonte = (RAIZ / "templates" / "ordem_producao.html").read_text(encoding="utf-8")
    linha = next(linha for linha in fonte.splitlines() if "SKU / Processo:</strong>" in linha)
    html = Environment(autoescape=True).from_string(linha).render(op={"sku": sku})
    assert "SKU indisponível" in html
    assert "Galinha Cortada" not in html
    assert "Galinha Inteira" not in html


def test_guardrail_nao_reintroduz_fallbacks_conhecidos():
    extensoes = {".py", ".html", ".js", ".sql"}
    proibidos = (
        "sku or \"Galinha Cortada\"",
        "sku or 'Galinha Cortada'",
        "sku or \"Galinha Inteira\"",
        "sku or 'Galinha Inteira'",
        "COALESCE(o.sku, 'Galinha Cortada')",
        "COALESCE(sku, 'Galinha Cortada')",
        "sku TEXT DEFAULT 'Galinha Cortada'",
    )
    ocorrencias = []
    for caminho in RAIZ.rglob("*"):
        if caminho.suffix not in extensoes or "tests" in caminho.parts or ".git" in caminho.parts:
            continue
        texto = caminho.read_text(encoding="utf-8", errors="ignore")
        for padrao in proibidos:
            if padrao in texto:
                ocorrencias.append(f"{caminho.relative_to(RAIZ)}: {padrao}")
    assert ocorrencias == []
