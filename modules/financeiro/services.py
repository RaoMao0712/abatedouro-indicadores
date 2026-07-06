"""Plano de Contas Gerencial do FrigoDatta."""


def conta(nome, grupo, natureza, dre, resultado_operacional, fluxo_caixa,
          estoque=False, cmv=False, imobilizado=False, financeiro=False, neutro=False):
    return {
        "nome": nome,
        "grupo": grupo,
        "natureza": natureza,
        "impacta_dre": dre,
        "impacta_resultado_operacional": resultado_operacional,
        "impacta_fluxo_caixa": fluxo_caixa,
        "formacao_estoque": estoque,
        "cmv": cmv,
        "imobilizado": imobilizado,
        "financeiro": financeiro,
        "transferencia_neutro": neutro,
    }


PLANO_CONTAS_GERENCIAL = [
    conta("Venda de Produtos", "Receitas", "Entrada", True, True, True),
    conta("Recebimento de cliente", "Receitas", "Entrada", True, True, True),
    conta("Outras Receitas Operacionais", "Receitas", "Entrada", True, True, True),
    conta("Receitas Financeiras", "Receitas", "Entrada", True, False, True, financeiro=True),
    conta("Receitas Nao Operacionais", "Receitas", "Entrada", True, False, True),
    conta("Aporte", "Transferencias", "Entrada", False, False, True, neutro=True),
    conta("Aportes", "Transferencias", "Entrada", False, False, True, neutro=True),
    conta("Emprestimo recebido", "Financeiro", "Entrada", False, False, True, financeiro=True),
    conta("Outras entradas", "Receitas", "Entrada", True, True, True),

    conta("Galinha Viva", "CMV", "Saida", True, False, True, estoque=True, cmv=True),
    conta("Embalagens", "CMV", "Saida", True, False, True, estoque=True, cmv=True),
    conta("Formacao de Estoque", "CMV", "Saida", False, False, True, estoque=True),
    conta("Consumo de Estoque", "CMV", "Saida", True, False, False, estoque=True, cmv=True),
    conta("Ajuste de Estoque", "CMV", "Saida", True, False, False, estoque=True),
    conta("Insumos para Producao", "CMV", "Saida", True, False, True, estoque=True, cmv=True),

    conta("Mao de Obra", "Despesas Operacionais", "Saida", True, True, True),
    conta("Energia", "Despesas Operacionais", "Saida", True, True, True),
    conta("Agua", "Despesas Operacionais", "Saida", True, True, True),
    conta("Lenha", "Despesas Operacionais", "Saida", True, True, True),
    conta("Combustivel", "Despesas Operacionais", "Saida", True, True, True),
    conta("Manutencao", "Despesas Operacionais", "Saida", True, True, True),
    conta("Manutencao de Equipamentos", "Despesas Operacionais", "Saida", True, True, True),
    conta("Manutencao Predial", "Despesas Operacionais", "Saida", True, True, True),
    conta("Manutencao de Veiculos", "Despesas Operacionais", "Saida", True, True, True),
    conta("Material de Limpeza", "Despesas Operacionais", "Saida", True, True, True),
    conta("Material de Escritorio", "Despesas Operacionais", "Saida", True, True, True),
    conta("Produtos Quimicos", "Despesas Operacionais", "Saida", True, True, True),
    conta("Servicos", "Despesas Operacionais", "Saida", True, True, True),
    conta("Servicos terceiros", "Despesas Operacionais", "Saida", True, True, True),
    conta("Fornecedor", "Despesas Operacionais", "Saida", True, True, True),
    conta("Viagens", "Despesas Operacionais", "Saida", True, True, True),
    conta("Despesas com Viagens", "Despesas Operacionais", "Saida", True, True, True),
    conta("Qualidade", "Despesas Operacionais", "Saida", True, True, True),
    conta("Seguranca do Trabalho", "Despesas Operacionais", "Saida", True, True, True),
    conta("Licencas Operacionais", "Despesas Operacionais", "Saida", True, True, True),
    conta("EPIs", "Despesas Operacionais", "Saida", True, True, True),
    conta("Cursos e Treinamentos", "Despesas Operacionais", "Saida", True, True, True),
    conta("Consultoria e Responsabilidade Tecnica", "Despesas Operacionais", "Saida", True, True, True),
    conta("Contratos com Clientes", "Despesas Operacionais", "Saida", True, True, True),
    conta("Outras Despesas Operacionais", "Despesas Operacionais", "Saida", True, True, True),
    conta("Outras saidas", "Despesas Operacionais", "Saida", True, True, True),

    conta("Impostos", "Resultado Nao Operacional", "Saida", True, False, True),
    conta("Taxas", "Resultado Nao Operacional", "Saida", True, False, True),
    conta("Impostos e Taxas", "Resultado Nao Operacional", "Saida", True, False, True),
    conta("Marketing", "Resultado Nao Operacional", "Saida", True, False, True),
    conta("Despesas Comerciais", "Resultado Nao Operacional", "Saida", True, False, True),
    conta("Comissoes", "Resultado Nao Operacional", "Saida", True, False, True),
    conta("Multas", "Resultado Nao Operacional", "Saida", True, False, True),
    conta("Ganhos Extraordinarios", "Resultado Nao Operacional", "Entrada", True, False, True),
    conta("Perdas Extraordinarias", "Resultado Nao Operacional", "Saida", True, False, True),

    conta("Equipamentos", "Investimentos", "Saida", False, False, True, imobilizado=True),
    conta("Veiculos", "Investimentos", "Saida", False, False, True, imobilizado=True),
    conta("Obras", "Investimentos", "Saida", False, False, True, imobilizado=True),
    conta("Reformas", "Investimentos", "Saida", False, False, True, imobilizado=True),
    conta("Maquinas", "Investimentos", "Saida", False, False, True, imobilizado=True),
    conta("Benfeitorias", "Investimentos", "Saida", False, False, True, imobilizado=True),

    conta("Juros", "Financeiro", "Saida", True, False, True, financeiro=True),
    conta("Tarifas Bancarias", "Financeiro", "Saida", True, False, True, financeiro=True),
    conta("IOF", "Financeiro", "Saida", True, False, True, financeiro=True),
    conta("Emprestimos", "Financeiro", "Saida", False, False, True, financeiro=True),
    conta("Financiamentos", "Financeiro", "Saida", False, False, True, financeiro=True),
    conta("Emprestimos e financiamentos", "Financeiro", "Saida", False, False, True, financeiro=True),
    conta("Despesas Financeiras", "Financeiro", "Saida", True, False, True, financeiro=True),

    conta("Mutuos", "Transferencias", "Neutro", False, False, True, neutro=True),
    conta("Transferencias entre contas", "Transferencias", "Neutro", False, False, True, neutro=True),
    conta("Retiradas", "Transferencias", "Saida", False, False, True, neutro=True),
    conta("Adiantamentos", "Transferencias", "Saida", False, False, True, neutro=True),
]


