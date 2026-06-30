from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import uuid4


class UnidadePeso(str, Enum):
    KG = "kg"
    G = "g"


@dataclass(frozen=True)
class LeituraPeso:
    peso_bruto: Decimal
    unidade: UnidadePeso
    estavel: bool
    capturado_em: datetime = field(default_factory=datetime.now)
    origem: str = ""
    bruto_original: str = ""


@dataclass(frozen=True)
class Tara:
    peso: Decimal
    unidade: UnidadePeso = UnidadePeso.KG
    descricao: str = "Tara padrao"


@dataclass(frozen=True)
class PesagemCaixa:
    id: str
    ordem_producao: str
    peso_bruto: Decimal
    tara: Decimal
    peso_liquido: Decimal
    unidade: UnidadePeso
    conferida: bool
    registrada_em: datetime
    operador: Optional[str] = None
    pallet_id: Optional[str] = None
    equipamento_origem: str = ""


def novo_id_pesagem() -> str:
    return str(uuid4())
