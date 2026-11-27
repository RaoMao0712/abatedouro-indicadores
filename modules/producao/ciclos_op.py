"""Identidade persistente do ciclo, distinta da versão de concorrência da OP."""

from pathlib import Path

from database import DATABASE_URL, q, transaction


TABELAS_APONTAMENTOS = (
    "apontamentos_producao", "embalagem_primaria_apontamentos",
    "apontamentos_descartes", "apontamentos_mao_obra",
    "apontamentos_paradas", "apontamentos_tempos_setor", "apontamentos_setor",
)


def aplicar_migration_ciclos_op_postgres():
    """Aplica a migração publicada uma vez durante o bootstrap PostgreSQL."""
    arquivo = Path(__file__).resolve().parents[2] / "database" / "20261127_op_ciclos.sql"
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pg_advisory_xact_lock(20261127, 1)")
        if not tabela_de_ciclo_existe(cursor, "op_ciclos"):
            cursor.execute(arquivo.read_text(encoding="utf-8-sig"))


def tabela_de_ciclo_existe(cursor, tabela):
    if DATABASE_URL:
        cursor.execute(q("SELECT to_regclass(?) IS NOT NULL AS existe"), (tabela,))
    else:
        cursor.execute(q("""SELECT EXISTS (SELECT 1 FROM sqlite_master
            WHERE name=? AND type='table') AS existe"""), (tabela,))
    return bool(cursor.fetchone()["existe"])


def fonte_ativa_cursor(cursor, tabela):
    if tabela not in TABELAS_APONTAMENTOS:
        raise ValueError("Tabela sem política de vigência por ciclo.")
    if not tabela_de_ciclo_existe(cursor, "op_ciclo_registros_invalidados"):
        return tabela
    return f"""(SELECT atual.* FROM {tabela} atual WHERE NOT EXISTS (
        SELECT 1 FROM op_ciclo_registros_invalidados invalido
        WHERE invalido.tabela='{tabela}' AND invalido.registro_id=atual.id
    ))"""


def apontamentos_correntes_cursor(cursor, op_id):
    apontamentos = {}
    for tabela in TABELAS_APONTAMENTOS:
        fonte = fonte_ativa_cursor(cursor, tabela)
        cursor.execute(q(f"SELECT id FROM {fonte} vigente WHERE op_id=? ORDER BY id"), (op_id,))
        apontamentos[tabela] = [linha["id"] for linha in cursor.fetchall()]
    return apontamentos


def invalidar_apontamentos_cursor(cursor, ciclo_id, apontamentos):
    for tabela, ids in apontamentos.items():
        cursor.executemany(q("""INSERT INTO op_ciclo_registros_invalidados
            (ciclo_id,tabela,registro_id) VALUES (?,?,?)"""),
            [(ciclo_id, tabela, identificador) for identificador in ids])
        if tabela in {"apontamentos_producao", "embalagem_primaria_apontamentos"}:
            cursor.executemany(q(f"UPDATE {tabela} SET vigente=0 WHERE id=?"), [(identificador,) for identificador in ids])


def ciclo_corrente_cursor(cursor, op_id, *, bloquear=False):
    sql = "SELECT * FROM op_ciclos WHERE op_id=? AND corrente=1"
    if bloquear and DATABASE_URL:
        sql += " FOR UPDATE"
    cursor.execute(q(sql), (op_id,))
    ciclo = cursor.fetchone()
    if not ciclo:
        raise ValueError("A OP não possui ciclo corrente.")
    return dict(ciclo)


def numero_ciclo_posicao_cursor(cursor, op_id):
    if not tabela_de_ciclo_existe(cursor, "op_ciclos"):
        return 1
    return ciclo_corrente_cursor(cursor, op_id)["numero_ciclo"]


def substituir_ciclo_cursor(cursor, op_id, *, ciclo_id, operacao_id, usuario, motivo, agora,
                            checkpoint=None):
    """Etapa final do reset, na transação que já compensou o ciclo anterior."""
    if not all(str(valor or "").strip() for valor in (operacao_id, usuario, motivo)):
        raise ValueError("Operação, administrador e motivo são obrigatórios.")
    ciclo = ciclo_corrente_cursor(cursor, op_id, bloquear=True)
    if ciclo["id"] != ciclo_id:
        raise ValueError("O ciclo corrente mudou desde a análise.")
    cursor.execute(q("""
        UPDATE op_ciclos SET status='INVALIDADO_REPROCESSAMENTO', corrente=0,
            invalidado_em=?, invalidado_por=?, motivo_invalidacao=?, operacao_reset_id=?
        WHERE id=? AND corrente=1
    """), (agora, usuario, motivo.strip(), operacao_id, ciclo_id))
    if cursor.rowcount != 1:
        raise ValueError("A OP foi alterada concorrentemente.")
    if checkpoint:
        checkpoint("apos_invalidar_ciclo")
        checkpoint("antes_novo_ciclo")
    cursor.execute(q("""
        INSERT INTO op_ciclos (op_id,numero_ciclo,status,iniciado_em,iniciado_por)
        VALUES (?,?,'ATIVO',?,?)
    """), (op_id, ciclo["numero_ciclo"] + 1, agora, usuario))
    return ciclo_corrente_cursor(cursor, op_id)
