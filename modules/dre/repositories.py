"""Acesso a dados da DRE Gerencial."""

import calendar

from database import conectar, q
from modules.financeiro.services import (
    LINHA_DEDUCOES_RECEITA,
    LINHA_DESPESAS_OPERACIONAIS,
    LINHA_RECEITA_BRUTA,
    LINHA_RESULTADO_NAO_OPERACIONAL,
)


TIPOS_SAIDA = ("Saida", "Saída", "SaÃ­da", "Sa?da")


def buscar_vendas_periodo(data_inicio, data_fim):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM vendas_diarias
    WHERE data BETWEEN ? AND ?
    ORDER BY sku ASC, data ASC, id ASC
    """), (data_inicio, data_fim))
    vendas = cursor.fetchall()
    conn.close()
    return vendas


def buscar_receita_bruta_movimentacoes(data_inicio, data_fim):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT COALESCE(SUM(valor), 0) as total
    FROM movimentacoes_financeiras
    WHERE tipo = ?
      AND COALESCE(status, 'Pendente') <> ?
      AND data_documento BETWEEN ? AND ?
      AND (
        linha_dre = ?
        OR categoria IN (?, ?, ?)
      )
    """), (
        "Entrada", "Cancelado", data_inicio, data_fim,
        LINHA_RECEITA_BRUTA,
        "Receita Bruta", "Venda de Producao Propria", "Venda de Mercadorias",
    ))
    item = cursor.fetchone()
    conn.close()
    return float(item["total"] or 0)


def buscar_deducoes_receita_movimentacoes(data_inicio, data_fim):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT COALESCE(SUM(valor), 0) as total
    FROM movimentacoes_financeiras
    WHERE COALESCE(status, 'Pendente') <> ?
      AND data_documento BETWEEN ? AND ?
      AND linha_dre = ?
      AND tipo IN (?, ?, ?, ?)
      AND COALESCE(tipo_conta, 'Saida') <> ?
    """), ("Cancelado", data_inicio, data_fim, LINHA_DEDUCOES_RECEITA, *TIPOS_SAIDA, "Neutro"))
    item = cursor.fetchone()
    conn.close()
    return float(item["total"] or 0)


def buscar_resultado_nao_operacional_movimentacoes(data_inicio, data_fim):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT
        COALESCE(SUM(
            CASE
                WHEN tipo = ? THEN valor
                WHEN tipo IN (?, ?, ?, ?) THEN -valor
                ELSE 0
            END
        ), 0) as total
    FROM movimentacoes_financeiras
    WHERE COALESCE(status, 'Pendente') <> ?
      AND data_documento BETWEEN ? AND ?
      AND linha_dre = ?
      AND COALESCE(tipo_conta, '') <> ?
    """), ("Entrada", *TIPOS_SAIDA, "Cancelado", data_inicio, data_fim, LINHA_RESULTADO_NAO_OPERACIONAL, "Neutro"))
    item = cursor.fetchone()
    conn.close()
    return float(item["total"] or 0)


def buscar_parametros_custos_por_sku():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM parametros_custos")
    parametros = {
        item["sku"]: item
        for item in cursor.fetchall()
    }
    conn.close()
    return parametros


def buscar_custos_mensais_por_categoria(competencia):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT
        categoria,
        COALESCE(SUM(valor), 0) as total
    FROM custos_mensais
    WHERE competencia = ?
    GROUP BY categoria
    ORDER BY categoria
    """), (competencia,))
    custos = cursor.fetchall()
    conn.close()
    return custos


def buscar_custos_operacionais_movimentacoes_por_categoria(competencia):
    ano, mes = competencia.split("-")
    ultimo_dia = calendar.monthrange(int(ano), int(mes))[1]
    data_inicio = f"{competencia}-01"
    data_fim = f"{competencia}-{ultimo_dia:02d}"

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT
        COALESCE(NULLIF(categoria_plano, ''), categoria) as categoria,
        COALESCE(SUM(valor), 0) as total
    FROM movimentacoes_financeiras
    WHERE tipo IN (?, ?, ?, ?)
      AND COALESCE(status, 'Pendente') <> ?
      AND data_documento BETWEEN ? AND ?
      AND (
        linha_dre = ?
        OR linha_dre IS NULL
        OR TRIM(linha_dre) = ''
      )
    GROUP BY COALESCE(NULLIF(categoria_plano, ''), categoria)
    ORDER BY categoria
    """), (*TIPOS_SAIDA, "Cancelado", data_inicio, data_fim, LINHA_DESPESAS_OPERACIONAIS))
    custos = cursor.fetchall()
    conn.close()
    return custos
