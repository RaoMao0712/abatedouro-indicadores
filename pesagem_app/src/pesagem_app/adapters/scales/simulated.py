from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pesagem_app.core.models import LeituraPeso, UnidadePeso


class BalancaSimulada:
    nome = "Balanca simulada"

    def __init__(self, peso_padrao: Decimal = Decimal("10.000")) -> None:
        self.peso_padrao = peso_padrao

    def ler_peso(self) -> LeituraPeso:
        return LeituraPeso(
            peso_bruto=self.peso_padrao,
            unidade=UnidadePeso.KG,
            estavel=True,
            capturado_em=datetime.now(),
            origem=self.nome,
            bruto_original=str(self.peso_padrao),
        )
