"""Migracoes pontuais de dados executadas no ambiente da aplicacao."""

from datetime import datetime

from .connection import conectar, q


LIMPEZA_CODEX_PREFIXO = "VALIDACAO-CODEX-"
LIMPEZA_CODEX_CHAVE = "limpeza_residuos_validacao_codex_manutencao_20260724"

OS_CAMPOS_TEXTO = [
    "descricao",
    "diagnostico",
    "solucao",
    "pecas_utilizadas",
    "observacoes_finais",
    "cancelamento_motivo",
    "motivo_parada",
    "local_predial_descricao",
]
RECURSO_CAMPOS_TEXTO = [
    "descricao",
    "descricao_complementar",
    "fornecedor",
    "observacoes",
]
EVENTO_CAMPOS_TEXTO = [
    "evento",
    "descricao",
    "valor_anterior",
    "valor_novo",
]


def _campo_contem_prefixo(campo):
    return f"COALESCE({campo}, '') LIKE ?"


def _params_prefixo(quantidade, inicio=False):
    padrao = f"{LIMPEZA_CODEX_PREFIXO}%" if inicio else f"%{LIMPEZA_CODEX_PREFIXO}%"
    return [padrao] * quantidade


def _ids(rows):
    return [int(row["id"]) for row in rows]


def _limpar_texto_codex(valor):
    if not valor:
        return valor
    texto = str(valor)
    indice = texto.find(LIMPEZA_CODEX_PREFIXO)
    if indice < 0:
        return texto
    if indice == 0:
        return ""
    return texto[:indice].rstrip()


def _registrar_log(mensagem):
    print(f"[MIGRACAO-CODEX-MANUTENCAO] {mensagem}", flush=True)


