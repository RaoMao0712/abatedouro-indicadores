"""Servicos de relatorios gerenciais."""

from datetime import datetime
from copy import deepcopy
import unicodedata

from . import repositories as repository
from .catalogo import RELATORIOS_OFICIAIS
from modules.custos.services import CATEGORIAS_CUSTOS, criar_tabelas_custos


ORDEM_DOMINIOS_RELATORIOS = [
    "Financeiro",
    "Producao",
    "Almoxarifado",
    "Expedicao",
    "Gerencial",
]

ROTULOS_DOMINIOS_RELATORIOS = {
    "Financeiro": "Financeiro",
    "Producao": "Produção",
    "Almoxarifado": "Estoque e Insumos",
    "Expedicao": "Estoque e Expedição",
    "Gerencial": "Gerencial",
}

PERFIS_POR_DOMINIO = {
    "Financeiro": ("admin", "pcp", "gerencia"),
    "Producao": ("admin", "pcp", "producao", "gerencia"),
    "Almoxarifado": ("admin", "pcp", "producao", "gerencia"),
    "Expedicao": ("admin", "pcp", "qualidade", "gerencia"),
    "Gerencial": ("admin", "pcp", "gerencia"),
}

ORDEM_FINALIDADES = ["Posição atual", "Movimentação", "Análise", "Histórico"]

CALCULABILIDADE = {
    "producao-rendimento": "Calculado sobre pesos oficiais de entrada e saída; exibe N/A sem base comparável.",
    "producao-disponibilidade": "Calculado com os tempos oficiais registrados; exibe N/A quando a base é insuficiente.",
    "producao-performance": "Calculado com produção e tempo operacional oficiais; exibe N/A sem parâmetros suficientes.",
    "producao-oee": "OEE depende de Disponibilidade, Performance e Qualidade calculáveis; componentes ausentes são exibidos como N/A.",
    "almoxarifado-cmv": "CMV calculado pela camada financeira homologada; períodos sem cobertura são identificados como N/A ou parcial.",
    "financeiro-dre-gerencial": "Valores consolidados pela DRE oficial; linhas sem base permanecem explicitamente sem dados.",
}


def _classificar_finalidade(relatorio):
    texto = _normalizar_busca(f"{relatorio.get('id', '')} {relatorio.get('nome', '')}")
    if any(chave in texto for chave in ("historico", "rastreabilidade", "fifo", "tendencia")):
        return "Histórico"
    if any(chave in texto for chave in ("estoque atual", "estoque camara", "contas a pagar", "contas a receber", "saldo")):
        return "Posição atual"
    if any(chave in texto for chave in (
        "entrada", "saida", "producao por", "consumo", "condenacao", "perda",
        "transferencia", "entrega", "receita", "aporte", "venda",
    )):
        return "Movimentação"
    return "Análise"


def _nivel_gerencial(relatorio, finalidade):
    if relatorio.get("dominio") in ("Financeiro", "Gerencial"):
        return "Gerencial"
    if finalidade == "Histórico":
        return "Histórico"
    if finalidade in ("Posição atual", "Movimentação"):
        return "Operacional"
    return "Tático"


def enriquecer_relatorio(relatorio):
    item = deepcopy(relatorio)
    finalidade = _classificar_finalidade(item)
    item["modulo"] = ROTULOS_DOMINIOS_RELATORIOS[item["dominio"]]
    item["tipo"] = finalidade
    item["nivel"] = _nivel_gerencial(item, finalidade)
    item["perfis"] = PERFIS_POR_DOMINIO[item["dominio"]]
    item["permissao"] = ", ".join(item["perfis"])
    item["fonte"] = ", ".join(item.get("dependencias", []))
    item["calculabilidade"] = CALCULABILIDADE.get(item["id"], "Disponível conforme a cobertura da fonte oficial informada.")
    return item


def perfil_pode_acessar_relatorio(perfil, dominio):
    return (perfil or "") in PERFIS_POR_DOMINIO.get(dominio, ())


def listar_relatorios_oficiais(perfil=None):
    relatorios = [enriquecer_relatorio(item) for item in RELATORIOS_OFICIAIS]
    if perfil:
        relatorios = [item for item in relatorios if perfil in item["perfis"]]
    return relatorios


def _normalizar_busca(valor):
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(caractere for caractere in texto if not unicodedata.combining(caractere)).strip().lower()


def _opcoes_unicas(relatorios, campo):
    valores = []

    for relatorio in relatorios:
        valor = relatorio.get(campo) or ""
        if valor and valor not in valores:
            valores.append(valor)

    return valores


