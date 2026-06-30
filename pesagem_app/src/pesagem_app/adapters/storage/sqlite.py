from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path

from pesagem_app.core.models import PesagemCaixa


class RepositorioPesagensSQLite:
    def __init__(self, caminho_banco: str | Path) -> None:
        self.caminho_banco = Path(caminho_banco)
        self.caminho_banco.parent.mkdir(parents=True, exist_ok=True)
        self._criar_schema()

    def _conectar(self) -> sqlite3.Connection:
        conexao = sqlite3.connect(self.caminho_banco)
        conexao.execute("PRAGMA foreign_keys = ON")
        return conexao

    def _criar_schema(self) -> None:
        with self._conectar() as conexao:
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS pesagens_caixas (
                    id TEXT PRIMARY KEY,
                    ordem_producao TEXT NOT NULL,
                    peso_bruto TEXT NOT NULL,
                    tara TEXT NOT NULL,
                    peso_liquido TEXT NOT NULL,
                    unidade TEXT NOT NULL,
                    conferida INTEGER NOT NULL,
                    registrada_em TEXT NOT NULL,
                    operador TEXT,
                    pallet_id TEXT,
                    equipamento_origem TEXT
                )
                """
            )

    def salvar_pesagem(self, pesagem: PesagemCaixa) -> None:
        with self._conectar() as conexao:
            conexao.execute(
                """
                INSERT INTO pesagens_caixas (
                    id,
                    ordem_producao,
                    peso_bruto,
                    tara,
                    peso_liquido,
                    unidade,
                    conferida,
                    registrada_em,
                    operador,
                    pallet_id,
                    equipamento_origem
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pesagem.id,
                    pesagem.ordem_producao,
                    _decimal_texto(pesagem.peso_bruto),
                    _decimal_texto(pesagem.tara),
                    _decimal_texto(pesagem.peso_liquido),
                    pesagem.unidade.value,
                    1 if pesagem.conferida else 0,
                    pesagem.registrada_em.isoformat(),
                    pesagem.operador,
                    pesagem.pallet_id,
                    pesagem.equipamento_origem,
                ),
            )


def _decimal_texto(valor: Decimal) -> str:
    return format(valor, "f")
