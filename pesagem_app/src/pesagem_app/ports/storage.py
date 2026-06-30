from __future__ import annotations

from typing import Protocol

from pesagem_app.core.models import PesagemCaixa


class RepositorioPesagens(Protocol):
    def salvar_pesagem(self, pesagem: PesagemCaixa) -> None:
        """Persiste uma pesagem de caixa."""
