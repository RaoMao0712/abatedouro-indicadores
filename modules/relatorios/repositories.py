"""Acesso a dados dos relatorios gerenciais."""

from database import conectar, q


def buscar_custos_mensais_agrupados(competencia_inicio, competencia_fim):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT
        competencia,
        categoria,
        COALESCE(SUM(valor), 0) as total
    FROM custos_mensais
    WHERE competencia BETWEEN ? AND ?
    GROUP BY competencia, categoria
    ORDER BY competencia, categoria
    """), (
        competencia_inicio,
        competencia_fim
    ))
    registros = cursor.fetchall()
    conn.close()
    return registros