"""Identidade operacional dos SKUs suportados pelo fluxo legado."""

SKU_GALINHA_CORTADA = "Galinha Cortada"
SKU_GALINHA_INTEIRA = "Galinha Inteira"

SKUS_OPERACIONAIS_LEGADOS = frozenset({
    SKU_GALINHA_CORTADA,
    SKU_GALINHA_INTEIRA,
})

SKU_INVENTARIO_LEGADO = {
    "id": 1,
    "codigo": "LEG-1",
    "nome": SKU_GALINHA_CORTADA,
    "apresentacao": "Congelada",
}


def validar_sku_operacional(sku):
    valor = str(sku or "").strip()
    if not valor:
        raise ValueError("A OP deve possuir um SKU operacional explícito.")
    if valor not in SKUS_OPERACIONAIS_LEGADOS:
        raise ValueError(
            f"O SKU '{valor}' não possui suporte no fluxo produtivo atual."
        )
    return valor
