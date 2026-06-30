from __future__ import annotations

import unittest
from decimal import Decimal

from pesagem_app.adapters.scales.weightech_wt1000 import ParserWT1000
from pesagem_app.core.models import UnidadePeso


class ParserWT1000Test(unittest.TestCase):
    def test_extrai_peso_em_kg_de_payload_textual(self) -> None:
        leitura = ParserWT1000().parse(b"ST,GS, 12.345 kg\r\n")

        self.assertEqual(leitura.peso_bruto, Decimal("12.345"))
        self.assertEqual(leitura.unidade, UnidadePeso.KG)
        self.assertTrue(leitura.estavel)

    def test_marca_leitura_instavel_quando_payload_indica_instabilidade(self) -> None:
        leitura = ParserWT1000().parse(b"US,GS, 12.345 kg\r\n")

        self.assertFalse(leitura.estavel)


if __name__ == "__main__":
    unittest.main()
