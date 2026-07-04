"""Acesso a dados da DRE Gerencial."""

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