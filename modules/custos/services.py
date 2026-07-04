"""Servicos do modulo de Custos."""

from . import repositories as repository


CATEGORIAS_CUSTOS = [
    "Mão de obra",
    "Energia",
    "Água",
    "Lenha",
    "Combustível",

    "Manutenção de Equipamentos",
    "Manutenção Predial",
    "Manutenção de Veículos",

    "Material de Limpeza",
    "Material de Escritório",
    "Serviços",

    "EPIs",

    "Marketing",
    "Cursos e Treinamentos",
    "Despesas com Viagens",

    "Consultoria e Responsabilidade Técnica",

    "Contratos com Clientes",

    "Insumos para Produção",

    "Impostos e Taxas",

    "Despesas Financeiras",


    "Outros"
]


def criar_tabelas_custos():
    repository.criar_tabelas_custos()


def buscar_parametros_custos():
    return repository.buscar_parametros_custos()


def buscar_custos_mensais(competencia_inicio=None, competencia_fim=None, categoria=None):
    return repository.buscar_custos_mensais(competencia_inicio, competencia_fim, categoria)


def chave_sku_custo(sku):
    return (
        sku.lower()
        .replace(" ", "_")
        .replace("ã", "a")
    )


def salvar_parametros_custos(form):
    criar_tabelas_custos()

    skus = ["Galinha Cortada", "Galinha Inteira"]

    for sku in skus:
        chave = chave_sku_custo(sku)

        custo_ave = float(form.get(f"custo_ave_{chave}") or 0)
        custo_embalagem = float(form.get(f"custo_embalagem_{chave}") or 0)

        if sku == "Galinha Cortada":
            unidade_custo_ave = "R$/ave"
            unidade_custo_embalagem = "R$/bandeja"
        else:
            unidade_custo_ave = "R$/ave"
            unidade_custo_embalagem = "R$/unidade"

        repository.atualizar_parametro_custo(
            sku,
            custo_ave,
            unidade_custo_ave,
            custo_embalagem,
            unidade_custo_embalagem
        )


def salvar_custo_mensal(form):
    criar_tabelas_custos()
    repository.inserir_custo_mensal(
        form["competencia"],
        form["categoria"],
        float(form["valor"]),
        form.get("observacoes", "")
    )


def salvar_custos_mensais_lote(form):
    criar_tabelas_custos()

    competencia = form["competencia"]
    observacoes_gerais = form.get("observacoes_gerais", "")
    categorias = form.getlist("categoria[]")
    valores = form.getlist("valor[]")
    observacoes = form.getlist("observacoes[]")

    if not categorias:
        raise ValueError("Adicione pelo menos uma linha de custo antes de confirmar.")

    if not (len(categorias) == len(valores) == len(observacoes)):
        raise ValueError("As linhas de custo estao incompletas. Revise categorias, valores e observacoes.")

    linhas = []
    for indice, valor_raw in enumerate(valores, start=1):
        categoria = categorias[indice - 1]
        observacao = observacoes[indice - 1].strip()

        if not categoria:
            raise ValueError(f"Selecione uma categoria na linha {indice}.")

        if categoria not in CATEGORIAS_CUSTOS:
            raise ValueError(f"A categoria da linha {indice} nao e valida.")

        try:
            valor = float(str(valor_raw).replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError(f"Informe um valor valido na linha {indice}.")

        if valor <= 0:
            raise ValueError(f"O valor da linha {indice} precisa ser maior que zero.")

        if observacoes_gerais and observacao:
            observacao_final = f"{observacao} | {observacoes_gerais}"
        else:
            observacao_final = observacao or observacoes_gerais

        linhas.append((competencia, categoria, valor, observacao_final))

    repository.inserir_custos_mensais_lote(linhas)
    return len(linhas)


def buscar_custo_mensal_por_id(custo_id):
    return repository.buscar_custo_mensal_por_id(custo_id)


def atualizar_custo_mensal(custo_id, form):
    repository.atualizar_custo_mensal(
        custo_id,
        form["competencia"],
        form["categoria"],
        float(form["valor"]),
        form.get("observacoes", "")
    )


def excluir_custo_mensal(custo_id):
    repository.excluir_custo_mensal(custo_id)