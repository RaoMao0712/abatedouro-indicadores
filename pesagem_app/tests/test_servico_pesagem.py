from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from decimal import Decimal

from pesagem_app.core.models import LeituraPeso, PesagemCaixa, Tara, UnidadePeso
from pesagem_app.core.services import LeituraInstavelError, ServicoPesagem


@dataclass
class RepositorioMemoria:
    pesagens: list[PesagemCaixa] = field(default_factory=list)

    def salvar_pesagem(self, pesagem: PesagemCaixa) -> None:
        self.pesagens.append(pesagem)


class ServicoPesagemTest(unittest.TestCase):
    def test_calcula_peso_liquido_descontando_tara(self) -> None:
        repositorio = RepositorioMemoria()
        servico = ServicoPesagem(repositorio)
        leitura = LeituraPeso(Decimal("12.350"), UnidadePeso.KG, True)
        tara = Tara(Decimal("0.850"))

        pesagem = servico.registrar_caixa("OP-001", leitura, tara, conferida=True)

        self.assertEqual(pesagem.peso_liquido, Decimal("11.500"))
        self.assertEqual(len(repositorio.pesagens), 1)

    def test_rejeita_leitura_instavel(self) -> None:
        repositorio = RepositorioMemoria()
        servico = ServicoPesagem(repositorio)
        leitura = LeituraPeso(Decimal("12.350"), UnidadePeso.KG, False)
        tara = Tara(Decimal("0.850"))

        with self.assertRaises(LeituraInstavelError):
            servico.registrar_caixa("OP-001", leitura, tara, conferida=False)


if __name__ == "__main__":
    unittest.main()
