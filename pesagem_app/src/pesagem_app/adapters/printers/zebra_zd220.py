from __future__ import annotations


class ZebraZD220:
    nome = "Zebra ZD220"

    def __init__(self, destino: str) -> None:
        self.destino = destino

    def imprimir_etiqueta(self, conteudo: str) -> None:
        raise NotImplementedError(
            "Impressao Zebra sera implementada no STEP 2, apos validacao da balanca."
        )
