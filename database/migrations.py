"""Helpers centralizados para alterações estruturais seguras."""


def executar_alteracao_segura(cursor, conn, comando):
    try:
        cursor.execute(comando)
        conn.commit()
    except Exception:
        conn.rollback()


def colunas_postgresql(cursor, tabela):
    """Consulta as colunas visíveis sem adquirir o lock de um ALTER TABLE."""
    cursor.execute("""
        SELECT attname FROM pg_attribute
        WHERE attrelid = to_regclass(%s) AND attnum > 0 AND NOT attisdropped
    """, (tabela,))
    return {linha["attname"] for linha in cursor.fetchall()}
