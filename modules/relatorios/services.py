"""Servicos de relatorios gerenciais."""

from datetime import datetime

from . import repositories as repository
from modules.custos.services import CATEGORIAS_CUSTOS, criar_tabelas_custos


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
