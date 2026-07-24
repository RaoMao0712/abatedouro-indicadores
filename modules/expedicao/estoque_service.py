"""Marco zero, estoque operacional e auditoria da Expedição.

Este módulo não altera os apontamentos produtivos. Ele classifica o PA já
existente como histórico e mantém uma camada operacional própria para o PA
formado por OPs posteriores ao marco zero.
"""

from datetime import datetime
import json
from zoneinfo import ZoneInfo

from database import DATABASE_URL, conectar, q, transaction
from modules.auth.services import nome_usuario_atual, perfil_atual


FUSO_MANAUS = ZoneInfo("America/Manaus")
LOCAL_ABATEDOURO = "Abatedouro"
LOCAL_LSM = "Câmara Fria LSM"

TIPOS_ROMANEIO = {
    "TRANSFERENCIA": "Transferência",
    "DESCARTE": "Descarte",
    "DEVOLUCAO": "Devolução",
    "TRANSFERENCIA_AUTORIZADA": "Transferência autorizada",
    "HISTORICO_MARCO_ZERO": "Transferência histórica — marco zero",
}

DESTINOS_CONTROLADOS = {
    "TRANSFERENCIA": LOCAL_LSM,
    "TRANSFERENCIA_AUTORIZADA": LOCAL_LSM,
    "HISTORICO_MARCO_ZERO": LOCAL_LSM,
    "DESCARTE": "Descarte autorizado",
    "DEVOLUCAO": "Devolução ao fornecedor",
}

STATUS_DISPONIVEL = "DISPONIVEL"
STATUS_RESERVADO = "RESERVADO"
STATUS_BLOQUEADO = "BLOQUEADO"
STATUS_TRANSFERIDO = "TRANSFERIDO"
STATUS_EXPEDIDO = "EXPEDIDO"
STATUS_DESCARTADO = "DESCARTADO"
STATUS_DEVOLVIDO = "DEVOLVIDO"
STATUS_REPROCESSAMENTO = "REPROCESSAMENTO"
STATUS_LEGADO = "LEGADO"
STATUS_PENDENTE = "PENDENTE_OP"
_SCHEMA_ESTOQUE_CONFIAVEL_INICIALIZADO = False


def _agora():
    return datetime.now(FUSO_MANAUS).strftime("%Y-%m-%d %H:%M:%S%z")


def _usuario():
    try:
        return nome_usuario_atual() or "Sistema"
    except RuntimeError:
        return "Sistema"


def _perfil():
    try:
        return perfil_atual() or "sistema"
    except RuntimeError:
        return "sistema"


def _alterar_coluna(cursor, sql_postgres, sql_sqlite):
    try:
        cursor.execute(sql_postgres if DATABASE_URL else sql_sqlite)
    except Exception:
        if DATABASE_URL:
            raise