def remover_residuos_validacao_codex_manutencao():
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
        """), (LIMPEZA_CODEX_CHAVE,))
        if cursor.fetchone():
            conn.commit()
            _registrar_log("limpeza ja registrada; no-op")
            return {"executado": False, "motivo": "limpeza_ja_registrada"}

        cursor.execute(q("""
        SELECT id, descricao
        FROM manutencao_ordens
        WHERE COALESCE(descricao, '') LIKE ?
        """), (f"{LIMPEZA_CODEX_PREFIXO}%",))
        os_ficticias = cursor.fetchall()
        os_ficticias_ids = _ids(os_ficticias)

        where_os_texto = " OR ".join(_campo_contem_prefixo(campo) for campo in OS_CAMPOS_TEXTO)
        cursor.execute(q(f"""
        SELECT id, {", ".join(OS_CAMPOS_TEXTO)}
        FROM manutencao_ordens
        WHERE ({where_os_texto})
        """), _params_prefixo(len(OS_CAMPOS_TEXTO)))
        os_com_marcador = cursor.fetchall()

        where_recurso_texto = " OR ".join(_campo_contem_prefixo(campo) for campo in RECURSO_CAMPOS_TEXTO)
        cursor.execute(q(f"""
        SELECT id, ordem_id, tipo, {", ".join(RECURSO_CAMPOS_TEXTO)}
        FROM manutencao_ordem_recursos
        WHERE ({where_recurso_texto})
        """), _params_prefixo(len(RECURSO_CAMPOS_TEXTO)))
        recursos_com_marcador = cursor.fetchall()

        where_evento_texto = " OR ".join(_campo_contem_prefixo(campo) for campo in EVENTO_CAMPOS_TEXTO)
        cursor.execute(q(f"""
        SELECT id, ordem_id, {", ".join(EVENTO_CAMPOS_TEXTO)}
        FROM manutencao_ordem_eventos
        WHERE ({where_evento_texto})
        """), _params_prefixo(len(EVENTO_CAMPOS_TEXTO)))
        eventos_com_marcador = cursor.fetchall()

        recursos_grupo_b = [
            row for row in recursos_com_marcador
            if int(row["ordem_id"] or 0) not in os_ficticias_ids
        ]
        eventos_grupo_b = [
            row for row in eventos_com_marcador
            if int(row["ordem_id"] or 0) not in os_ficticias_ids
        ]
        os_grupo_c = [
            row for row in os_com_marcador
            if int(row["id"]) not in os_ficticias_ids
        ]

        _registrar_log(f"prefixo={LIMPEZA_CODEX_PREFIXO}")
        _registrar_log(f"grupo_a_os_ficticias={os_ficticias_ids}")
        _registrar_log(
            "grupo_b_recursos_teste="
            f"{[(int(row['id']), int(row['ordem_id'] or 0), row['tipo']) for row in recursos_grupo_b]}"
        )
        _registrar_log(
            "grupo_b_eventos_teste="
            f"{[(int(row['id']), int(row['ordem_id'] or 0)) for row in eventos_grupo_b]}"
        )
        _registrar_log(f"grupo_c_os_campos={[int(row['id']) for row in os_grupo_c]}")

        recursos_ids_b = _ids(recursos_grupo_b)
        eventos_ids_b = _ids(eventos_grupo_b)
        os_recalcular = {
            int(row["ordem_id"] or 0)
            for row in recursos_grupo_b
            if int(row["ordem_id"] or 0)
        }

        recursos_removidos = 0
        eventos_removidos = 0
        ordens_removidas = 0
        campos_restaurados = 0

        for recurso_id in recursos_ids_b:
            cursor.execute(q("""
            DELETE FROM manutencao_ordem_recursos
            WHERE id = ?
            """), (recurso_id,))
            recursos_removidos += int(cursor.rowcount or 0)

        for evento_id in eventos_ids_b:
            cursor.execute(q("""
            DELETE FROM manutencao_ordem_eventos
            WHERE id = ?
            """), (evento_id,))
            eventos_removidos += int(cursor.rowcount or 0)

        for ordem in os_grupo_c:
            atualizacoes = {}
            for campo in OS_CAMPOS_TEXTO:
                valor = ordem[campo]
                if valor and LIMPEZA_CODEX_PREFIXO in str(valor):
                    atualizacoes[campo] = _limpar_texto_codex(valor)
            if atualizacoes:
                set_sql = ", ".join(f"{campo} = ?" for campo in atualizacoes)
                params = list(atualizacoes.values()) + [int(ordem["id"])]
                cursor.execute(q(f"""
                UPDATE manutencao_ordens
                SET {set_sql}
                WHERE id = ?
                """), params)
                campos_restaurados += len(atualizacoes)

        for ordem_id in os_ficticias_ids:
            cursor.execute(q("""
            SELECT COUNT(*) AS total
            FROM manutencao_ordem_recursos
            WHERE ordem_id = ?
            """), (ordem_id,))
            recursos_removidos += int(cursor.fetchone()["total"] or 0)

            cursor.execute(q("""
            SELECT COUNT(*) AS total
            FROM manutencao_ordem_eventos
            WHERE ordem_id = ?
            """), (ordem_id,))
            eventos_removidos += int(cursor.fetchone()["total"] or 0)

            cursor.execute(q("""
            DELETE FROM manutencao_ordem_recursos
            WHERE ordem_id = ?
            """), (ordem_id,))

            cursor.execute(q("""
            DELETE FROM manutencao_ordem_eventos
            WHERE ordem_id = ?
            """), (ordem_id,))

            cursor.execute(q("""
            DELETE FROM manutencao_ordens
            WHERE id = ?
              AND COALESCE(descricao, '') LIKE ?
            """), (ordem_id, f"{LIMPEZA_CODEX_PREFIXO}%"))
            ordens_removidas += int(cursor.rowcount or 0)

        for ordem_id in os_recalcular:
            cursor.execute(q("""
            SELECT COALESCE(SUM(valor_estimado), 0) AS total
            FROM manutencao_ordem_recursos
            WHERE ordem_id = ?
              AND COALESCE(status, '') <> ?
            """), (ordem_id, "Cancelado"))
            total = float(cursor.fetchone()["total"] or 0)
            cursor.execute(q("""
            UPDATE manutencao_ordens
            SET custo_estimado = ?
            WHERE id = ?
            """), (total, ordem_id))

        cursor.execute(q("""
        INSERT INTO manutencao_limpezas_dados (
            chave, executado_em, ordem_id, materiais_removidos, eventos_removidos, ordens_removidas
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            LIMPEZA_CODEX_CHAVE,
            datetime.now().isoformat(timespec="seconds"),
            0,
            recursos_removidos,
            eventos_removidos + campos_restaurados,
            ordens_removidas,
        ))

        _registrar_log(
            "resultado="
            f"ordens_removidas={ordens_removidas}; "
            f"recursos_removidos={recursos_removidos}; "
            f"eventos_removidos={eventos_removidos}; "
            f"campos_restaurados={campos_restaurados}; "
            f"os_recalculadas={sorted(os_recalcular)}"
        )
        conn.commit()
        return {
            "executado": True,
            "os_ficticias": os_ficticias_ids,
            "recursos_removidos": recursos_removidos,
            "eventos_removidos": eventos_removidos,
            "campos_restaurados": campos_restaurados,
            "ordens_removidas": ordens_removidas,
            "os_recalculadas": sorted(os_recalcular),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
