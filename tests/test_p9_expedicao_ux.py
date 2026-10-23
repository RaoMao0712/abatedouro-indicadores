"""Contratos UX do redesign P9, sem pixel-perfect nem regra de domínio."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def texto(nome):
    return (ROOT / nome).read_text(encoding="utf-8")


def test_navegacao_principal_ordem_estado_ativo_e_acessibilidade():
    nav = texto("templates/_expedicao_tabs.html")
    itens = ["Pallets", "Romaneios", "Estoque", "Não conformes", "Histórico"]
    assert [nav.index(item) for item in itens] == sorted(nav.index(item) for item in itens)
    assert nav.count('aria-current="page"') == 5
    assert 'aria-label="Navegação da Expedição"' in nav


def test_uma_acao_principal_cabecalhos_e_risco_em_mais_acoes():
    for arquivo in ("templates/pallets.html", "templates/expedicao.html",
                    "templates/expedicao_estoque.html", "templates/expedicao_nao_conformes.html"):
        pagina = texto(arquivo)
        assert pagina.count("data-primary-action") == 1
        assert "expedicao_tab=" in pagina
    pallet = texto("templates/pallet_detalhe.html")
    romaneio = texto("templates/romaneio_detalhe.html")
    assert "Mais ações" in pallet and "romaneio-btn-destructive" in pallet
    assert "Mais ações" in romaneio and "romaneio-btn-destructive" in romaneio


def test_hierarquia_status_abas_e_blocos_operacionais():
    pallets = texto("templates/pallets.html")
    detalhe = texto("templates/pallet_detalhe.html")
    romaneio = texto("templates/romaneio_detalhe.html")
    assert all(classe in pallets for classe in ("pallet-level-pallet", "pallet-level-op", "pallet-level-caixas"))
    assert "exp-status" in pallets and "status-{{ pallet.disponibilidade_agregada|lower }}" in pallets
    assert all(rotulo in detalhe for rotulo in ("Visão geral", "Caixas", "OPs", "Movimentações"))
    assert all(bloco in romaneio for bloco in (
        "resumo-romaneio", "itens-romaneio", "selecao-ops", "historico-romaneio",
    ))


def test_adicionar_pallet_preserva_selecao_massa_indeterminate_contador_e_peso():
    pagina = texto("templates/romaneio_adicionar_pallet.html")
    assert "Selecionar todas" in pagina and "Desmarcar todos" in pagina
    assert "mestre.indeterminate" in pagina
    assert "contador.textContent" in pagina
    assert "data-peso" in pagina and "peso.toLocaleString" in pagina
    assert "item.elegivel %}checked" in pagina and "disabled" in pagina


def test_responsividade_foco_e_botoes_consolidados():
    css = texto("static/style.css")
    assert "P9 — sistema visual local da Expedição" in css
    assert ".romaneio-btn-neutral" in css and ".romaneio-btn-destructive" in css
    assert ":focus-visible" in css
    assert "@media(max-width:900px)" in css and "@media(max-width:620px)" in css
    assert ".tabela-responsiva{max-width:100%;overflow-x:auto}" in css


def test_historico_tem_filtros_e_nao_expoe_json_bruto():
    pagina = texto("templates/expedicao_historico.html")
    for filtro in ("pallet", "romaneio", "op", "tipo_evento", "usuario", "data_inicio", "data_fim"):
        assert f'name="{filtro}"' in pagina
    assert "exp-timeline" in pagina
    assert "dados_json" not in pagina
