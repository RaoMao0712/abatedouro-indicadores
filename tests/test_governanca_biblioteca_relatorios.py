from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app import app
from modules.relatorios.almoxarifado import RELATORIOS_ALMOXARIFADO
from modules.relatorios.catalogo import (
    RELATORIOS_OFICIAIS,
    STATUS_CONGELADO,
    STATUS_DEPENDENCIA,
    STATUS_DISPONIVEL,
    STATUS_ESTRUTURACAO,
    STATUS_EVOLUCAO,
    STATUS_FUTURO,
)
from modules.relatorios.expedicao import RELATORIOS_EXPEDICAO
from modules.relatorios.financeiro import RELATORIOS_FINANCEIROS
from modules.relatorios.gerencial import RELATORIOS_GERENCIAIS
from modules.relatorios.producao import RELATORIOS_PRODUCAO


STATUS_VALIDOS = {
    STATUS_DISPONIVEL,
    STATUS_EVOLUCAO,
    STATUS_ESTRUTURACAO,
    STATUS_DEPENDENCIA,
    STATUS_FUTURO,
    STATUS_CONGELADO,
}

DOMINIOS_VALIDOS = {"Financeiro", "Producao", "Almoxarifado", "Expedicao", "Gerencial"}
PRIORIDADES_VALIDAS = {"Alta", "Media", "Baixa"}
FORMATOS_VALIDOS = {"Tela", "Excel", "Impressao", "Catalogo"}

SLUGS_POR_ENDPOINT = {
    "relatorio_financeiro_oficial": set(RELATORIOS_FINANCEIROS),
    "relatorio_producao_oficial": set(RELATORIOS_PRODUCAO),
    "relatorio_almoxarifado_oficial": set(RELATORIOS_ALMOXARIFADO),
    "relatorio_expedicao_oficial": set(RELATORIOS_EXPEDICAO),
    "relatorio_gerencial_oficial": set(RELATORIOS_GERENCIAIS),
}

EXPORT_ENDPOINTS = {
    "relatorio_financeiro_oficial": "relatorio_financeiro_oficial_exportar",
    "relatorio_producao_oficial": "relatorio_producao_oficial_exportar",
    "relatorio_almoxarifado_oficial": "relatorio_almoxarifado_oficial_exportar",
    "relatorio_expedicao_oficial": "relatorio_expedicao_oficial_exportar",
    "relatorio_gerencial_oficial": "relatorio_gerencial_oficial_exportar",
    "dre_gerencial": "exportar_dre_gerencial_excel",
}

ROTAS_FUTURAS_BLOQUEADAS = {
    "/integracoes/sankhya/vendas/importar",
    "/relatorios/expedicao/vendas",
    "/relatorios/expedicao/vendas/exportar",
    "/relatorios/expedicao/rastreabilidade",
    "/relatorios/expedicao/rastreabilidade/exportar",
    "/relatorios/almoxarifado/giro",
    "/relatorios/almoxarifado/fifo",
    "/relatorios/almoxarifado/cmv",
    "/relatorios/producao/oee",
}

RELATORIOS_LEGADOS_PERMITIDOS = {
    "relatorio_rendimento",  # compatibilidade: redireciona para /relatorios/producao/rendimento
    "relatorio_custos",  # requisito gerencial legado fora dos 38, sem substituto 1:1
    "relatorio_viabilidade",  # ferramenta operacional da Qualidade fora dos 38
}

ROTAS_LEGADAS_CLASSIFICADAS = {
    "/relatorio-custos": {
        "endpoint": "relatorio_custos",
        "classificacao": "requisito gerencial legado fora dos 38",
        "marcadores": [
            "Compatibilidade gerencial",
            "custos mensais cadastrados",
            "Não substitui DRE, Fluxo de Caixa, CMV ou relatórios oficiais da Biblioteca.",
        ],
    },
    "/relatorio-viabilidade": {
        "endpoint": "relatorio_viabilidade",
        "classificacao": "ferramenta operacional da Qualidade fora dos 38",
        "marcadores": [
            "Ferramenta operacional",
            "Relatório de Viabilidade de Aves",
            "Esta ferramenta não altera DRE, Fluxo de Caixa, CMV ou indicadores oficiais da Biblioteca.",
        ],
    },
}


def endpoint_names():
    return {rule.endpoint for rule in app.url_map.iter_rules()}


def route_paths():
    return {rule.rule for rule in app.url_map.iter_rules()}


def cliente_autenticado():
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["usuario_id"] = 1
        sess["nome"] = "Teste Governanca"
        sess["perfil"] = "admin"
    return client


def test_catalogo_tem_38_ids_unicos_e_campos_governados():
    ids = [item["id"] for item in RELATORIOS_OFICIAIS]

    assert len(RELATORIOS_OFICIAIS) == 38
    assert len(ids) == len(set(ids))

    for item in RELATORIOS_OFICIAIS:
        assert item["dominio"] in DOMINIOS_VALIDOS
        assert item["status"] in STATUS_VALIDOS
        assert item["prioridade"] in PRIORIDADES_VALIDAS
        assert item["permissao"]
        assert item["dependencias"]
        assert set(item["formatos"]).issubset(FORMATOS_VALIDOS)


