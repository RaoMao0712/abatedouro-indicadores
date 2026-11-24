"""Camada de persistencia do modulo de Producao."""

from database import conectar, q


def consultar_relatorio_ordens(situacao, produto, numero, pagina, *, imprimir=False):
    condicoes = ["UPPER(status) IN ('ABERTA', 'ENCERRADA')"]
    parametros = []
    if situacao:
        condicoes.append("UPPER(status) = ?")
        parametros.append(situacao)
    if produto:
        condicoes.append("sku = ?")
        parametros.append(produto)
    if numero:
        condicoes.append("CAST(id AS TEXT) = ?")
        parametros.append(numero)
    filtro = " AND ".join(condicoes)
    conexao = conectar()
    try:
        cursor = conexao.cursor()
        cursor.execute(q(f"SELECT COUNT(*) AS total FROM ordens_producao WHERE {filtro}"), parametros)
        total = cursor.fetchone()["total"]
        por_pagina = 25
        paginas = max(1, (total + por_pagina - 1) // por_pagina)
        pagina = min(pagina, paginas)
        consulta = f"""
            SELECT id, UPPER(status) AS situacao, sku, quantidade_aves
            FROM ordens_producao WHERE {filtro} ORDER BY id DESC
        """
        if not imprimir:
            consulta += " LIMIT ? OFFSET ?"
            parametros.extend((por_pagina, (pagina - 1) * por_pagina))
        cursor.execute(q(consulta), parametros)
        ordens = cursor.fetchall()
        cursor.execute("""
            SELECT DISTINCT sku FROM ordens_producao
            WHERE UPPER(status) IN ('ABERTA', 'ENCERRADA') AND sku <> ''
            ORDER BY sku
        """)
        produtos = [registro["sku"] for registro in cursor.fetchall()]
        return ordens, produtos, total, pagina, paginas
    finally:
        conexao.close()
