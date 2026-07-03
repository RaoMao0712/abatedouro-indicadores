"""Helpers centralizados para alterações estruturais seguras."""


def executar_alteracao_segura(cursor, conn, comando):
    try:
        cursor.execute(comando)
        conn.commit()
    except Exception:
        conn.rollback()
