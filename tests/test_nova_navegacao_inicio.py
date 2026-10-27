"""Contratos da nova navegação e da página Início."""

import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DB_NAME"] = str(Path(TEMP_DIR.name) / "navegacao.db")
os.environ.pop("DATABASE_URL", None)

from app import app  # noqa: E402
from modules.navegacao.services import (  # noqa: E402
    NAVEGACAO,
    PERFIS_CONHECIDOS,
    cards_das_areas,
    montar_navegacao,
)


HASH_LOGO_OFICIAL = "c580b0d1cf6606732bab33d2ac07f409f46482b961bfc4d78586fe893e6f1973"


def sessao(client, perfil, nome=None):
    with client.session_transaction() as session:
        session["usuario_id"] = 900
        session["nome"] = nome or f"Usuário {perfil}"
        session["perfil"] = perfil


def html_inicio(perfil):
    client = app.test_client()
    sessao(client, perfil)
    resposta = client.get("/inicio")
    assert resposta.status_code == 200
    return resposta.get_data(as_text=True)


def test_inicio_exige_autenticacao():
    resposta = app.test_client().get("/inicio")
    assert resposta.status_code == 302
    assert urlsplit(resposta.location).path == "/"


def test_todos_os_perfis_conhecidos_chegam_ao_inicio_apos_login():
    for indice, perfil in enumerate(PERFIS_CONHECIDOS, start=1):
        client = app.test_client()
        usuario = {
            "id": indice,
            "nome": f"Pessoa {perfil}",
            "perfil": perfil,
        }
        with patch("modules.auth.routes.autenticar_usuario", return_value=usuario):
            resposta = client.post("/", data={"email": "teste@local", "senha": "teste"})
        assert resposta.status_code == 302
        assert urlsplit(resposta.location).path == "/inicio"


def test_cards_derivam_da_definicao_central_de_navegacao():
    assert NAVEGACAO
    with app.test_request_context("/inicio"):
        navegacao = montar_navegacao("producao", "inicio")
        cards = cards_das_areas(navegacao)

    html = html_inicio("producao")
    for dominio in cards:
        assert f'data-domain="{dominio["id"]}"' in html
        assert dominio["titulo"] in html


def test_cards_e_dominios_respeitam_perfis():
    esperados = {
            "admin": {"gestao", "producao", "qualidade", "manutencao", "compras", "almoxarifado", "expedicao", "financeiro", "cadastros"},
            "pcp": {"gestao", "producao", "qualidade", "manutencao", "compras", "almoxarifado", "expedicao", "financeiro", "cadastros"},
            "producao": {"producao", "manutencao", "compras", "cadastros"},
            "qualidade": {"producao", "qualidade", "manutencao", "compras", "expedicao", "cadastros"},
            "manutencao": {"producao", "manutencao", "compras"},
            "gerencia": {"gestao", "producao", "qualidade", "manutencao", "compras", "almoxarifado", "cadastros"},
    }
    for perfil, dominios in esperados.items():
        html = html_inicio(perfil)
        renderizados = set(re.findall(r'data-domain="([^"]+)"', html))
        assert renderizados == dominios


def test_painel_producao_disponivel_para_todos_os_perfis():
    for perfil in PERFIS_CONHECIDOS:
        client = app.test_client()
        sessao(client, perfil)
        resposta = client.get("/dashboard")
        assert resposta.status_code == 200
        html = resposta.get_data(as_text=True)
        assert "Painel da Produção" in html
        assert "Mapa de origem" in html


def test_custos_e_vendas_ocultos_mas_rotas_preservadas():
    html = html_inicio("pcp")
    assert 'href="/custos"' not in html
    assert 'href="/vendas"' not in html

    client = app.test_client()
    sessao(client, "pcp")
    assert client.get("/custos").status_code == 200
    assert client.get("/vendas").status_code == 200


def test_embalagens_aparecem_para_producao():
    html = html_inicio("producao")
    assert 'href="/embalagem-primaria"' in html
    assert 'href="/embalagem-secundaria"' not in html


def test_tempos_dos_setores_fica_fora_da_navegacao_visivel():
    producao = next(dominio for dominio in NAVEGACAO if dominio["id"] == "producao")
    apontamentos = [
        item["titulo"]
        for item in producao["itens"]
        if item.get("grupo") == "Apontamentos"
    ]
    assert apontamentos == ["Mão de Obra", "Paradas"]
    assert all(item["endpoint"] != "tempos_setor" for item in producao["itens"])

    for perfil in PERFIS_CONHECIDOS:
        html = html_inicio(perfil)
        assert 'href="/tempos-setor"' not in html
        assert ">Tempos<" not in html


def test_tempos_dos_setores_preserva_historico_sem_atalho_operacional():
    template = (ROOT / "templates" / "consultar_op.html").read_text(encoding="utf-8")
    assert "<h2>Tempos dos Setores</h2>" in template
    assert "tempos_setor" in template
    assert "url_for('tempos_setor'" not in template
    assert "Lançar / Editar Tempos" not in template