def test_itens_disponiveis_tem_endpoint_existente_e_linkavel():
    endpoints = endpoint_names()

    for item in RELATORIOS_OFICIAIS:
        endpoint = item.get("endpoint")
        if item["status"] in {STATUS_DISPONIVEL, STATUS_EVOLUCAO}:
            assert endpoint, item["id"]
            assert endpoint in endpoints, item["id"]

            if endpoint in SLUGS_POR_ENDPOINT:
                slug = item.get("route_args", {}).get("slug")
                assert slug in SLUGS_POR_ENDPOINT[endpoint], item["id"]


def test_itens_bloqueados_nao_geram_link_operacional():
    for item in RELATORIOS_OFICIAIS:
        if item["status"] in {STATUS_ESTRUTURACAO, STATUS_CONGELADO, STATUS_FUTURO}:
            assert item.get("endpoint") is None, item["id"]
            assert item["formatos"] == ["Catalogo"], item["id"]


def test_formatos_anunciados_correspondem_a_rotas_reais():
    endpoints = endpoint_names()

    for item in RELATORIOS_OFICIAIS:
        endpoint = item.get("endpoint")
        formatos = set(item["formatos"])

        assert "PDF" not in formatos, item["id"]

        if "Excel" in formatos:
            assert endpoint in EXPORT_ENDPOINTS, item["id"]
            assert EXPORT_ENDPOINTS[endpoint] in endpoints, item["id"]

        if "Impressao" in formatos:
            assert "PDF" not in formatos, item["id"]


def test_rotas_futuras_continuam_ausentes():
    rotas = route_paths()

    for rota in ROTAS_FUTURAS_BLOQUEADAS:
        assert rota not in rotas


def test_endpoints_nomeados_como_relatorio_estao_no_catalogo_ou_allowlist():
    endpoints_catalogo = {item.get("endpoint") for item in RELATORIOS_OFICIAIS if item.get("endpoint")}
    endpoints_oficiais = endpoints_catalogo | set(EXPORT_ENDPOINTS.values()) | {"biblioteca_relatorios"}
    permitidos = endpoints_oficiais | RELATORIOS_LEGADOS_PERMITIDOS

    suspeitos = {
        rule.endpoint
        for rule in app.url_map.iter_rules()
        if "relatorio" in rule.endpoint
    }

    assert suspeitos.issubset(permitidos)


def test_custos_e_viabilidade_ficam_fora_do_catalogo_oficial():
    ids = {item["id"] for item in RELATORIOS_OFICIAIS}
    endpoints_catalogo = {item.get("endpoint") for item in RELATORIOS_OFICIAIS if item.get("endpoint")}

    assert "relatorio-custos" not in ids
    assert "relatorio-viabilidade" not in ids
    assert "custos" not in ids
    assert "viabilidade" not in ids
    assert "relatorio_custos" not in endpoints_catalogo
    assert "relatorio_viabilidade" not in endpoints_catalogo


def test_custos_e_viabilidade_preservados_sem_redirect_ou_410():
    client = cliente_autenticado()

    for rota, esperado in ROTAS_LEGADAS_CLASSIFICADAS.items():
        resposta = client.get(rota)
        html = resposta.get_data(as_text=True)

        assert resposta.status_code == 200, esperado["classificacao"]
        assert resposta.location is None
        for marcador in esperado["marcadores"]:
            assert marcador in html


def test_custos_e_viabilidade_preservam_autenticacao():
    with app.test_client() as client:
        for rota in ROTAS_LEGADAS_CLASSIFICADAS:
            resposta = client.get(rota)
            assert resposta.status_code == 302
            assert resposta.location == "/"


def test_rendimento_legado_redireciona_sem_loop_para_relatorio_oficial():
    client = cliente_autenticado()

    resposta = client.get(
        "/relatorio-rendimento?data_inicio=2026-07-01&data_fim=2026-07-31",
        follow_redirects=False,
    )

    assert resposta.status_code == 302
    assert resposta.location == "/relatorios/producao/rendimento?data_inicio=2026-07-01&data_fim=2026-07-31"

    destino = client.get(resposta.location)
    assert destino.status_code == 200
    assert "Rendimento legado" not in destino.get_data(as_text=True)


def test_rotas_legadas_classificadas_existem_com_metodo_get():
    rotas = {
        rule.rule: {
            "endpoint": rule.endpoint,
            "methods": rule.methods - {"HEAD", "OPTIONS"},
        }
        for rule in app.url_map.iter_rules()
    }

    for rota, esperado in ROTAS_LEGADAS_CLASSIFICADAS.items():
        assert rota in rotas
        assert rotas[rota]["endpoint"] == esperado["endpoint"]
        assert rotas[rota]["methods"] == {"GET"}


if __name__ == "__main__":
    falhas = []
    for nome, funcao in sorted(globals().items()):
        if nome.startswith("test_") and callable(funcao):
            try:
                funcao()
                print(f"OK {nome}")
            except Exception as erro:
                falhas.append((nome, erro))
                print(f"FAIL {nome}: {erro}")

    if falhas:
        raise SystemExit(1)
