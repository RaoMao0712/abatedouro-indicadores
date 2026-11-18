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
    necessidades = []
    with localcontext() as contexto:
        contexto.prec = 70
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
                "necessidade_calculada": planejada.quantize(ESCALA, rounding=ROUND_HALF_UP),
            })
    return necessidades
