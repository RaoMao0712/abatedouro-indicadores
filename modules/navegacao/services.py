"""Fonte única da sidebar, dos cards e dos acessos principais."""

from copy import deepcopy

from flask import url_for


PERFIS_CONHECIDOS = ("admin", "pcp", "producao", "qualidade", "manutencao", "gerencia")
TODOS_PERFIS = PERFIS_CONHECIDOS
ADMIN_PCP = ("admin", "pcp")

# Tempos dos Setores: funcionalidade operacional descontinuada — preservada
# para compatibilidade e eventual uso futuro em estudos específicos de tempos
# e gargalos. A rota tempos_setor permanece ativa, mas fora da navegação visível.

NAVEGACAO = [
    {
        "id": "inicio",
        "titulo": "Início",
        "icone": "home",
        "endpoint": "inicio",
        "perfis": TODOS_PERFIS,
        "card": False,
    },
    {
        "id": "gestao",
        "titulo": "Gestão",
        "descricao": "Visão executiva e relatórios oficiais.",
        "icone": "chart",
        "perfis": ADMIN_PCP,
        "card": True,
        "itens": [
            {"titulo": "Dashboard Executivo", "endpoint": "relatorio_gerencial_oficial", "route_args": {"slug": "dashboard-executivo"}, "perfis": ADMIN_PCP, "principal": True},
            {"titulo": "Biblioteca de Relatórios", "endpoint": "biblioteca_relatorios", "perfis": ADMIN_PCP, "principal": True},
            {"titulo": "Indicadores", "endpoint": "relatorio_gerencial_oficial", "route_args": {"slug": "indicadores"}, "perfis": ADMIN_PCP},
            {"titulo": "Comparativos", "endpoint": "relatorio_gerencial_oficial", "route_args": {"slug": "comparativos"}, "perfis": ADMIN_PCP},
            {"titulo": "Tendências", "endpoint": "relatorio_gerencial_oficial", "route_args": {"slug": "tendencias"}, "perfis": ADMIN_PCP},
        ],
    },
    {
        "id": "producao",
        "titulo": "Produção",
        "descricao": "Ordens, apontamentos, embalagem e estoque industrial.",
        "icone": "factory",
        "perfis": TODOS_PERFIS,
        "card": True,
        "itens": [
            {"titulo": "Painel da Produção", "endpoint": "dashboard", "perfis": TODOS_PERFIS, "principal": True},
            {"titulo": "Nova OP", "grupo": "Ordens de Produção", "endpoint": "ordem_producao", "perfis": ADMIN_PCP},
            {
                "titulo": "Consultar OP",
                "grupo": "Ordens de Produção",
                "endpoint": "consultar_op",
                "perfis": ("admin", "pcp", "producao", "qualidade"),
                "principal": True,
                "active_endpoints": (
                    "consultar_op", "editar_op", "imprimir_op", "pesagem_op",
                    "etiqueta_pesagem_op", "cancelar_ultima_pesagem_op",
                    "editar_mao_obra", "editar_mao_obra_lote",
                    "editar_parada", "editar_paradas_lote",
                    "editar_descartes_lote",
                ),
            },
            {"titulo": "Mão de Obra", "grupo": "Apontamentos", "endpoint": "apontamento_mao_obra", "perfis": ("admin", "producao")},
            {"titulo": "Paradas", "grupo": "Apontamentos", "endpoint": "apontamento_paradas", "perfis": ("admin", "producao")},
            {"titulo": "Embalagem Primária", "endpoint": "embalagem_primaria", "perfis": ("admin", "pcp", "producao"), "principal": True},
            {
                "titulo": "Embalagem Secundária",
                "endpoint": "embalagem_secundaria",
                "perfis": ("admin", "pcp", "producao"),
                "active_endpoints": ("embalagem_secundaria", "finalizar_embalagem_secundaria", "resetar_embalagem_secundaria_op"),
            },
            {"titulo": "Estoque PI/PA", "endpoint": "estoque_produtos", "perfis": ("admin", "pcp", "qualidade"), "principal": True},
            {"titulo": "Produtos Não Conformes", "endpoint": "produtos_nao_conformes", "perfis": ("admin", "pcp", "producao", "qualidade")},
        ],
    },
    {
        "id": "qualidade",
        "titulo": "Qualidade",
        "descricao": "Verificações, conformidade e registros de qualidade.",
        "icone": "shield",
        "perfis": ("admin", "pcp", "qualidade", "gerencia"),
        "card": True,
        "itens": [
            {
                "titulo": "Central de Verificações",
                "endpoint": "sgi_qualidade",
                "perfis": ("admin", "pcp", "qualidade", "gerencia"),
                "principal": True,
                "active_endpoints": (
                    "sgi_qualidade", "sgi_nova_verificacao", "sgi_plm01_mensal",
                    "sgi_plm01_imprimir", "sgi_verificacao_detalhe",
                    "sgi_cadastrar_local", "sgi_cadastrar_setor",
                    "sgi_confirmar_reposicao", "sgi_decisao_gerencia",
                    "sgi_validar_eficacia", "sgi_encerrar_nc",
                ),
            },
            {"titulo": "Consolidado Mensal", "endpoint": "sgi_consolidado_mensal", "perfis": ("admin", "pcp", "qualidade", "gerencia")},
            {
                "titulo": "Produtos Não Conformes",
                "endpoint": "produtos_nao_conformes",
                "perfis": ("admin", "pcp", "producao", "qualidade", "gerencia"),
                "principal": True,
                "active_endpoints": ("produtos_nao_conformes", "detalhe_produto_nao_conforme"),
            },
            {
                "titulo": "Validar Liberacoes",
                "endpoint": "validar_liberacoes_pendentes",
                "perfis": ("admin", "gerencia"),
                "active_endpoints": ("validar_liberacoes_pendentes", "validar_liberacao_produto"),
            },
            {
                "titulo": "Descartes e Condenações",
                "endpoint": "apontamento_descartes",
                "perfis": ("admin", "qualidade"),
                "principal": True,
                "active_endpoints": ("apontamento_descartes", "editar_descartes_lote", "excluir_descartes_lote"),
            },
        ],
    },
    {
        "id": "manutencao",
        "titulo": "Manutenção",
        "descricao": "Abertura, consulta e gestão de ordens de serviço.",
        "icone": "tools",
        "perfis": TODOS_PERFIS,
        "card": True,
        "itens": [
            {
                "titulo": "Painel de Ordens de Serviço",
                "endpoint": "manutencao",
                "perfis": TODOS_PERFIS,
                "principal": True,
                "active_endpoints": (
                    "manutencao", "visualizar_ordem_manutencao",
                    "imprimir_ordem_manutencao", "imprimir_relatorio_ordens_manutencao",
                    "abrir_ordem_manutencao_sgi",
                ),
            },
        ],
    },
    {
        "id": "almoxarifado",
        "titulo": "Almoxarifado",
        "descricao": "Insumos, entradas, saldos e rastreabilidade.",
        "icone": "box",
        "perfis": ADMIN_PCP,
        "card": True,
        "itens": [
            {"titulo": "Central", "endpoint": "almoxarifado", "perfis": ADMIN_PCP, "principal": True, "active_endpoints": ("almoxarifado", "editar_insumo_almoxarifado")},
            {"titulo": "Entradas", "endpoint": "entrada_estoque_almoxarifado", "perfis": ADMIN_PCP},
            {"titulo": "Saldos", "endpoint": "saldo_almoxarifado", "perfis": ADMIN_PCP},
            {"titulo": "Movimentações", "endpoint": "movimentacoes_almoxarifado", "perfis": ADMIN_PCP},
            {"titulo": "Rastreabilidade", "endpoint": "rastreabilidade_almoxarifado", "perfis": ADMIN_PCP},
        ],
    },
    {
        "id": "expedicao",
        "titulo": "Expedição",
        "descricao": "Romaneios, estoque operacional e histórico logístico.",
        "icone": "truck",
        "perfis": ("admin", "pcp", "qualidade"),
        "card": True,
        "itens": [
            {"titulo": "Central de Romaneios", "endpoint": "expedicao", "perfis": ("admin", "pcp", "qualidade"), "principal": True, "active_endpoints": ("expedicao", "detalhe_romaneio_expedicao", "imprimir_romaneio_expedicao")},
            {"titulo": "Novo Romaneio", "endpoint": "novo_romaneio_expedicao", "perfis": ("admin", "pcp", "qualidade")},
            {"titulo": "Estoque Operacional", "endpoint": "estoque_camara_expedicao", "perfis": ("admin", "pcp", "qualidade")},
            {"titulo": "Não Conformes", "endpoint": "produtos_nao_conformes", "perfis": ("admin", "pcp", "qualidade")},
            {"titulo": "Histórico", "endpoint": "historico_estoque_expedicao", "perfis": ("admin", "pcp", "qualidade")},
        ],
    },
    {
        "id": "financeiro",
        "titulo": "Financeiro",
        "descricao": "Movimentações, liquidação, caixa e resultado.",
        "icone": "wallet",
        "perfis": ADMIN_PCP,
        "card": True,
        "itens": [
            {
                "titulo": "Central de Movimentações",
                "endpoint": "movimentacoes_entradas",
                "perfis": ADMIN_PCP,
                "principal": True,
                "active_endpoints": ("movimentacoes_entradas", "movimentacoes_despesas", "movimentacoes_estoque", "editar_movimentacao_financeira"),
            },
            {"titulo": "Liquidação", "endpoint": "movimentacoes_liquidacao", "perfis": ADMIN_PCP},
            {"titulo": "Fluxo de Caixa", "endpoint": "fluxo_caixa", "perfis": ADMIN_PCP, "principal": True},
            {"titulo": "DRE Gerencial", "endpoint": "dre_gerencial", "perfis": ADMIN_PCP, "principal": True},
            {"titulo": "Auditoria Financeira", "endpoint": "movimentacoes_auditoria", "perfis": ADMIN_PCP},
            {"titulo": "Pendências", "endpoint": "movimentacoes_pendencias", "perfis": ADMIN_PCP},
            {
                "titulo": "Importações",
                "endpoint": "importar_movimentacoes_financeiras",
                "perfis": ADMIN_PCP,
                "active_endpoints": ("importar_movimentacoes_financeiras", "importar_vendas_financeiras"),
            },
        ],
    },
    {
        "id": "cadastros",
        "titulo": "Cadastros",
        "descricao": "Estruturas de apoio aos fluxos operacionais.",
        "icone": "database",
        "perfis": ("admin", "pcp", "producao", "qualidade", "gerencia"),
        "card": True,
        "itens": [
            {"titulo": "Fornecedores", "endpoint": "fornecedores", "perfis": ADMIN_PCP},
            {"titulo": "Clientes", "endpoint": "clientes", "perfis": ("admin", "gerencia", "pcp")},
            {
                "titulo": "Engenharia de Produtos",
                "endpoint": "engenharia_produtos",
                "perfis": ("admin", "pcp", "producao", "qualidade", "gerencia"),
                "active_endpoints": (
                    "engenharia_produtos", "receitas_sku", "novo_produto", "detalhe_produto",
                    "editar_produto", "processos_produtivos", "novo_item_estrutura",
                    "editar_item_estrutura",
                ),
            },
            {"titulo": "Plano de Contas", "endpoint": "plano_contas_gerencial", "perfis": ADMIN_PCP},
            {"titulo": "Equipamentos", "endpoint": "cadastro_equipamentos_manutencao", "perfis": ("admin", "pcp", "producao"), "active_endpoints": ("cadastro_equipamentos_manutencao", "editar_equipamento_manutencao")},
            {"titulo": "Veículos", "endpoint": "cadastro_veiculos_manutencao", "perfis": ADMIN_PCP},
        ],
    },
    {
        "id": "administracao",
        "titulo": "Administração",
        "descricao": "Administração de acessos.",
        "icone": "settings",
        "perfis": ("admin",),
        "card": False,
        "itens": [
            {"titulo": "Usuários", "endpoint": "cadastrar_usuario", "perfis": ("admin",), "principal": True},
        ],
    },
]