def filtrar_relatorios_oficiais(args, perfil=None):
    catalogo_completo = listar_relatorios_oficiais()
    relatorios = listar_relatorios_oficiais(perfil)
    termo = _normalizar_busca(args.get("q"))
    dominio = args.get("modulo") or args.get("dominio") or "Todos"
    tipo = args.get("tipo") or "Todos"
    nivel = args.get("nivel") or "Todos"
    formato = args.get("formato") or "Todos"
    prioridade = args.get("prioridade") or "Todas"
    status = args.get("status") or "Todos"

    filtrados = []

    for relatorio in relatorios:
        texto_busca = _normalizar_busca(" ".join([
            relatorio.get("nome", ""),
            relatorio.get("modulo", ""),
            relatorio.get("objetivo", ""),
            relatorio.get("tipo", ""),
            relatorio.get("nivel", ""),
            " ".join(relatorio.get("dependencias", [])),
        ]))

        if termo and termo not in texto_busca:
            continue
        if dominio != "Todos" and relatorio.get("modulo") != dominio and relatorio.get("dominio") != dominio:
            continue
        if tipo != "Todos" and relatorio.get("tipo") != tipo:
            continue
        if nivel != "Todos" and relatorio.get("nivel") != nivel:
            continue
        if formato != "Todos" and formato not in relatorio.get("formatos", []):
            continue
        if prioridade != "Todas" and relatorio.get("prioridade") != prioridade:
            continue
        if status != "Todos" and relatorio.get("status") != status:
            continue

        filtrados.append(relatorio)

    grupos = []

    for dominio_nome in ORDEM_DOMINIOS_RELATORIOS:
        itens = [item for item in filtrados if item.get("dominio") == dominio_nome]
        if itens:
            subgrupos = []
            for finalidade in ORDEM_FINALIDADES:
                relatorios_finalidade = [item for item in itens if item["tipo"] == finalidade]
                if relatorios_finalidade:
                    subgrupos.append({"finalidade": finalidade, "relatorios": relatorios_finalidade})
            grupos.append({
                "dominio": dominio_nome,
                "modulo": ROTULOS_DOMINIOS_RELATORIOS[dominio_nome],
                "relatorios": itens,
                "finalidades": subgrupos,
            })

    return {
        "relatorios": filtrados,
        "grupos": grupos,
        "total_catalogo": len(catalogo_completo),
        "total_permitido": len(relatorios),
        "total_filtrado": len(filtrados),
        "dominios": [ROTULOS_DOMINIOS_RELATORIOS[item] for item in ORDEM_DOMINIOS_RELATORIOS],
        "tipos": ORDEM_FINALIDADES,
        "niveis": _opcoes_unicas(relatorios, "nivel"),
        "formatos": sorted({formato for item in relatorios for formato in item.get("formatos", [])}),
        "prioridades": _opcoes_unicas(relatorios, "prioridade"),
        "status_opcoes": _opcoes_unicas(relatorios, "status"),
        "filtros": {
            "q": args.get("q") or "",
            "dominio": dominio,
            "tipo": tipo,
            "nivel": nivel,
            "formato": formato,
            "prioridade": prioridade,
            "status": status,
        },
        "matriz_permissoes": [
            {"modulo": ROTULOS_DOMINIOS_RELATORIOS[dominio], "perfis": perfis}
            for dominio, perfis in PERFIS_POR_DOMINIO.items()
        ] if perfil == "admin" else [],
    }


def normalizar_competencia(competencia):
    if not competencia:
        return ""

    competencia = str(competencia).strip()

    if len(competencia) >= 7:
        return competencia[:7]

    return competencia


def listar_competencias_periodo(competencia_inicio, competencia_fim):
    inicio = datetime.strptime(competencia_inicio + "-01", "%Y-%m-%d")
    fim = datetime.strptime(competencia_fim + "-01", "%Y-%m-%d")

    competencias = []
    atual = inicio

    while atual <= fim:
        competencias.append(atual.strftime("%Y-%m"))

        if atual.month == 12:
            atual = atual.replace(year=atual.year + 1, month=1)
        else:
            atual = atual.replace(month=atual.month + 1)

    return competencias


