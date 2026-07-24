"""Migracoes pontuais de dados executadas no ambiente da aplicacao."""

from datetime import datetime

from .connection import conectar, q


LIMPEZA_OS_CODEX_CHAVE = "limpeza_os_validacao_codex_20260723215342"
LIMPEZA_OS_CODEX_ORDEM_ID = 11
LIMPEZA_OS_CODEX_MARCADOR = "VALIDACAO-CODEX-20260723215342"


def remover_os_validacao_codex_20260723215342():
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_limpezas_dados (
            chave TEXT PRIMARY KEY,
            executado_em TEXT NOT NULL,
            ordem_id INTEGER NOT NULL,
            materiais_removidos INTEGER NOT NULL,
            eventos_removidos INTEGER NOT NULL,
            ordens_removidas INTEGER NOT NULL
        )
        """)

        cursor.execute(q("""
        SELECT chave
        FROM manutencao_limpezas_dados
        WHERE chave = ?
        """), (LIMPEZA_OS_CODEX_CHAVE,))
        if cursor.fetchone():
            conn.commit()
            return {"executado": False, "motivo": "limpeza_ja_registrada"}

        cursor.execute(q("""
        SELECT id, descricao
        FROM manutencao_ordens
        WHERE id = ?
        """), (LIMPEZA_OS_CODEX_ORDEM_ID,))
        ordem = cursor.fetchone()
        if not ordem:
            cursor.execute(q("""
            INSERT INTO manutencao_limpezas_dados (
                chave, executado_em, ordem_id, materiais_removidos, eventos_removidos, ordens_removidas
            ) VALUES (?, ?, ?, ?, ?, ?)
            """), (
                LIMPEZA_OS_CODEX_CHAVE,
                datetime.now().isoformat(timespec="seconds"),
                LIMPEZA_OS_CODEX_ORDEM_ID,
                0,
                0,
                0,
            ))
            conn.commit()
            return {"executado": False, "motivo": "os_ausente"}

        if not (ordem["descricao"] or "").startswith(LIMPEZA_OS_CODEX_MARCADOR):
            raise RuntimeError("OS 11 existe, mas nao possui o marcador exato de validacao Codex.")

        cursor.execute(q("""
        SELECT COUNT(*) AS total
        FROM manutencao_ordem_recursos
        WHERE ordem_id = ?
        """), (LIMPEZA_OS_CODEX_ORDEM_ID,))
        materiais_removidos = int(cursor.fetchone()["total"] or 0)

        cursor.execute(q("""
        SELECT COUNT(*) AS total
        FROM manutencao_ordem_eventos
        WHERE ordem_id = ?
        """), (LIMPEZA_OS_CODEX_ORDEM_ID,))
        eventos_removidos = int(cursor.fetchone()["total"] or 0)

        cursor.execute(q("""
        DELETE FROM manutencao_ordem_recursos
        WHERE ordem_id = ?
        """), (LIMPEZA_OS_CODEX_ORDEM_ID,))

        cursor.execute(q("""
        DELETE FROM manutencao_ordem_eventos
        WHERE ordem_id = ?
        """), (LIMPEZA_OS_CODEX_ORDEM_ID,))

        cursor.execute(q("""
        DELETE FROM manutencao_ordens
        WHERE id = ?
          AND descricao LIKE ?
        """), (LIMPEZA_OS_CODEX_ORDEM_ID, f"{LIMPEZA_OS_CODEX_MARCADOR}%"))
        ordens_removidas = int(cursor.rowcount or 0)
        if ordens_removidas != 1:
            raise RuntimeError("Falha ao remover exatamente a OS 11 de validacao Codex.")

        cursor.execute(q("""
        INSERT INTO manutencao_limpezas_dados (
            chave, executado_em, ordem_id, materiais_removidos, eventos_removidos, ordens_removidas
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            LIMPEZA_OS_CODEX_CHAVE,
            datetime.now().isoformat(timespec="seconds"),
            LIMPEZA_OS_CODEX_ORDEM_ID,
            materiais_removidos,
            eventos_removidos,
            ordens_removidas,
        ))
        conn.commit()
        return {
            "executado": True,
            "ordem_id": LIMPEZA_OS_CODEX_ORDEM_ID,
            "materiais_removidos": materiais_removidos,
            "eventos_removidos": eventos_removidos,
            "ordens_removidas": ordens_removidas,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
