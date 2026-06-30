from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from pesagem_app.core.models import LeituraPeso, UnidadePeso


class ProtocoloWT1000Error(ValueError):
    pass


@dataclass(frozen=True)
class ParserWT1000:
    """Parser inicial configuravel para validacao em bancada.

    O formato definitivo deve ser ajustado com base no manual e nas leituras
    reais capturadas da porta serial da Weightech WT1000.
    """

    nome_origem: str = "Weightech WT1000"

    def parse(self, payload: bytes) -> LeituraPeso:
        texto = payload.decode("ascii", errors="ignore").strip()
        match = re.search(r"([-+]?\d+(?:[\.,]\d+)?)\s*(kg|g)?", texto, re.IGNORECASE)

        if not match:
            raise ProtocoloWT1000Error(f"Leitura nao reconhecida: {texto!r}")

        valor = Decimal(match.group(1).replace(",", "."))
        unidade_texto = (match.group(2) or "kg").lower()
        unidade = UnidadePeso.KG if unidade_texto == "kg" else UnidadePeso.G

        texto_upper = texto.upper()
        instavel = "US" in texto_upper or "INST" in texto_upper

        return LeituraPeso(
            peso_bruto=valor,
            unidade=unidade,
            estavel=not instavel,
            origem=self.nome_origem,
            bruto_original=texto,
        )


class BalancaWT1000Serial:
    nome = "Weightech WT1000"

    def __init__(self, porta: str, baudrate: int, timeout: float = 1.0) -> None:
        self.porta = porta
        self.baudrate = baudrate
        self.timeout = timeout
        self.parser = ParserWT1000()

    def ler_peso(self) -> LeituraPeso:
        try:
            import serial
        except ImportError as exc:
            raise RuntimeError("Instale pyserial para usar a balanca via porta serial.") from exc

        with serial.Serial(self.porta, self.baudrate, timeout=self.timeout) as conexao:
            payload = conexao.readline()

        return self.parser.parse(payload)
