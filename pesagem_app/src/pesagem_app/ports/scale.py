from __future__ import annotations

from typing import Protocol

from pesagem_app.core.models import LeituraPeso


class Balanca(Protocol):
    nome: str

    def ler_peso(self) -> LeituraPeso:
        """Retorna a leitura atual da balanca."""