def _normalizar(texto):
    return (
        (texto or "")
        .strip()
        .lower()
        .replace("ã", "a")
        .replace("á", "a")
        .replace("à", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("ê", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("õ", "o")
        .replace("ú", "u")
        .replace("ç", "c")
    )


INDICE_PLANO_CONTAS = {
    _normalizar(item["nome"]): item
    for item in PLANO_CONTAS_GERENCIAL
}


def listar_plano_contas():
    return PLANO_CONTAS_GERENCIAL


def buscar_conta_gerencial(nome):
    return INDICE_PLANO_CONTAS.get(_normalizar(nome))


def categoria_impacta_resultado_operacional(nome):
    conta_gerencial = buscar_conta_gerencial(nome)
    return bool(conta_gerencial and conta_gerencial["impacta_resultado_operacional"])


def categorias_por_natureza(natureza):
    return [
        item["nome"]
        for item in PLANO_CONTAS_GERENCIAL
        if item["natureza"] == natureza
    ]


def categorias_entradas_financeiras():
    return categorias_por_natureza("Entrada")


def categorias_saidas_financeiras():
    return categorias_por_natureza("Saida")


def categorias_custos_operacionais():
    return [
        item["nome"]
        for item in PLANO_CONTAS_GERENCIAL
        if item["grupo"] == "Despesas Operacionais"
        and item["impacta_resultado_operacional"]
    ]


def agrupar_plano_contas():
    grupos = {}
    for item in PLANO_CONTAS_GERENCIAL:
        grupos.setdefault(item["grupo"], []).append(item)
    return grupos


def diagnostico_categorias_legadas():
    return {
        "duplicadas": [
            "Manutencao / Manutencao de Equipamentos",
            "Viagens / Despesas com Viagens",
            "Impostos / Impostos e Taxas",
            "Emprestimos / Emprestimos e financiamentos",
        ],
        "ambiguas": [
            "Fornecedor",
            "Outras entradas",
            "Outras saidas",
            "Servicos terceiros",
        ],
        "tratamento_incorreto_corrigido": [
            "Marketing fora do Resultado Operacional",
            "Embalagens e Insumos para Producao tratados como CMV/estoque, nao despesa operacional",
            "Despesas Financeiras fora do Resultado Operacional",
            "Investimentos e Imobilizado fora da DRE operacional",
        ],
    }
