from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pesagem_app.core.models import (
    LeituraPeso,
    PesagemCaixa,
    Tara,
    UnidadePeso,
    novo_id_pesagem,
)
from pesagem_app.ports.storage import RepositorioPesagens


class PesoInvalidoError(ValueError):
    pass


class LeituraInstavelError(ValueError):
    pass


@dataclass(frozen=True)
class ServicoPesagem:
    repositorio: RepositorioPesagens

    def calcular_peso_liquido(self, leitura: LeituraPeso, tara: Tara) -> Decimal:
        if leitura.unidade != tara.unidade:
            raise PesoInvalidoError("Leitura e tara devem estar na mesma unidade.")

        liquido = leitura.peso_bruto - tara.peso
        if liquido <= Decimal("0"):
            raise PesoInvalidoError("Peso liquido deve ser maior que zero.")

        return liquido.quantize(Decimal("0.001"))

    def registrar_caixa(
        self,
        ordem_producao: str,
        leitura: LeituraPeso,
        tara: Tara,
        conferida: bool,
        operador: str | None = None,
        pallet_id: str | None = None,
    ) -> PesagemCaixa:
        if not leitura.estavel:
            raise LeituraInstavelError("A leitura da balanca ainda nao esta estavel.")

        pesagem = PesagemCaixa(
            id=novo_id_pesagem(),
            ordem_producao=ordem_producao,
            peso_bruto=leitura.peso_bruto,
            tara=tara.peso,
            peso_liquido=self.calcular_peso_liquido(leitura, tara),
            unidade=UnidadePeso(leitura.unidade),
            conferida=conferida,
            registrada_em=leitura.capturado_em,
            operador=operador,
            pallet_id=pallet_id,
            equipamento_origem=leitura.origem,
        )

        self.repositorio.salvar_pesagem(pesagem)
        return pesagem
