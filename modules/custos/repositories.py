"""Acesso a dados do modulo de Custos."""

from database import DATABASE_URL, conectar, q


def criar_tabelas_custos():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS parametros_custos (
            id SERIAL PRIMARY KEY,
            sku TEXT UNIQUE NOT NULL,
            custo_ave REAL DEFAULT 0,
            unidade_custo_ave TEXT DEFAULT '',
            custo_embalagem REAL DEFAULT 0,
            unidade_custo_embalagem TEXT DEFAULT '',
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS custos_mensais (
            id SERIAL PRIMARY KEY,
            competencia TEXT NOT NULL,
            categoria TEXT NOT NULL,
            valor REAL NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS parametros_custos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE NOT NULL,
            custo_ave REAL DEFAULT 0,
            unidade_custo_ave TEXT DEFAULT '',
            custo_embalagem REAL DEFAULT 0,
            unidade_custo_embalagem TEXT DEFAULT '',
            atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS custos_mensais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competencia TEXT NOT NULL,
            categoria TEXT NOT NULL,
            valor REAL NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()

    parametros_padrao = [
        ("Galinha Cortada", 0, "R$/ave", 0, "R$/bandeja"),
        ("Galinha Inteira", 0, "R$/ave", 0, "R$/unidade")
    ]

    for item in parametros_padrao:
        try:
            cursor.execute(q("""
            INSERT INTO parametros_custos (
                sku,
                custo_ave,
                unidade_custo_ave,
                custo_embalagem,
                unidade_custo_embalagem
            ) VALUES (?, ?, ?, ?, ?)
            """), item)
            conn.commit()
        except Exception:
            conn.rollback()

    conn.close()


def buscar_parametros_custos():
    criar_tabelas_custos()

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT *
    FROM parametros_custos
    ORDER BY sku
    """)
    parametros = cursor.fetchall()
    conn.close()
    return parametros


def buscar_custos_mensais(competencia_inicio=None, competencia_fim=None, categoria=None):
    criar_tabelas_custos()

    conn = conectar()
    cursor = conn.cursor()

    filtros = []
    parametros = []

    if competencia_inicio:
        filtros.append("competencia >= ?")
        parametros.append(competencia_inicio)

    if competencia_fim:
        filtros.append("competencia <= ?")
        parametros.append(competencia_fim)

    if categoria and categoria != "Todas":
        filtros.append("categoria = ?")
        parametros.append(categoria)

    where_sql = f"WHERE {' AND '.join(filtros)}" if filtros else ""

    cursor.execute(q(f"""
    SELECT *
    FROM custos_mensais
    {where_sql}
    ORDER BY competencia DESC, categoria ASC
    """), parametros)

    custos = cursor.fetchall()
    conn.close()
    return custos


def atualizar_parametro_custo(sku, custo_ave, unidade_custo_ave, custo_embalagem, unidade_custo_embalagem):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE parametros_custos
    SET custo_ave = ?,
        unidade_custo_ave = ?,
        custo_embalagem = ?,
        unidade_custo_embalagem = ?
    WHERE sku = ?
    """), (
        custo_ave,
        unidade_custo_ave,
        custo_embalagem,
        unidade_custo_embalagem,
        sku
    ))
    conn.commit()
    conn.close()


def inserir_custo_mensal(competencia, categoria, valor, observacoes):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    INSERT INTO custos_mensais (
        competencia,
        categoria,
        valor,
        observacoes
    ) VALUES (?, ?, ?, ?)
    """), (competencia, categoria, valor, observacoes))
    conn.commit()
    conn.close()


def inserir_custos_mensais_lote(linhas):
    conn = conectar()
    cursor = conn.cursor()
    cursor.executemany(q("""
    INSERT INTO custos_mensais (
        competencia,
        categoria,
        valor,
        observacoes
    ) VALUES (?, ?, ?, ?)
    """), linhas)
    conn.commit()
    conn.close()


def buscar_custo_mensal_por_id(custo_id):
    criar_tabelas_custos()

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM custos_mensais
    WHERE id = ?
    """), (custo_id,))
    custo = cursor.fetchone()
    conn.close()
    return custo


def atualizar_custo_mensal(custo_id, competencia, categoria, valor, observacoes):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE custos_mensais
    SET competencia = ?,
        categoria = ?,
        valor = ?,
        observacoes = ?
    WHERE id = ?
    """), (competencia, categoria, valor, observacoes, custo_id))
    conn.commit()
    conn.close()


def excluir_custo_mensal(custo_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    DELETE FROM custos_mensais
    WHERE id = ?
    """), (custo_id,))
    conn.commit()
    conn.close()