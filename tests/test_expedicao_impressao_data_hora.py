"""Formatação localizada da data e hora de emissão dos romaneios."""

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modules.expedicao.estoque_service import (  # noqa: E402
    formatar_data_brasileira,
    formatar_data_hora_emissao_manaus,
    formatar_documento_brasileiro,
)


class ImpressaoRomaneioDataHoraTest(unittest.TestCase):
    def test_offset_manaus_no_padrao_brasileiro_exato(self):
        armazenado = "2026-07-24 16:54:00-0400"

        self.assertEqual(
            formatar_data_hora_emissao_manaus(armazenado),
            "24/07/2026 às 16:54 — horário de Manaus",
        )
        self.assertEqual(armazenado, "2026-07-24 16:54:00-0400")

    def test_utc_e_convertido_para_manaus(self):
        self.assertEqual(
            formatar_data_hora_emissao_manaus("2026-07-24T20:54:00+00:00"),
            "24/07/2026 às 16:54 — horário de Manaus",
        )

    def test_conversao_respeita_mudanca_de_data(self):
        self.assertEqual(
            formatar_data_hora_emissao_manaus("2026-07-25T02:30:00+00:00"),
            "24/07/2026 às 22:30 — horário de Manaus",
        )

    def test_valor_nulo_usa_marcador_neutro(self):
        self.assertEqual(formatar_data_hora_emissao_manaus(None), "-")

    def test_valor_ingenuo_nao_recebe_fuso_por_suposição(self):
        self.assertEqual(
            formatar_data_hora_emissao_manaus("2026-07-24 16:54:00"),
            "24/07/2026 às 16:54",
        )


    def test_data_operacional_em_pt_br(self):
        self.assertEqual(formatar_data_brasileira("2026-08-06"), "06/08/2026")
        self.assertEqual(formatar_data_brasileira(None), "-")

    def test_cpf_e_cnpj_recebem_mascara_oficial(self):
        self.assertEqual(formatar_documento_brasileiro("52998224725"), "529.982.247-25")
        self.assertEqual(formatar_documento_brasileiro("11444777000161"), "11.444.777/0001-61")
        self.assertEqual(formatar_documento_brasileiro(None), "-")


if __name__ == "__main__":
    unittest.main()
