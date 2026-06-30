from __future__ import annotations

from typing import Protocol


class ImpressoraEtiqueta(Protocol):
    nome: str

    def imprimir_etiqueta(self, conteudo: str) -> None:
        """Envia uma etiqueta ja formatada para impressao."""