def test_tempos_setor_permanece_protegido_e_funcional_por_url():
    client = app.test_client()
    resposta = client.get("/tempos-setor")
    assert resposta.status_code == 302
    assert urlsplit(resposta.location).path == "/"

    sessao(client, "producao")
    resposta = client.get("/tempos-setor")
    assert resposta.status_code == 200
    assert "Tempos dos Setores" in resposta.get_data(as_text=True)


def test_editar_op_nao_aparece_para_perfis_sem_permissao():
    template = (ROOT / "templates" / "consultar_op.html").read_text(encoding="utf-8")
    marcador = "href=\"{{ url_for('editar_op'"
    bloco = template[template.index(marcador):template.index("Editar OP") + len("Editar OP")]
    prefixo = template[:template.index(bloco)]
    condicao = prefixo.rsplit("{% if", 1)[-1]
    assert 'session.get("perfil") == "admin"' in condicao
    assert 'session.get("perfil") == "pcp"' in condicao


def test_usuario_perfil_e_sair_ficam_integrados_ao_hero():
    html = html_inicio("admin")
    assert '<header class="fd-topbar">' not in html
    assert 'class="fd-hero-user"' in html
    assert 'class="fd-logout"' in html
    assert '<span>Sair</span>' in html
    assert 'M10 5H5v14h5' in html
    assert '<aside class="fd-sidebar"' not in html


def test_tela_interna_exibe_hero_global_com_inicio_e_voltar():
    client = app.test_client()
    sessao(client, "producao")
    html = client.get("/dashboard").get_data(as_text=True)
    assert '<section class="fd-hero"' in html
    assert '<h1 id="fd-page-title">Painel da Produção</h1>' in html
    assert '<span>Início</span>' in html
    assert 'data-safe-back' in html


def test_tela_interna_exibe_navegacao_local_com_todos_os_itens_autorizados():
    client = app.test_client()
    sessao(client, "admin")
    html = client.get("/cadastros/parceiros").get_data(as_text=True)
    assert 'class="fd-domain-nav"' in html
    assert '>Parceiros</a>' in html
    assert '>Veículos</a>' in html
    assert '>Locais de estoque</a>' in html
    assert '>Usuários</a>' in html
    assert '<aside class="fd-sidebar"' not in html


def test_compras_expoe_somente_rotas_reais_sem_inventar_pedido_ou_recebimento():
    client = app.test_client()
    sessao(client, "admin")
    html = client.get("/compras/requisicoes").get_data(as_text=True)
    assert 'class="fd-domain-nav"' in html
    assert '>Requisições de Compra</a>' in html
    assert '>Pedidos de Compra</a>' not in html
    assert '>Recebimentos</a>' not in html


def test_navegacao_local_respeita_perfil_e_item_ativo():
    client = app.test_client()
    sessao(client, "producao")
    html = client.get("/dashboard").get_data(as_text=True)
    assert 'class="fd-domain-link is-active" aria-current="page">Painel da Produção</a>' in html
    assert '>Nova OP</a>' not in html
    assert '>Mão de Obra</a>' in html


def test_login_institucional_preserva_contrato_de_autenticacao():
    html = app.test_client().get("/").get_data(as_text=True)
    assert 'class="fd-login-shell"' in html
    assert 'class="fd-login-watermark"' in html
    assert 'name="email"' in html
    assert 'name="senha"' in html
    assert 'action=' not in html


def test_dominios_sem_item_autorizado_nao_renderizam():
    html = html_inicio("gerencia")
    assert ">Financeiro<" not in html
    assert ">Cadastros<" in html
    assert "Central de Cadastros" in html
    assert "Fornecedores" not in html
    assert ">Administração<" not in html


def test_links_da_navegacao_renderizada_possuem_rotas_validas():
    for perfil in PERFIS_CONHECIDOS:
        html = html_inicio(perfil)
        caminhos = {
            urlsplit(href).path
            for href in re.findall(r'href="([^"]+)"', html)
            if href.startswith("/") and not href.startswith("/static/")
        }
        adaptador = app.url_map.bind("localhost")
        for caminho in caminhos:
            endpoint, _ = adaptador.match(caminho, method="GET")
            assert endpoint


def test_logo_oficial_e_preservada_no_hero():
    logo = ROOT / "static" / "imagens" / "logo.png"
    assert hashlib.sha256(logo.read_bytes()).hexdigest() == HASH_LOGO_OFICIAL
    html = html_inicio("admin")
    assert 'src="/static/imagens/logo.png' in html
    assert 'class="fd-hero-brand"' in html


def test_pizza_e_mapa_de_origem_permanecem_no_template():
    template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "qualidade-donut" in template
    assert "conic-gradient" in template
    assert "Mapa de origem" in template


def test_voltar_so_aceita_referencia_interna_e_tem_fallback_inicio():
    javascript = (ROOT / "static" / "navigation.js").read_text(encoding="utf-8")
    assert "document.referrer" in javascript
    assert "window.location.origin" in javascript
    assert 'previous.pathname !== "/"' in javascript
    html = html_inicio("admin")
    assert 'aria-disabled="true"' in html
