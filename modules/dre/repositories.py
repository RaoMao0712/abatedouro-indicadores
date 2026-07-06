"""Acesso a dados da DRE Gerencial."""

import calendar

from database import conectar, q


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
        categoria,
        COALESCE(SUM(valor), 0) as total
    FROM movimentacoes_financeiras
    WHERE tipo = ?
      AND COALESCE(status, 'Pendente') <> ?
      AND data_documento BETWEEN ? AND ?
    GROUP BY categoria
    ORDER BY categoria
    """), ("Saída", "Cancelado", data_inicio, data_fim))
    custos = cursor.fetchall()
    conn.close()
    return custos