def perfil_autorizado(perfil, perfis):
    return perfil == "admin" or perfil in perfis


def _item_ativo(item, endpoint_atual, view_args):
    endpoints = item.get("active_endpoints", (item["endpoint"],))
    if endpoint_atual not in endpoints:
        return False
    if endpoint_atual != item["endpoint"]:
        return True
    return all(view_args.get(chave) == valor for chave, valor in item.get("route_args", {}).items())


def montar_navegacao(perfil, endpoint_atual="", view_args=None):
    """Filtra e resolve URLs sem criar uma segunda matriz de autorização."""
    view_args = view_args or {}
    navegacao = []

    for definicao in NAVEGACAO:
        if not perfil_autorizado(perfil, definicao["perfis"]):
            continue

        dominio = deepcopy(definicao)
        if dominio.get("endpoint"):
            dominio["url"] = url_for(dominio["endpoint"])
            dominio["ativo"] = endpoint_atual == dominio["endpoint"]
            navegacao.append(dominio)
            continue

        itens = []
        for item_definicao in dominio.get("itens", []):
            if not perfil_autorizado(perfil, item_definicao["perfis"]):
                continue
            item = deepcopy(item_definicao)
            item["url"] = url_for(item["endpoint"], **item.get("route_args", {}))
            item["ativo"] = _item_ativo(item, endpoint_atual, view_args)
            itens.append(item)

        if not itens:
            continue

        dominio["itens"] = itens
        dominio["url"] = itens[0]["url"]
        dominio["ativo"] = any(item["ativo"] for item in itens)
        navegacao.append(dominio)

    return navegacao


def cards_das_areas(navegacao):
    return [dominio for dominio in navegacao if dominio.get("card")]


def acessos_principais(navegacao):
    acessos = []
    for dominio in navegacao:
        for item in dominio.get("itens", []):
            if item.get("principal"):
                acessos.append({
                    "titulo": item["titulo"],
                    "dominio": dominio["titulo"],
                    "icone": dominio["icone"],
                    "url": item["url"],
                })
    return acessos


def nome_perfil(perfil):
    return {
        "admin": "Administrador",
        "pcp": "PCP",
        "producao": "Produção",
        "qualidade": "Qualidade",
        "manutencao": "Manutenção",
        "gerencia": "Gerência",
    }.get(perfil, perfil.title())