def _inserir_evento(
    cursor,
    *,
    caixa_id=None,
    expedicao_id=None,
    acao,
    situacao_anterior=None,
    situacao_nova=None,
    condicao_anterior=None,
    condicao_nova=None,
    quantidade=0,
    peso=None,
    justificativa=None,
    observacao=None,
    idempotency_key=None,
):
    parametros = (
        caixa_id,
        expedicao_id,
        acao,
        situacao_anterior,
        situacao_nova,
        condicao_anterior,
        condicao_nova,
        float(quantidade or 0),
        None if peso is None else float(peso),
        justificativa,
        observacao,
        _usuario(),
        _perfil(),
        _agora(),
        idempotency_key,
    )
    if DATABASE_URL:
        cursor.execute(q("""
        INSERT INTO estoque_eventos (
            caixa_id, expedicao_id, acao, situacao_anterior, situacao_nova,
            condicao_anterior, condicao_nova, quantidade, peso,
            justificativa, observacao, usuario, perfil, criado_em,
            idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (idempotency_key) DO NOTHING
        """), parametros)
    else:
        cursor.execute(q("""
        INSERT OR IGNORE INTO estoque_eventos (
            caixa_id, expedicao_id, acao, situacao_anterior, situacao_nova,
            condicao_anterior, condicao_nova, quantidade, peso,
            justificativa, observacao, usuario, perfil, criado_em,
            idempotency_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), parametros)


def registrar_evento_romaneio(
    cursor,
    expedicao_id,
    acao,
    *,
    estado_anterior=None,
    estado_novo=None,
    dados_alterados=None,
    justificativa=None,
    idempotency_key=None,
):
    """Registra uma ação documental do romaneio com estado e dados completos."""
    _inserir_evento(
        cursor,
        expedicao_id=expedicao_id,
        acao=acao,
        situacao_anterior=estado_anterior,
        situacao_nova=estado_novo,
        justificativa=justificativa,
        observacao=json.dumps(
            {
                "estado_anterior": estado_anterior,
                "estado_novo": estado_novo,
                "dados_alterados": dados_alterados or {},
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ),
        idempotency_key=idempotency_key,
    )


def criar_tabelas_estoque_confiavel():
    """Aplica a migration aditiva e registra o marco zero uma única vez."""
    global _SCHEMA_ESTOQUE_CONFIAVEL_INICIALIZADO
    if _SCHEMA_ESTOQUE_CONFIAVEL_INICIALIZADO:
        return

    conn = conectar()
    cursor = conn.cursor()
    try:
        id_pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
        timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"

        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS estoque_marcos (
            id {id_pk},
            tipo TEXT UNIQUE NOT NULL,
            referencia_data TEXT NOT NULL,
            fuso_horario TEXT NOT NULL,
            legacy_max_op_id INTEGER NOT NULL,
            ativado_por TEXT NOT NULL,
            ativado_em {timestamp_type} NOT NULL,
            status TEXT NOT NULL DEFAULT 'ATIVO'
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS estoque_eventos (
            id {id_pk},
            caixa_id INTEGER,
            expedicao_id INTEGER,
            acao TEXT NOT NULL,
            situacao_anterior TEXT,
            situacao_nova TEXT,
            condicao_anterior TEXT,
            condicao_nova TEXT,
            quantidade REAL DEFAULT 0,
            peso REAL DEFAULT 0,
            justificativa TEXT,
            observacao TEXT,
            usuario TEXT NOT NULL,
            perfil TEXT NOT NULL,
            criado_em {timestamp_type} NOT NULL,
            idempotency_key TEXT UNIQUE
        )
        """)

        _alterar_coluna(
            cursor,
            "ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS estoque_classificacao TEXT DEFAULT 'POS_MARCO'",
            "ALTER TABLE ordens_producao ADD COLUMN estoque_classificacao TEXT DEFAULT 'POS_MARCO'",
        )
        _alterar_coluna(
            cursor,
            "ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS estoque_marco_id INTEGER",
            "ALTER TABLE ordens_producao ADD COLUMN estoque_marco_id INTEGER",
        )

        colunas_pa = [
            ("estoque_operacional INTEGER DEFAULT 0", "estoque_operacional INTEGER DEFAULT 0"),
            ("peso_tara REAL DEFAULT 0", "peso_tara REAL DEFAULT 0"),
            ("unidade_estoque TEXT DEFAULT 'CAIXA'", "unidade_estoque TEXT DEFAULT 'CAIXA'"),
            ("apresentacao TEXT", "apresentacao TEXT"),
            ("galinhas_por_pacote INTEGER", "galinhas_por_pacote INTEGER"),
            ("quantidade_pacotes INTEGER", "quantidade_pacotes INTEGER"),
            ("quantidade_galinhas INTEGER", "quantidade_galinhas INTEGER"),
            ("quantidade_pacotes_reservados INTEGER DEFAULT 0", "quantidade_pacotes_reservados INTEGER DEFAULT 0"),
            ("condicao TEXT DEFAULT 'CONFORME'", "condicao TEXT DEFAULT 'CONFORME'"),
            ("disponibilidade TEXT DEFAULT 'PENDENTE_OP'", "disponibilidade TEXT DEFAULT 'PENDENTE_OP'"),
            ("zona_estoque TEXT DEFAULT 'Conforme'", "zona_estoque TEXT DEFAULT 'Conforme'"),
            ("motivo_nao_conformidade TEXT", "motivo_nao_conformidade TEXT"),
            ("reservado_expedicao_id INTEGER", "reservado_expedicao_id INTEGER"),
            ("formado_por TEXT", "formado_por TEXT"),
            ("formado_em TEXT", "formado_em TEXT"),
        ]
        for postgres_col, sqlite_col in colunas_pa:
            nome = postgres_col.split()[0]
            _alterar_coluna(
                cursor,
                f"ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS {postgres_col}",
                f"ALTER TABLE pa_caixas ADD COLUMN {sqlite_col}",
            )

        colunas_expedicao = [
            "origem TEXT DEFAULT 'Abatedouro'",
            "destino_local_id INTEGER",
            "criado_por TEXT",
            "perfil_criacao TEXT",
            "atualizado_em TEXT",
            "concluido_em TEXT",
            "cancelado_em TEXT",
            "estornado_em TEXT",
            "emitido_por TEXT",
            "emitido_em TEXT",
            "justificativa TEXT",
        ]
        for coluna in colunas_expedicao:
            _alterar_coluna(
                cursor,
                f"ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS {coluna}",
                f"ALTER TABLE expedicoes ADD COLUMN {coluna}",
            )

        colunas_item = [
            "situacao_anterior TEXT",
            "condicao_anterior TEXT",
            "local_anterior_id INTEGER",
            "unidade_estoque TEXT",
            "apresentacao TEXT",
            "galinhas_por_pacote INTEGER",
            "quantidade_pacotes INTEGER",
            "quantidade_galinhas INTEGER",
            "peso_bruto REAL",
            "peso_tara REAL",
            "lote TEXT",
        ]
        for coluna in colunas_item:
            _alterar_coluna(
                cursor,
                f"ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS {coluna}",
                f"ALTER TABLE expedicao_itens ADD COLUMN {coluna}",
            )

        for coluna in [
            "pacotes_v1 INTEGER DEFAULT 0",
            "pacotes_v2 INTEGER DEFAULT 0",
            "total_galinhas INTEGER DEFAULT 0",
        ]:
            _alterar_coluna(
                cursor,
                f"ALTER TABLE embalagem_primaria_apontamentos ADD COLUMN IF NOT EXISTS {coluna}",
                f"ALTER TABLE embalagem_primaria_apontamentos ADD COLUMN {coluna}",
            )

        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_pa_operacional_disponibilidade
        ON pa_caixas (estoque_operacional, disponibilidade, condicao)
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_estoque_eventos_caixa
        ON estoque_eventos (caixa_id, criado_em)
        """)

        cursor.execute("SELECT * FROM estoque_marcos WHERE tipo = 'MARCO_ZERO' LIMIT 1")
        marco = cursor.fetchone()
        if not marco:
            cursor.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM ordens_producao")
            legacy_max_op_id = int(cursor.fetchone()["max_id"] or 0)
            ativado_em = _agora()
            if DATABASE_URL:
                cursor.execute(q("""
                INSERT INTO estoque_marcos (
                    tipo, referencia_data, fuso_horario, legacy_max_op_id,
                    ativado_por, ativado_em, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING id
                """), (
                    "MARCO_ZERO", "2026-07-24", "America/Manaus",
                    legacy_max_op_id, _usuario(), ativado_em, "ATIVO",
                ))
                marco_id = cursor.fetchone()["id"]
            else:
                cursor.execute(q("""
                INSERT INTO estoque_marcos (
                    tipo, referencia_data, fuso_horario, legacy_max_op_id,
                    ativado_por, ativado_em, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """), (
                    "MARCO_ZERO", "2026-07-24", "America/Manaus",
                    legacy_max_op_id, _usuario(), ativado_em, "ATIVO",
                ))
                marco_id = cursor.lastrowid

            cursor.execute(q("""
            UPDATE ordens_producao
            SET estoque_classificacao = 'LEGADA',
                estoque_marco_id = ?
            WHERE id <= ?
            """), (marco_id, legacy_max_op_id))
            cursor.execute(q("""
            UPDATE ordens_producao
            SET estoque_classificacao = 'POS_MARCO',
                estoque_marco_id = ?
            WHERE id > ?
            """), (marco_id, legacy_max_op_id))

            # O PA presente na ativação é preservado, porém deixa de ser estoque
            # operacional e não pode ser selecionado em romaneio normal.
            cursor.execute("""
            UPDATE pa_caixas
            SET estoque_operacional = 0,
                disponibilidade = 'LEGADO',
                status = 'Histórico',
                reservado_expedicao_id = NULL
            """)
        conn.commit()
        _SCHEMA_ESTOQUE_CONFIAVEL_INICIALIZADO = True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def obter_marco_zero():
    criar_tabelas_estoque_confiavel()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM estoque_marcos WHERE tipo = 'MARCO_ZERO' LIMIT 1")
        return cursor.fetchone()
    finally:
        conn.close()


def ativar_estoque_op_encerrada(cursor, op_id):
    """Ativa uma única vez o PA elegível de uma OP encerrada.

    Caixas compostas por mais de uma OP só são ativadas quando todas forem
    pós-marco e estiverem encerradas.
    """
    cursor.execute(q("""
    SELECT cx.*
    FROM pa_caixas cx
    WHERE EXISTS (
        SELECT 1 FROM pa_caixa_composicao c
        WHERE c.caixa_id = cx.id AND c.op_id = ?
    )
      AND NOT EXISTS (
        SELECT 1
        FROM pa_caixa_composicao c
        INNER JOIN ordens_producao op ON op.id = c.op_id
        WHERE c.caixa_id = cx.id
          AND (
              COALESCE(op.estoque_classificacao, 'LEGADA') <> 'POS_MARCO'
              OR COALESCE(op.status, '') <> 'Encerrada'
          )
      )
    """), (op_id,))
    caixas = cursor.fetchall()
    for caixa in caixas:
        if int(caixa["estoque_operacional"] or 0) == 1:
            continue
        cursor.execute(q("""
        UPDATE pa_caixas
        SET estoque_operacional = 1,
            status = 'Em estoque',
            condicao = 'CONFORME',
            disponibilidade = 'DISPONIVEL',
            zona_estoque = 'Conforme',
            reservado_expedicao_id = NULL,
            formado_por = ?,
            formado_em = ?
        WHERE id = ? AND COALESCE(estoque_operacional, 0) = 0
        """), (_usuario(), _agora(), caixa["id"]))
        if cursor.rowcount == 1:
            _inserir_evento(
                cursor,
                caixa_id=caixa["id"],
                acao="FORMACAO_ESTOQUE",
                situacao_anterior=caixa["disponibilidade"] or STATUS_PENDENTE,
                situacao_nova=STATUS_DISPONIVEL,
                condicao_anterior=caixa["condicao"] or "CONFORME",
                condicao_nova="CONFORME",
                quantidade=caixa["quantidade_pacotes"] if caixa["unidade_estoque"] == "PACOTE" else caixa["quantidade_bandejas"],
                peso=None if caixa["unidade_estoque"] == "PACOTE" else caixa["peso_liquido"],
                idempotency_key=f"FORMACAO-PA-{caixa['id']}",
            )
    return len(caixas)


def ativar_estoque_da_op(op_id):
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        return ativar_estoque_op_encerrada(conn.cursor(), op_id)


def marcar_pa_pendente(cursor, caixa_id):
    """Classifica PA recém-criado sem torná-lo disponível antes do encerramento."""
    cursor.execute(q("""
    UPDATE pa_caixas
    SET estoque_operacional = 0,
        disponibilidade = 'PENDENTE_OP',
        condicao = 'CONFORME',
        zona_estoque = 'Conforme',
        reservado_expedicao_id = NULL
    WHERE id = ?
    """), (caixa_id,))


def buscar_estoque_operacional():
    criar_tabelas_estoque_confiavel()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""
        SELECT
            cx.*,
            le.nome AS local_estoque,
            MIN(comp.op_id) AS op_id
        FROM pa_caixas cx
        LEFT JOIN locais_estoque le ON le.id = cx.local_estoque_id
        LEFT JOIN pa_caixa_composicao comp ON comp.caixa_id = cx.id
        WHERE COALESCE(cx.estoque_operacional, 0) = 1
          AND cx.disponibilidade NOT IN ('TRANSFERIDO', 'EXPEDIDO', 'DESCARTADO', 'DEVOLVIDO')
        GROUP BY cx.id, le.nome
        ORDER BY cx.data_validade ASC, cx.id ASC
        """))
        itens = cursor.fetchall()
        cursor.execute(q("""
        SELECT
            COALESCE(COUNT(*), 0) AS itens_fisicos,
            COALESCE(SUM(peso_liquido), 0) AS peso_fisico,
            COALESCE(SUM(CASE WHEN unidade_estoque = 'PACOTE' THEN quantidade_pacotes ELSE 1 END), 0) AS unidades_fisicas,
            COALESCE(SUM(CASE
                WHEN unidade_estoque = 'PACOTE' AND condicao = 'CONFORME'
                    THEN quantidade_pacotes - COALESCE(quantidade_pacotes_reservados, 0)
                WHEN unidade_estoque <> 'PACOTE' AND disponibilidade = 'DISPONIVEL' AND condicao = 'CONFORME'
                    THEN 1 ELSE 0 END), 0) AS unidades_disponiveis,
            COALESCE(SUM(CASE
                WHEN unidade_estoque = 'PACOTE' THEN COALESCE(quantidade_pacotes_reservados, 0)
                WHEN disponibilidade = 'RESERVADO' THEN 1 ELSE 0 END), 0) AS unidades_reservadas,
            COALESCE(SUM(CASE
                WHEN condicao = 'NAO_CONFORME' AND disponibilidade = 'BLOQUEADO'
                    THEN CASE WHEN unidade_estoque = 'PACOTE' THEN quantidade_pacotes ELSE 1 END
                ELSE 0 END), 0) AS unidades_bloqueadas,
            COALESCE(SUM(CASE
                WHEN disponibilidade = 'REPROCESSAMENTO'
                    THEN CASE WHEN unidade_estoque = 'PACOTE' THEN quantidade_pacotes ELSE 1 END
                ELSE 0 END), 0) AS unidades_reprocessamento,
            COALESCE(SUM(CASE WHEN disponibilidade = 'DISPONIVEL' AND condicao = 'CONFORME' THEN 1 ELSE 0 END), 0) AS itens_disponiveis,
            COALESCE(SUM(CASE WHEN disponibilidade = 'DISPONIVEL' AND condicao = 'CONFORME' THEN peso_liquido ELSE 0 END), 0) AS peso_disponivel,
            COALESCE(SUM(CASE WHEN disponibilidade = 'RESERVADO' THEN 1 ELSE 0 END), 0) AS itens_reservados,
            COALESCE(SUM(CASE WHEN disponibilidade = 'RESERVADO' THEN peso_liquido ELSE 0 END), 0) AS peso_reservado,
            COALESCE(SUM(CASE WHEN condicao = 'NAO_CONFORME' AND disponibilidade = 'BLOQUEADO' THEN 1 ELSE 0 END), 0) AS itens_bloqueados,
            COALESCE(SUM(CASE WHEN condicao = 'NAO_CONFORME' AND disponibilidade = 'BLOQUEADO' THEN peso_liquido ELSE 0 END), 0) AS peso_bloqueado,
            COALESCE(SUM(CASE WHEN disponibilidade = 'REPROCESSAMENTO' THEN 1 ELSE 0 END), 0) AS itens_reprocessamento,
            COALESCE(SUM(CASE WHEN disponibilidade = 'REPROCESSAMENTO' THEN peso_liquido ELSE 0 END), 0) AS peso_reprocessamento,
            COALESCE(SUM(CASE WHEN NOT (
                (disponibilidade = 'DISPONIVEL' AND condicao = 'CONFORME')
                OR disponibilidade = 'RESERVADO'
                OR (condicao = 'NAO_CONFORME' AND disponibilidade = 'BLOQUEADO')
                OR disponibilidade = 'REPROCESSAMENTO'
            ) THEN 1 ELSE 0 END), 0) AS itens_outras_condicoes,
            COALESCE(SUM(CASE WHEN NOT (
                (disponibilidade = 'DISPONIVEL' AND condicao = 'CONFORME')
                OR disponibilidade = 'RESERVADO'
                OR (condicao = 'NAO_CONFORME' AND disponibilidade = 'BLOQUEADO')
                OR disponibilidade = 'REPROCESSAMENTO'
            ) THEN peso_liquido ELSE 0 END), 0) AS peso_outras_condicoes
        FROM pa_caixas
        WHERE estoque_operacional = 1
          AND disponibilidade NOT IN ('TRANSFERIDO', 'EXPEDIDO', 'DESCARTADO', 'DEVOLVIDO')
        """))
        resumo = dict(cursor.fetchone())
        resumo["unidades_outras_condicoes"] = max(
            0,
            float(resumo["unidades_fisicas"] or 0)
            - float(resumo["unidades_disponiveis"] or 0)
            - float(resumo["unidades_reservadas"] or 0)
            - float(resumo["unidades_bloqueadas"] or 0)
            - float(resumo["unidades_reprocessamento"] or 0),
        )
        return itens, resumo
    finally:
        conn.close()


def buscar_historico_estoque(limite=300):
    criar_tabelas_estoque_confiavel()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""
        SELECT ev.*, cx.codigo_caixa, cx.sku, e.numero_romaneio
        FROM estoque_eventos ev
        LEFT JOIN pa_caixas cx ON cx.id = ev.caixa_id
        LEFT JOIN expedicoes e ON e.id = ev.expedicao_id
        ORDER BY ev.criado_em DESC, ev.id DESC
        LIMIT ?
        """), (limite,))
        return cursor.fetchall()
    finally:
        conn.close()


def reservar_itens(expedicao_id, caixa_ids, quantidades_pacotes=None):
    """Reserva caixas inteiras ou uma quantidade inteira de pacotes de GI."""
    criar_tabelas_estoque_confiavel()
    ids = [int(item) for item in caixa_ids]
    quantidades_pacotes = quantidades_pacotes or {}
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Selecione itens distintos para reservar.")
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM expedicoes WHERE id = ?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if not romaneio or romaneio["status"] != "Aberto":
            raise ValueError("Somente romaneios abertos podem receber itens.")
        tipo = romaneio["tipo_movimentacao"]
        for caixa_id in ids:
            cursor.execute(q("""
            SELECT cx.*, MIN(comp.op_id) AS op_id
            FROM pa_caixas cx
            LEFT JOIN pa_caixa_composicao comp ON comp.caixa_id = cx.id
            WHERE cx.id = ?
            GROUP BY cx.id
            """), (caixa_id,))
            caixa = cursor.fetchone()
            if not caixa or int(caixa["estoque_operacional"] or 0) != 1:
                raise ValueError("Item inexistente ou fora do estoque operacional.")
            cursor.execute(q("""
            SELECT COUNT(*) AS total FROM expedicao_itens
            WHERE expedicao_id = ? AND caixa_id = ?
            """), (expedicao_id, caixa_id))
            if int(cursor.fetchone()["total"] or 0):
                raise ValueError("O item ja esta incluido neste romaneio.")
            situacao_origem = caixa["disponibilidade"]
            if tipo == "TRANSFERENCIA" and caixa["condicao"] != "CONFORME":
                raise ValueError("Produto nao conforme nao pode entrar em romaneio normal.")
            if tipo in {"DESCARTE", "DEVOLUCAO", "TRANSFERENCIA_AUTORIZADA"} and caixa["condicao"] != "NAO_CONFORME":
                raise ValueError("Este tipo de romaneio e destinado a Produto Nao Conforme.")

            if caixa["unidade_estoque"] == "PACOTE":
                total_pacotes = int(caixa["quantidade_pacotes"] or 0)
                reservados = int(caixa["quantidade_pacotes_reservados"] or 0)
                disponiveis = total_pacotes - reservados
                valor = quantidades_pacotes.get(str(caixa_id), quantidades_pacotes.get(caixa_id, disponiveis))
                if valor in (None, ""):
                    valor = disponiveis
                try:
                    quantidade = float(valor)
                except (TypeError, ValueError):
                    raise ValueError("Informe uma quantidade valida de pacotes.")
                if not quantidade.is_integer() or quantidade <= 0:
                    raise ValueError("A movimentacao de Galinha Inteira aceita somente pacotes inteiros.")
                quantidade = int(quantidade)
                if quantidade > disponiveis:
                    raise ValueError("A quantidade de pacotes excede o saldo disponivel.")
                cursor.execute(q("""
                UPDATE pa_caixas
                SET quantidade_pacotes_reservados = COALESCE(quantidade_pacotes_reservados, 0) + ?,
                    disponibilidade = CASE
                        WHEN COALESCE(quantidade_pacotes_reservados, 0) + ? = quantidade_pacotes
                        THEN 'RESERVADO' ELSE disponibilidade END
                WHERE id = ?
                  AND quantidade_pacotes - COALESCE(quantidade_pacotes_reservados, 0) >= ?
                """), (quantidade, quantidade, caixa_id, quantidade))
                if cursor.rowcount != 1:
                    raise ValueError(f"O saldo de {caixa['codigo_caixa']} foi reservado por outro romaneio.")
                galinhas = quantidade * int(caixa["galinhas_por_pacote"] or 0)
                cursor.execute(q("""
                INSERT INTO expedicao_itens (
                    expedicao_id, caixa_id, op_id, sku, quantidade_unidades,
                    quantidade_kg, situacao_anterior, condicao_anterior,
                    local_anterior_id, unidade_estoque, apresentacao,
                    galinhas_por_pacote, quantidade_pacotes, quantidade_galinhas,
                    peso_bruto, peso_tara, lote
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, 'PACOTE', ?, ?, ?, ?, NULL, NULL, ?)
                """), (
                    expedicao_id, caixa_id, caixa["op_id"], caixa["sku"], quantidade,
                    situacao_origem, caixa["condicao"], caixa["local_estoque_id"],
                    caixa["apresentacao"], caixa["galinhas_por_pacote"],
                    quantidade, galinhas, caixa["codigo_caixa"],
                ))
                peso_evento = None
                quantidade_evento = quantidade
            else:
                if situacao_origem not in {STATUS_DISPONIVEL, STATUS_BLOQUEADO}:
                    raise ValueError("O item nao esta disponivel para reserva.")
                cursor.execute(q("""
                UPDATE pa_caixas
                SET disponibilidade = 'RESERVADO', reservado_expedicao_id = ?
                WHERE id = ? AND disponibilidade = ?
                """), (expedicao_id, caixa_id, situacao_origem))
                if cursor.rowcount != 1:
                    raise ValueError(f"O item {caixa['codigo_caixa']} foi reservado por outro romaneio.")
                cursor.execute(q("""
                INSERT INTO expedicao_itens (
                    expedicao_id, caixa_id, op_id, sku, quantidade_unidades,
                    quantidade_kg, situacao_anterior, condicao_anterior,
                    local_anterior_id, unidade_estoque, apresentacao,
                    peso_bruto, peso_tara, lote
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'CAIXA', ?, ?, ?, ?)
                """), (
                    expedicao_id, caixa_id, caixa["op_id"], caixa["sku"],
                    caixa["quantidade_bandejas"], caixa["peso_liquido"],
                    situacao_origem, caixa["condicao"], caixa["local_estoque_id"],
                    caixa["apresentacao"], caixa["peso_bruto"], caixa["peso_tara"],
                    caixa["codigo_caixa"],
                ))
                peso_evento = caixa["peso_liquido"]
                quantidade_evento = caixa["quantidade_bandejas"]
            _inserir_evento(
                cursor,
                caixa_id=caixa_id,
                expedicao_id=expedicao_id,
                acao="RESERVA",
                situacao_anterior=situacao_origem,
                situacao_nova=STATUS_RESERVADO,
                condicao_anterior=caixa["condicao"],
                condicao_nova=caixa["condicao"],
                quantidade=quantidade_evento,
                peso=peso_evento,
            )


def remover_item_reservado(expedicao_id, caixa_id):
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("""
        SELECT i.*, cx.codigo_caixa, cx.quantidade_bandejas, cx.peso_liquido,
               cx.unidade_estoque AS unidade_atual
        FROM expedicao_itens i
        INNER JOIN expedicoes e ON e.id = i.expedicao_id
        INNER JOIN pa_caixas cx ON cx.id = i.caixa_id
        WHERE i.expedicao_id = ? AND i.caixa_id = ? AND e.status = 'Aberto'
        """), (expedicao_id, caixa_id))
        item = cursor.fetchone()
        if not item:
            raise ValueError("Item reservado não encontrado em romaneio aberto.")
        if item["unidade_atual"] == "PACOTE":
            cursor.execute(q("""
            UPDATE pa_caixas
            SET quantidade_pacotes_reservados = CASE
                    WHEN COALESCE(quantidade_pacotes_reservados, 0) > ?
                    THEN COALESCE(quantidade_pacotes_reservados, 0) - ?
                    ELSE 0 END,
                disponibilidade = CASE
                    WHEN COALESCE(quantidade_pacotes_reservados, 0) - ? >= quantidade_pacotes
                    THEN 'RESERVADO' ELSE ? END
            WHERE id = ?
            """), (
                int(item["quantidade_pacotes"] or 0),
                int(item["quantidade_pacotes"] or 0),
                int(item["quantidade_pacotes"] or 0),
                item["situacao_anterior"] or STATUS_DISPONIVEL,
                caixa_id,
            ))
        else:
            cursor.execute(q("""
            UPDATE pa_caixas
            SET disponibilidade = ?, reservado_expedicao_id = NULL
            WHERE id = ? AND reservado_expedicao_id = ?
            """), (item["situacao_anterior"] or STATUS_DISPONIVEL, caixa_id, expedicao_id))
        cursor.execute(q("""
        DELETE FROM expedicao_itens WHERE expedicao_id = ? AND caixa_id = ?
        """), (expedicao_id, caixa_id))
        _inserir_evento(
            cursor,
            caixa_id=caixa_id,
            expedicao_id=expedicao_id,
            acao="REMOCAO_RESERVA",
            situacao_anterior=STATUS_RESERVADO,
            situacao_nova=item["situacao_anterior"] or STATUS_DISPONIVEL,
            condicao_anterior=item["condicao_anterior"],
            condicao_nova=item["condicao_anterior"],
            quantidade=item["quantidade_pacotes"] if item["unidade_atual"] == "PACOTE" else item["quantidade_bandejas"],
            peso=None if item["unidade_atual"] == "PACOTE" else item["peso_liquido"],
        )


def resolver_destino_romaneio(cursor, tipo, destino):
    esperado = DESTINOS_CONTROLADOS.get(tipo)
    if not esperado or (destino or "").strip() != esperado:
        raise ValueError("O destino informado nao corresponde ao destino operacional permitido para este tipo.")
    if tipo in {"TRANSFERENCIA", "TRANSFERENCIA_AUTORIZADA"}:
        cursor.execute(q("""
        SELECT id FROM locais_estoque
        WHERE nome = ? AND COALESCE(ativo, 'Sim') = 'Sim'
        """), (esperado,))
        local = cursor.fetchone()
        if not local:
            raise ValueError("O destino selecionado nao corresponde a um local de estoque ativo.")
        return local["id"]
    return None


def concluir_romaneio(expedicao_id):
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM expedicoes WHERE id = ?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if not romaneio or romaneio["status"] != "Aberto":
            raise ValueError("Somente romaneios abertos podem ser concluidos.")
        tipo = romaneio["tipo_movimentacao"]
        destino_id = resolver_destino_romaneio(cursor, tipo, romaneio["destino"])
        cursor.execute(q("""
        SELECT i.*, cx.disponibilidade, cx.condicao,
               cx.quantidade_bandejas, cx.peso_liquido, cx.codigo_caixa,
               cx.unidade_estoque AS unidade_atual,
               cx.quantidade_pacotes AS pacotes_atuais,
               cx.quantidade_pacotes_reservados AS pacotes_reservados
        FROM expedicao_itens i
        LEFT JOIN pa_caixas cx ON cx.id = i.caixa_id
        WHERE i.expedicao_id = ?
        ORDER BY i.id
        """), (expedicao_id,))
        itens = cursor.fetchall()
        if not itens:
            raise ValueError("Inclua ao menos um item antes de concluir.")

        if tipo == "HISTORICO_MARCO_ZERO":
            momento = _agora()
            cursor.execute(q("""
            UPDATE expedicoes
            SET status = 'Concluído', concluido_em = ?, atualizado_em = ?,
                responsavel = COALESCE(NULLIF(responsavel, ''), ?)
            WHERE id = ? AND status = 'Aberto'
            """), (momento, momento, _usuario(), expedicao_id))
            registrar_evento_romaneio(
                cursor,
                expedicao_id,
                "CONCLUSAO_MZ",
                estado_anterior="Aberto",
                estado_novo="Concluído",
                dados_alterados={"concluido_em": momento},
                idempotency_key=f"CONCLUSAO-MZ-{expedicao_id}",
            )
            return

        situacao_final = {
            "TRANSFERENCIA": STATUS_TRANSFERIDO,
            "TRANSFERENCIA_AUTORIZADA": STATUS_TRANSFERIDO,
            "DESCARTE": STATUS_DESCARTADO,
            "DEVOLUCAO": STATUS_DEVOLVIDO,
        }.get(tipo)
        if not situacao_final:
            raise ValueError("O tipo de romaneio nao possui movimentacao final configurada.")

        for item in itens:
            if not item["caixa_id"]:
                raise ValueError("Romaneio operacional contem item sem posicao de estoque.")
            if item["unidade_atual"] == "PACOTE":
                quantidade = int(item["quantidade_pacotes"] or 0)
                total_atual = int(item["pacotes_atuais"] or 0)
                reservados = int(item["pacotes_reservados"] or 0)
                if quantidade <= 0 or reservados < quantidade or total_atual < quantidade:
                    raise ValueError(f"A reserva de {item['codigo_caixa']} nao esta mais integra.")
                restante = total_atual - quantidade
                reservados_restantes = reservados - quantidade
                galinhas_por_pacote = int(item["galinhas_por_pacote"] or 0)
                if restante > 0 and reservados_restantes >= restante:
                    disponibilidade_restante = STATUS_RESERVADO
                else:
                    disponibilidade_restante = (
                        STATUS_BLOQUEADO
                        if item["condicao"] == "NAO_CONFORME"
                        else STATUS_DISPONIVEL
                    )
                cursor.execute(q("""
                UPDATE pa_caixas
                SET quantidade_pacotes = ?,
                    quantidade_galinhas = ?,
                    quantidade_pacotes_reservados = ?,
                    disponibilidade = CASE WHEN ? = 0 THEN ? ELSE ? END,
                    status = CASE WHEN ? = 0 THEN ? ELSE 'Em estoque' END,
                    local_estoque_id = CASE
                        WHEN ? = 0 THEN COALESCE(?, local_estoque_id)
                        ELSE local_estoque_id END
                WHERE id = ?
                  AND quantidade_pacotes = ?
                  AND COALESCE(quantidade_pacotes_reservados, 0) >= ?
                """), (
                    restante,
                    restante * galinhas_por_pacote,
                    reservados_restantes,
                    restante,
                    situacao_final,
                    disponibilidade_restante,
                    restante,
                    situacao_final.replace("_", " ").title(),
                    restante,
                    destino_id,
                    item["caixa_id"],
                    total_atual,
                    quantidade,
                ))
                if cursor.rowcount != 1:
                    raise ValueError(f"Os pacotes de {item['codigo_caixa']} nao puderam ser baixados.")
                quantidade_evento = quantidade
                peso_evento = None
            else:
                if item["disponibilidade"] != STATUS_RESERVADO:
                    raise ValueError(f"O item {item['codigo_caixa']} perdeu a reserva.")
                cursor.execute(q("""
                UPDATE pa_caixas
                SET disponibilidade = ?, status = ?,
                    local_estoque_id = COALESCE(?, local_estoque_id),
                    reservado_expedicao_id = NULL
                WHERE id = ? AND reservado_expedicao_id = ?
                """), (
                    situacao_final,
                    situacao_final.replace("_", " ").title(),
                    destino_id,
                    item["caixa_id"],
                    expedicao_id,
                ))
                if cursor.rowcount != 1:
                    raise ValueError(f"O item {item['codigo_caixa']} nao pode ser baixado.")
                quantidade_evento = item["quantidade_bandejas"]
                peso_evento = item["peso_liquido"]
            _inserir_evento(
                cursor,
                caixa_id=item["caixa_id"],
                expedicao_id=expedicao_id,
                acao="CONFIRMACAO_ROMANEIO",
                situacao_anterior=STATUS_RESERVADO,
                situacao_nova=situacao_final,
                condicao_anterior=item["condicao"],
                condicao_nova=item["condicao"],
                quantidade=quantidade_evento,
                peso=peso_evento,
            )

        momento = _agora()
        cursor.execute(q("""
        UPDATE expedicoes
        SET status = 'Concluído', concluido_em = ?, atualizado_em = ?,
            destino_local_id = ?,
            responsavel = COALESCE(NULLIF(responsavel, ''), ?)
        WHERE id = ? AND status = 'Aberto'
        """), (momento, momento, destino_id, _usuario(), expedicao_id))
        registrar_evento_romaneio(
            cursor,
            expedicao_id,
            "CONCLUSAO_ROMANEIO",
            estado_anterior="Aberto",
            estado_novo="Concluído",
            dados_alterados={"destino": romaneio["destino"], "destino_local_id": destino_id},
            idempotency_key=f"CONCLUSAO-ROMANEIO-{expedicao_id}",
        )


def cancelar_romaneio(expedicao_id, justificativa):
    if not (justificativa or "").strip():
        raise ValueError("Informe a justificativa do cancelamento.")
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM expedicoes WHERE id = ?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if not romaneio or romaneio["status"] != "Aberto":
            raise ValueError("Somente romaneios abertos podem ser cancelados.")
        cursor.execute(q("""
        SELECT i.*, cx.quantidade_bandejas, cx.peso_liquido,
               cx.unidade_estoque AS unidade_atual
        FROM expedicao_itens i
        LEFT JOIN pa_caixas cx ON cx.id = i.caixa_id
        WHERE i.expedicao_id = ?
        """), (expedicao_id,))
        for item in cursor.fetchall():
            if item["caixa_id"]:
                if item["unidade_atual"] == "PACOTE":
                    quantidade = int(item["quantidade_pacotes"] or 0)
                    cursor.execute(q("""
                    UPDATE pa_caixas
                    SET quantidade_pacotes_reservados = CASE
                            WHEN COALESCE(quantidade_pacotes_reservados, 0) > ?
                            THEN COALESCE(quantidade_pacotes_reservados, 0) - ?
                            ELSE 0 END,
                        disponibilidade = CASE
                            WHEN COALESCE(quantidade_pacotes_reservados, 0) - ? >= quantidade_pacotes
                            THEN 'RESERVADO' ELSE ? END
                    WHERE id = ?
                    """), (
                        quantidade,
                        quantidade,
                        quantidade,
                        item["situacao_anterior"] or STATUS_DISPONIVEL,
                        item["caixa_id"],
                    ))
                else:
                    cursor.execute(q("""
                    UPDATE pa_caixas
                    SET disponibilidade = ?, reservado_expedicao_id = NULL
                    WHERE id = ? AND reservado_expedicao_id = ?
                    """), (item["situacao_anterior"] or STATUS_DISPONIVEL, item["caixa_id"], expedicao_id))
                _inserir_evento(
                    cursor,
                    caixa_id=item["caixa_id"],
                    expedicao_id=expedicao_id,
                    acao="CANCELAMENTO_ROMANEIO",
                    situacao_anterior=STATUS_RESERVADO,
                    situacao_nova=item["situacao_anterior"] or STATUS_DISPONIVEL,
                    condicao_anterior=item["condicao_anterior"],
                    condicao_nova=item["condicao_anterior"],
                    quantidade=item["quantidade_pacotes"] if item["unidade_atual"] == "PACOTE" else item["quantidade_bandejas"],
                    peso=None if item["unidade_atual"] == "PACOTE" else item["peso_liquido"],
                    justificativa=justificativa.strip(),
                )
        momento = _agora()
        cursor.execute(q("""
        UPDATE expedicoes
        SET status = 'Cancelado', cancelado_em = ?, atualizado_em = ?,
            justificativa = ?
        WHERE id = ?
        """), (momento, momento, justificativa.strip(), expedicao_id))
        registrar_evento_romaneio(
            cursor,
            expedicao_id,
            "CANCELAMENTO_MZ" if romaneio["tipo_movimentacao"] == "HISTORICO_MARCO_ZERO" else "CANCELAMENTO_ROMANEIO_DOCUMENTO",
            estado_anterior="Aberto",
            estado_novo="Cancelado",
            dados_alterados={"cancelado_em": momento},
            justificativa=justificativa.strip(),
            idempotency_key=f"CANCELAMENTO-ROMANEIO-{expedicao_id}",
        )


def estornar_romaneio(expedicao_id, justificativa):
    if not (justificativa or "").strip():
        raise ValueError("Informe a justificativa do estorno.")
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM expedicoes WHERE id = ?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if not romaneio or romaneio["status"] != "Concluído":
            raise ValueError("Somente romaneios concluídos podem ser estornados.")
        if romaneio["tipo_movimentacao"] == "HISTORICO_MARCO_ZERO":
            raise ValueError("O marco zero histórico não pode ser estornado operacionalmente.")
        cursor.execute(q("""
        SELECT i.*, cx.disponibilidade, cx.condicao, cx.quantidade_bandejas,
               cx.peso_liquido, cx.unidade_estoque AS unidade_atual,
               cx.quantidade_pacotes_reservados AS pacotes_reservados_atuais
        FROM expedicao_itens i
        INNER JOIN pa_caixas cx ON cx.id = i.caixa_id
        WHERE i.expedicao_id = ?
        """), (expedicao_id,))
        for item in cursor.fetchall():
            if item["unidade_atual"] == "PACOTE":
                if int(item["pacotes_reservados_atuais"] or 0) > 0:
                    raise ValueError("Nao e possivel estornar enquanto houver pacotes reservados em outro romaneio.")
                quantidade = int(item["quantidade_pacotes"] or 0)
                por_pacote = int(item["galinhas_por_pacote"] or 0)
                cursor.execute(q("""
                UPDATE pa_caixas
                SET quantidade_pacotes = COALESCE(quantidade_pacotes, 0) + ?,
                    quantidade_galinhas = COALESCE(quantidade_galinhas, 0) + ?,
                    quantidade_pacotes_reservados = 0,
                    disponibilidade = ?, status = 'Em estoque',
                    condicao = ?, local_estoque_id = ?,
                    reservado_expedicao_id = NULL
                WHERE id = ?
                """), (
                    quantidade,
                    quantidade * por_pacote,
                    item["situacao_anterior"] or STATUS_DISPONIVEL,
                    item["condicao_anterior"] or "CONFORME",
                    item["local_anterior_id"],
                    item["caixa_id"],
                ))
            else:
                cursor.execute(q("""
                UPDATE pa_caixas
                SET disponibilidade = ?,
                    status = 'Em estoque',
                    condicao = ?,
                    local_estoque_id = ?,
                    reservado_expedicao_id = NULL
                WHERE id = ?
                """), (
                    item["situacao_anterior"] or STATUS_DISPONIVEL,
                    item["condicao_anterior"] or "CONFORME",
                    item["local_anterior_id"],
                    item["caixa_id"],
                ))
            _inserir_evento(
                cursor,
                caixa_id=item["caixa_id"],
                expedicao_id=expedicao_id,
                acao="ESTORNO_ROMANEIO",
                situacao_anterior=item["disponibilidade"],
                situacao_nova=item["situacao_anterior"] or STATUS_DISPONIVEL,
                condicao_anterior=item["condicao"],
                condicao_nova=item["condicao_anterior"] or "CONFORME",
                quantidade=item["quantidade_pacotes"] if item["unidade_atual"] == "PACOTE" else item["quantidade_bandejas"],
                peso=None if item["unidade_atual"] == "PACOTE" else item["peso_liquido"],
                justificativa=justificativa.strip(),
            )
        cursor.execute(q("""
        UPDATE expedicoes
        SET status = 'Estornado', estornado_em = ?, atualizado_em = ?,
            justificativa = ?
        WHERE id = ?
        """), (_agora(), _agora(), justificativa.strip(), expedicao_id))
        registrar_evento_romaneio(
            cursor,
            expedicao_id,
            "ESTORNO_ROMANEIO_DOCUMENTO",
            estado_anterior="Concluído",
            estado_novo="Estornado",
            dados_alterados={"destino": romaneio["destino"]},
            justificativa=justificativa.strip(),
            idempotency_key=f"ESTORNO-ROMANEIO-{expedicao_id}",
        )


def bloquear_produto(caixa_id, motivo, observacao=""):
    if not (motivo or "").strip():
        raise ValueError("Informe o motivo da não conformidade.")
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pa_caixas WHERE id = ?"), (caixa_id,))
        caixa = cursor.fetchone()
        if not caixa or int(caixa["estoque_operacional"] or 0) != 1:
            raise ValueError("Item não encontrado no estoque operacional.")
        if int(caixa["quantidade_pacotes_reservados"] or 0) > 0:
            raise ValueError("Posição com pacotes reservados não pode ser bloqueada.")
        if caixa["disponibilidade"] not in {STATUS_DISPONIVEL, STATUS_BLOQUEADO}:
            raise ValueError("Item reservado ou já movimentado não pode ser bloqueado.")
        cursor.execute(q("""
        UPDATE pa_caixas
        SET condicao = 'NAO_CONFORME', disponibilidade = 'BLOQUEADO',
            zona_estoque = 'Produto Não Conforme',
            motivo_nao_conformidade = ?
        WHERE id = ?
        """), (motivo.strip(), caixa_id))
        _inserir_evento(
            cursor,
            caixa_id=caixa_id,
            acao="BLOQUEIO_NAO_CONFORMIDADE",
            situacao_anterior=caixa["disponibilidade"],
            situacao_nova=STATUS_BLOQUEADO,
            condicao_anterior=caixa["condicao"],
            condicao_nova="NAO_CONFORME",
            quantidade=caixa["quantidade_bandejas"],
            peso=caixa["peso_liquido"],
            justificativa=motivo.strip(),
            observacao=(observacao or "").strip(),
        )


def destinar_produto(caixa_id, destino, justificativa):
    destinos = {
        "LIBERAR": ("CONFORME", STATUS_DISPONIVEL, "Conforme"),
        "REPROCESSAMENTO": ("NAO_CONFORME", STATUS_REPROCESSAMENTO, "Produto Não Conforme"),
        "PERMANECER_BLOQUEADO": ("NAO_CONFORME", STATUS_BLOQUEADO, "Produto Não Conforme"),
    }
    if destino not in destinos:
        raise ValueError("Destinação inválida ou dependente de romaneio específico.")
    if not (justificativa or "").strip():
        raise ValueError("Informe a justificativa da destinação.")
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pa_caixas WHERE id = ?"), (caixa_id,))
        caixa = cursor.fetchone()
        if not caixa or caixa["condicao"] != "NAO_CONFORME":
            raise ValueError("Produto Não Conforme não encontrado.")
        condicao, situacao, zona = destinos[destino]
        cursor.execute(q("""
        UPDATE pa_caixas
        SET condicao = ?, disponibilidade = ?, zona_estoque = ?,
            motivo_nao_conformidade = CASE WHEN ? = 'CONFORME' THEN NULL ELSE motivo_nao_conformidade END
        WHERE id = ?
        """), (condicao, situacao, zona, condicao, caixa_id))
        _inserir_evento(
            cursor,
            caixa_id=caixa_id,
            acao=destino,
            situacao_anterior=caixa["disponibilidade"],
            situacao_nova=situacao,
            condicao_anterior=caixa["condicao"],
            condicao_nova=condicao,
            quantidade=caixa["quantidade_bandejas"],
            peso=caixa["peso_liquido"],
            justificativa=justificativa.strip(),
        )


def registrar_emissao_romaneio(expedicao_id):
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT status FROM expedicoes WHERE id = ?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if not romaneio:
            raise ValueError("Romaneio nao encontrado.")
        momento = _agora()
        cursor.execute(q("""
        UPDATE expedicoes SET emitido_por = ?, emitido_em = ?
        WHERE id = ?
        """), (_usuario(), momento, expedicao_id))
        registrar_evento_romaneio(
            cursor,
            expedicao_id,
            "EMISSAO_ROMANEIO",
            estado_anterior=romaneio["status"],
            estado_novo=romaneio["status"],
            dados_alterados={"emitido_por": _usuario(), "emitido_em": momento},
        )
    return momento


def registrar_itens_historicos(expedicao_id, linhas):
    """Registra o MZ por apresentação, sem criar ou alterar estoque operacional."""
    criar_tabelas_estoque_confiavel()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM expedicoes WHERE id = ?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if (
            not romaneio
            or romaneio["tipo_movimentacao"] != "HISTORICO_MARCO_ZERO"
            or romaneio["status"] != "Aberto"
        ):
            raise ValueError("Romaneio historico aberto nao encontrado.")
        cursor.execute(q("""
        SELECT sku, quantidade_unidades, quantidade_kg, apresentacao,
               quantidade_pacotes, galinhas_por_pacote, quantidade_galinhas
        FROM expedicao_itens WHERE expedicao_id = ? ORDER BY id
        """), (expedicao_id,))
        anteriores = [dict(item) for item in cursor.fetchall()]
        cursor.execute(q("DELETE FROM expedicao_itens WHERE expedicao_id = ?"), (expedicao_id,))
        novos = []
        for linha in linhas:
            sku = (linha.get("sku") or "").strip()
            if sku == "Galinha Inteira":
                pacotes = float(linha.get("quantidade_pacotes") or 0)
                por_pacote = int(linha.get("galinhas_por_pacote") or 0)
                if pacotes < 0 or not pacotes.is_integer() or por_pacote not in {1, 2}:
                    raise ValueError("Os pacotes V1 e V2 do MZ devem ser quantidades inteiras.")
                pacotes = int(pacotes)
                if not pacotes:
                    continue
                galinhas = pacotes * por_pacote
                apresentacao = f"Pacote com {por_pacote} galinha" + ("" if por_pacote == 1 else "s")
                cursor.execute(q("""
                INSERT INTO expedicao_itens (
                    expedicao_id, caixa_id, op_id, sku, quantidade_unidades,
                    quantidade_kg, unidade_estoque, apresentacao,
                    galinhas_por_pacote, quantidade_pacotes, quantidade_galinhas
                ) VALUES (?, NULL, NULL, ?, ?, NULL, 'PACOTE', ?, ?, ?, ?)
                """), (
                    expedicao_id, sku, pacotes, apresentacao,
                    por_pacote, pacotes, galinhas,
                ))
                novos.append({
                    "sku": sku,
                    "apresentacao": apresentacao,
                    "quantidade_pacotes": pacotes,
                    "galinhas_por_pacote": por_pacote,
                    "quantidade_galinhas": galinhas,
                })
            elif sku == "Galinha Cortada":
                caixas = float(linha.get("quantidade") or 0)
                peso = float(linha.get("peso") or 0)
                if caixas < 0 or peso < 0 or (caixas == 0 and peso == 0):
                    continue
                cursor.execute(q("""
                INSERT INTO expedicao_itens (
                    expedicao_id, caixa_id, op_id, sku,
                    quantidade_unidades, quantidade_kg, unidade_estoque
                ) VALUES (?, NULL, NULL, ?, ?, ?, 'CAIXA')
                """), (expedicao_id, sku, caixas, peso))
                novos.append({"sku": sku, "quantidade_caixas": caixas, "peso": peso})
        if not novos:
            raise ValueError("Informe ao menos um total historico.")
        registrar_evento_romaneio(
            cursor,
            expedicao_id,
            "TOTAIS_MZ_ALTERADOS",
            estado_anterior="Aberto",
            estado_novo="Aberto",
            dados_alterados={"antes": anteriores, "depois": novos},
        )


def editar_romaneio_aberto(expedicao_id, form):
    """Edita somente o cabeçalho de documento ainda aberto."""
    criar_tabelas_estoque_confiavel()
    data = (form.get("data") or "").strip()
    origem = (form.get("origem") or "").strip()
    destino = (form.get("destino") or "").strip()
    if not data or not origem or not destino:
        raise ValueError("Informe data, origem e destino.")
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM expedicoes WHERE id = ?"), (expedicao_id,))
        romaneio = cursor.fetchone()
        if not romaneio or romaneio["status"] != "Aberto":
            raise ValueError("Somente romaneios abertos podem ser editados.")
        destino = DESTINOS_CONTROLADOS.get(romaneio["tipo_movimentacao"])
        if not destino:
            raise ValueError("O tipo de romaneio nao possui destino operacional configurado.")
        cursor.execute(q("""
        UPDATE expedicoes
        SET data = ?, origem = ?, destino = ?, responsavel = ?,
            observacoes = ?, atualizado_em = ?
        WHERE id = ? AND status = 'Aberto'
        """), (
            data,
            origem,
            destino,
            (form.get("responsavel") or "").strip(),
            (form.get("observacoes") or "").strip(),
            _agora(),
            expedicao_id,
        ))
        registrar_evento_romaneio(
            cursor,
            expedicao_id,
            "CABECALHO_ROMANEIO_ALTERADO",
            estado_anterior="Aberto",
            estado_novo="Aberto",
            dados_alterados={
                "antes": {
                    "data": romaneio["data"],
                    "origem": romaneio["origem"],
                    "destino": romaneio["destino"],
                    "responsavel": romaneio["responsavel"],
                    "observacoes": romaneio["observacoes"],
                },
                "depois": {
                    "data": data,
                    "origem": origem,
                    "destino": destino,
                    "responsavel": (form.get("responsavel") or "").strip(),
                    "observacoes": (form.get("observacoes") or "").strip(),
                },
            },
        )