def buscar_dados_relatorio_custos(competencia_inicio, competencia_fim, categoria_filtro="Todas"):
    criar_tabelas_custos()

    competencias = listar_competencias_periodo(
        competencia_inicio,
        competencia_fim
    )

    categoria_filtro = categoria_filtro or "Todas"
    categorias_padrao = CATEGORIAS_CUSTOS

    dados_por_categoria_completo = {
        categoria: {competencia: 0 for competencia in competencias}
        for categoria in categorias_padrao
    }

    registros = repository.buscar_custos_mensais_agrupados(
        competencia_inicio,
        competencia_fim
    )

    categorias_encontradas = set()

    for item in registros:
        competencia = normalizar_competencia(item["competencia"])
        categoria = item["categoria"]
        categorias_encontradas.add(categoria)

        if categoria not in dados_por_categoria_completo:
            dados_por_categoria_completo[categoria] = {
                comp: 0 for comp in competencias
            }

        if competencia in dados_por_categoria_completo[categoria]:
            dados_por_categoria_completo[categoria][competencia] = float(item["total"] or 0)

    categorias_disponiveis = list(categorias_padrao)

    for categoria in sorted(categorias_encontradas):
        if categoria not in categorias_disponiveis:
            categorias_disponiveis.append(categoria)

    if categoria_filtro != "Todas":
        if categoria_filtro not in dados_por_categoria_completo:
            dados_por_categoria_completo[categoria_filtro] = {
                comp: 0 for comp in competencias
            }

        dados_por_categoria = {
            categoria_filtro: dados_por_categoria_completo[categoria_filtro]
        }
    else:
        dados_por_categoria = {
            categoria: dados_por_categoria_completo.get(
                categoria,
                {comp: 0 for comp in competencias}
            )
            for categoria in categorias_disponiveis
        }

    totais_por_categoria = {
        categoria: sum(valores.values())
        for categoria, valores in dados_por_categoria.items()
    }

    totais_por_competencia = {
        competencia: sum(
            dados_por_categoria[categoria].get(competencia, 0)
            for categoria in dados_por_categoria
        )
        for competencia in competencias
    }

    custo_total = sum(totais_por_categoria.values())
    media_mensal = custo_total / len(competencias) if competencias else 0

    maior_categoria = "Sem dados"
    valor_maior_categoria = 0

    if totais_por_categoria:
        maior_categoria = max(
            totais_por_categoria,
            key=lambda categoria: totais_por_categoria[categoria]
        )
        valor_maior_categoria = totais_por_categoria.get(maior_categoria, 0)

        if valor_maior_categoria == 0:
            maior_categoria = "Sem dados"

    maior_crescimento_categoria = "Sem dados"
    maior_crescimento_valor = 0

    for categoria, valores in dados_por_categoria.items():
        lista_valores = [valores.get(comp, 0) for comp in competencias]

        if len(lista_valores) < 2:
            continue

        crescimento = lista_valores[-1] - lista_valores[0]

        if crescimento > maior_crescimento_valor:
            maior_crescimento_valor = crescimento
            maior_crescimento_categoria = categoria

    # Gráfico executivo: exibe apenas as 5 maiores categorias do período
    # e agrupa as demais em "Outras Categorias".
    categorias_com_movimento = [
        categoria
        for categoria, total in sorted(
            totais_por_categoria.items(),
            key=lambda item: item[1],
            reverse=True
        )
        if float(total or 0) > 0
    ]

    categorias_principais = categorias_com_movimento[:5]
    categorias_restantes = categorias_com_movimento[5:]

    datasets = []

    for categoria in categorias_principais:
        valores = dados_por_categoria.get(categoria, {})
        datasets.append({
            "label": categoria,
            "data": [
                round(valores.get(competencia, 0), 2)
                for competencia in competencias
            ]
        })

    if categorias_restantes:
        datasets.append({
            "label": f"Outras Categorias ({len(categorias_restantes)})",
            "data": [
                round(
                    sum(
                        dados_por_categoria.get(categoria, {}).get(competencia, 0)
                        for categoria in categorias_restantes
                    ),
                    2
                )
                for competencia in competencias
            ]
        })

    resumo_categorias = []

    for categoria, total in sorted(
        totais_por_categoria.items(),
        key=lambda item: item[1],
        reverse=True
    ):
        percentual = 0

        if custo_total > 0:
            percentual = (total / custo_total) * 100

        resumo_categorias.append({
            "categoria": categoria,
            "total": round(total, 2),
            "percentual": round(percentual, 2)
        })

    return {
        "competencias": competencias,
        "datasets": datasets,
        "custo_total": round(custo_total, 2),
        "media_mensal": round(media_mensal, 2),
        "maior_categoria": maior_categoria,
        "valor_maior_categoria": round(valor_maior_categoria, 2),
        "maior_crescimento_categoria": maior_crescimento_categoria,
        "maior_crescimento_valor": round(maior_crescimento_valor, 2),
        "totais_por_competencia": totais_por_competencia,
        "resumo_categorias": resumo_categorias,
        "categorias_disponiveis": categorias_disponiveis,
        "categoria_filtro": categoria_filtro
    }
