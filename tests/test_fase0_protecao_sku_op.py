import sqlite3

import pytest

from modules.producao.protecao_sku_op import fatos_operacionais_op, validar_alteracao_sku
from modules.producao.services import setores_por_sku
from modules.producao.skus_legados import (
    SKU_GALINHA_CORTADA,
    SKU_GALINHA_INTEIRA,
    validar_sku_operacional,
)


@pytest.mark.parametrize("sku", [None, "", "Produto Novo"])
def test_sku_desconhecido_nao_herda_fluxo_legado(sku):
    with pytest.raises(ValueError, match="SKU|suporte"):
        validar_sku_operacional(sku)
    with pytest.raises(ValueError, match="SKU|suporte"):
        setores_por_sku(sku)


def test_dois_skus_legados_preservam_roteiros():
    assert validar_sku_operacional(SKU_GALINHA_CORTADA) == SKU_GALINHA_CORTADA
    assert validar_sku_operacional(SKU_GALINHA_INTEIRA) == SKU_GALINHA_INTEIRA
    assert "Corte" in setores_por_sku(SKU_GALINHA_CORTADA)
    assert "Corte" not in setores_por_sku(SKU_GALINHA_INTEIRA)


def _cursor_com_fatos(tabela=None):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    for nome in ("apontamentos_producao", "estoque_produto_intermediario",
                 "pa_caixa_composicao", "pa_nao_conformes", "retrabalho_origens"):
        cursor.execute(f"CREATE TABLE {nome}(id INTEGER PRIMARY KEY, op_id INTEGER)")
    if tabela:
        cursor.execute(f"INSERT INTO {tabela}(op_id) VALUES(10)")
    return conn, cursor


def test_op_virgem_permite_troca():
    conn, cursor = _cursor_com_fatos()
    assert fatos_operacionais_op(cursor, 10) == []
    assert validar_alteracao_sku(cursor, 10, SKU_GALINHA_CORTADA, SKU_GALINHA_INTEIRA) == []
    conn.close()


@pytest.mark.parametrize("tabela", [
    "apontamentos_producao", "estoque_produto_intermediario",
    "pa_caixa_composicao", "pa_nao_conformes", "retrabalho_origens",
])
def test_fato_operacional_bloqueia_troca(tabela):
    conn, cursor = _cursor_com_fatos(tabela)
    assert tabela in fatos_operacionais_op(cursor, 10)
    with pytest.raises(ValueError, match="fatos operacionais"):
        validar_alteracao_sku(cursor, 10, SKU_GALINHA_CORTADA, SKU_GALINHA_INTEIRA)
    conn.close()
