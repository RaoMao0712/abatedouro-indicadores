"""Cálculo de necessidades de materiais sem acesso a banco ou estoque."""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP, localcontext

UNIDADES = ("Kg", "Un", "Cx", "L", "Ml", "G", "Pct")
REGRAS = (
    "POR_UNIDADE_PRODUZIDA", "POR_QUANTIDADE_PRODUZIDA", "PERCENTUAL",
    "FIXO_POR_ORDEM", "RAZAO_AGRUPAMENTO",
)
ESCALA = Decimal("0.000001")


def numero(valor, nome, *, aceita_zero=False):
    try:
        resultado = Decimal(str(valor))
        if (
            not resultado.is_finite()
            or resultado < 0
            or (not aceita_zero and not resultado)
            or resultado >= Decimal("1000000000000")
            or resultado != resultado.quantize(ESCALA)
        ):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(f"{nome} deve ter valor válido com até seis casas decimais.") from None
    return resultado


def calcular_necessidades(produto_id, bom, quantidade_planejada):
    """O fator é o divisor nas regras proporcional e de agrupamento.

    Na regra percentual, a quantidade base contém o percentual e o fator
    ajusta a base de incidência. Nas regras unitária e fixa, multiplica o consumo.
    """
    if bom["produto_id"] != produto_id or bom["numero_versao"] < 1:
        raise ValueError("Versão de BOM inválida para o produto.")
    quantidade = numero(quantidade_planejada, "Quantidade planejada")
    return _calcular(bom, quantidade, arredondar=True)


def _calcular(bom, quantidade, *, arredondar):
    necessidades = []
    with localcontext() as contexto:
        contexto.prec = 90
        for item in bom["itens"]:
            if not item["ativo"]:
                continue
            unidade = item["unidade"]
            if unidade not in UNIDADES:
                raise ValueError("Unidade inválida.")
            base = numero(item["quantidade_base"], "Quantidade base")
            fator = numero(item["fator"], "Fator")
            perda = numero(item["perda_prevista_percentual"], "Perda", aceita_zero=True)
            regra = item["regra_calculo"]
            match regra:
                case "POR_UNIDADE_PRODUZIDA":
                    necessidade = quantidade * base * fator
                case "POR_QUANTIDADE_PRODUZIDA":
                    necessidade = quantidade * base / fator
                case "PERCENTUAL":
                    necessidade = quantidade * fator * base / 100
                case "FIXO_POR_ORDEM":
                    necessidade = base * fator
                case "RAZAO_AGRUPAMENTO":
                    necessidade = (quantidade / fator).to_integral_value(rounding=ROUND_CEILING) * base
                case _:
                    raise ValueError("Regra de cálculo inválida.")
            planejada = necessidade * (1 + perda / 100)
            necessidades.append({
                **item,
                "necessidade_calculada": (_arredondar(planejada) if arredondar else planejada),
            })
    return necessidades


MAX_NIVEIS = 24
MAX_COMPONENTES = 10000
CONVERSOES = {
    "Kg": ("massa", Decimal(1000)), "G": ("massa", Decimal(1)),
    "L": ("volume", Decimal(1000)), "Ml": ("volume", Decimal(1)),
}


def _arredondar(quantidade):
    return quantidade.quantize(ESCALA, rounding=ROUND_HALF_UP)


def _converter(quantidade, origem, destino):
    if origem == destino:
        return quantidade
    familia_origem, fator_origem = CONVERSOES.get(origem, (origem, Decimal(1)))
    familia_destino, fator_destino = CONVERSOES.get(destino, (destino, Decimal(1)))
    if familia_origem != familia_destino or origem not in UNIDADES or destino not in UNIDADES:
        raise ValueError(f"Unidades incompatíveis na explosão: {origem} e {destino}.")
    return quantidade * fator_origem / fator_destino


def explodir(versao, quantidade_planejada, resolver, verificar):
    """Expande BOMs ativas fornecidas pelo resolvedor e mantém cada caminho."""
    quantidade = numero(quantidade_planejada, "Quantidade planejada")
    caminhos = []
    terminais = []
    grupos = {}

    def percorrer(atual, quantidade_atual, ancestrais, trilha):
        produto = atual["produto_id"]
        if produto in ancestrais:
            raise ValueError(f"Ciclo detectado na explosão de {atual['produto']}.")
        if len(ancestrais) >= MAX_NIVEIS or quantidade_atual >= Decimal("1e30"):
            raise ValueError("A explosão excedeu o limite seguro de níveis ou quantidade.")
        verificar(atual)
        passo = {"produto": atual["produto"], "bom_id": atual["id"], "versao": atual["numero_versao"]}
        versoes = (*trilha, passo)
        nomes = [f"{etapa['produto']} v{etapa['versao']}" for etapa in versoes]
        for linha in _calcular(atual, quantidade_atual, arredondar=False):
            if len(caminhos) >= MAX_COMPONENTES:
                raise ValueError("A explosão excedeu o limite seguro de componentes.")
            necessidade = linha["necessidade_calculada"]
            filha = resolver(linha)
            registro = {
                **linha, "nivel": len(versoes), "versoes": versoes,
                "caminho": " → ".join([*nomes, linha["componente"]]),
                "necessidade_calculada": _arredondar(necessidade),
            }
            caminhos.append(registro)
            if filha:
                convertida = _converter(necessidade, linha["unidade"], filha["unidade_producao"])
                percorrer(filha, convertida, (*ancestrais, produto), versoes)
                continue
            terminais.append(registro)
            unidade = linha["unidade"]
            familia = CONVERSOES.get(unidade, (unidade, None))[0]
            chave = (linha["componente_produto_id"], linha["componente_insumo_id"], familia)
            grupo = grupos.setdefault(chave, {
                "componente": linha["componente"],
                "componente_produto_id": linha["componente_produto_id"],
                "componente_insumo_id": linha["componente_insumo_id"],
                "unidade": unidade, "quantidade_total": Decimal(0), "origens": [],
            })
            grupo["quantidade_total"] += _converter(necessidade, unidade, grupo["unidade"])
            grupo["origens"].append(registro)

    with localcontext() as contexto:
        contexto.prec = 90
        percorrer(versao, quantidade, (), ())
        for grupo in grupos.values():
            grupo["quantidade_total"] = _arredondar(grupo["quantidade_total"])
    return {"estrutura": caminhos, "detalhados": terminais, "consolidados": list(grupos.values())}
