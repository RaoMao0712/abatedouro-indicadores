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
    "relatorio_custos",  # temporario: fonte legada sem substituto 1:1 validado
    "relatorio_viabilidade",  # temporario: requisito executivo fora dos 38
}


def endpoint_names():
    return {rule.endpoint for rule in app.url_map.iter_rules()}


def route_paths():
    return {rule.rule for rule in app.url_map.iter_rules()}


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
