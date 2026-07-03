from database import DATABASE_URL, conectar, q


TIPOS_MANUTENCAO = [
    "Corretiva",
    "Preventiva",
    "Preditiva",
    "Melhoria",
]

PRIORIDADES_MANUTENCAO = [
    "Baixa",
    "Media",
    "Alta",
    "Critica",
]

STATUS_MANUTENCAO = [
    "Aberta",
    "Em andamento",
    "Aguardando peca",
    "Concluida",
    "Cancelada",
]


def _executar_alteracao(cursor, conn, comando):
    try:
        cursor.execute(q(comando))
        conn.commit()
    except Exception:
        conn.rollback()


def criar_tabelas_manutencao():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_equipamentos (
            id SERIAL PRIMARY KEY,
            codigo TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            setor TEXT NOT NULL,
            fabricante TEXT,
            modelo TEXT,
            numero_serie TEXT,
            criticidade TEXT DEFAULT 'Media',
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordens (
            id SERIAL PRIMARY KEY,
            equipamento_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            prioridade TEXT NOT NULL,
            status TEXT DEFAULT 'Aberta',
            data_abertura TEXT NOT NULL,
            data_prevista TEXT,
            data_conclusao TEXT,
            solicitante TEXT,
            responsavel TEXT,
            descricao TEXT NOT NULL,
            diagnostico TEXT,
            solucao TEXT,
            horas_paradas REAL DEFAULT 0,
            custo_estimado REAL DEFAULT 0,
            custo_real REAL DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_equipamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nome TEXT NOT NULL,
            setor TEXT NOT NULL,
            fabricante TEXT,
            modelo TEXT,
            numero_serie TEXT,
            criticidade TEXT DEFAULT 'Media',
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipamento_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            prioridade TEXT NOT NULL,
            status TEXT DEFAULT 'Aberta',
            data_abertura TEXT NOT NULL,
            data_prevista TEXT,
            data_conclusao TEXT,
            solicitante TEXT,
            responsavel TEXT,
            descricao TEXT NOT NULL,
            diagnostico TEXT,
            solucao TEXT,
            horas_paradas REAL DEFAULT 0,
            custo_estimado REAL DEFAULT 0,
            custo_real REAL DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()

    alteracoes = [
        "ALTER TABLE manutencao_ordens ADD COLUMN op_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN parada_id INTEGER",
        "ALTER TABLE manutencao_ordens ADD COLUMN motivo_parada TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN hora_abertura TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN hora_conclusao TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN pecas_utilizadas TEXT",
        "ALTER TABLE manutencao_ordens ADD COLUMN observacoes_finais TEXT",
    ]

    for comando in alteracoes:
        _executar_alteracao(cursor, conn, comando)

    try:
        cursor.execute(q("""
        UPDATE manutencao_equipamentos
        SET status = ?
        WHERE COALESCE(status, '') = ?
        """), ("Operacional", "Ativo"))
        conn.commit()
    except Exception:
        conn.rollback()

    conn.close()


def inserir_equipamento(dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    INSERT INTO manutencao_equipamentos (
        codigo,
        nome,
        setor,
        fabricante,
        modelo,
        numero_serie,
        criticidade,
        status,
        observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), dados)
    conn.commit()
    conn.close()


def equipamento_existe(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT id FROM manutencao_equipamentos WHERE id = ?"), (equipamento_id,))
    equipamento = cursor.fetchone()
    conn.close()
    return equipamento


def inserir_ordem(dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    INSERT INTO manutencao_ordens (
        equipamento_id,
        op_id,
        parada_id,
        tipo,
        prioridade,
        status,
        data_abertura,
        hora_abertura,
        data_prevista,
        solicitante,
        responsavel,
        descricao,
        motivo_parada,
        custo_estimado
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), dados)
    cursor.execute(q("""
    UPDATE manutencao_equipamentos
    SET status = ?
    WHERE id = ?
    """), ("Em Manutencao", dados[0]))
    conn.commit()
    cursor.execute("SELECT LASTVAL() as id" if DATABASE_URL else "SELECT last_insert_rowid() as id")
    ordem = cursor.fetchone()
    conn.close()
    return ordem["id"]


def atualizar_ordem(ordem_id, dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_ordens
    SET
        status = ?,
        data_conclusao = ?,
        responsavel = ?,
        diagnostico = ?,
        solucao = ?,
        horas_paradas = ?,
        custo_real = ?,
        hora_conclusao = ?,
        pecas_utilizadas = ?,
        observacoes_finais = ?
    WHERE id = ?
    """), (*dados, ordem_id))
    conn.commit()
    conn.close()


def buscar_ordem_por_id(ordem_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_ordens
    WHERE id = ?
    """), (ordem_id,))
    ordem = cursor.fetchone()
    conn.close()
    return ordem


def atualizar_status_equipamento(equipamento_id, status):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_equipamentos
    SET status = ?
    WHERE id = ?
    """), (status, equipamento_id))
    conn.commit()
    conn.close()


def buscar_equipamento_por_id(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    WHERE id = ?
    """), (equipamento_id,))
    equipamento = cursor.fetchone()
    conn.close()
    return equipamento


def vincular_ordem_a_parada(parada_id, ordem_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE apontamentos_paradas
    SET manutencao_ordem_id = ?,
        manutencao_aberta = ?
    WHERE id = ?
    """), (ordem_id, "Sim", parada_id))
    conn.commit()
    conn.close()


def encerrar_parada_por_ordem(parada_id, data_fim, hora_fim, horas_paradas):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE apontamentos_paradas
    SET data_fim = ?,
        hora_fim = ?,
        horas_paradas = ?,
        encerrada_por_manutencao = ?
    WHERE id = ?
    """), (data_fim, hora_fim, horas_paradas, "Sim", parada_id))
    conn.commit()
    conn.close()


def listar_equipamentos():
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    ORDER BY setor ASC, nome ASC
    """))
    equipamentos = cursor.fetchall()
    conn.close()
    return equipamentos


def listar_ordens(status_filtro="Todos", equipamento_id=""):
    criar_tabelas_manutencao()
    filtros = []
    parametros = []

    if status_filtro and status_filtro != "Todos":
        filtros.append("o.status = ?")
        parametros.append(status_filtro)

    if equipamento_id:
        filtros.append("o.equipamento_id = ?")
        parametros.append(int(equipamento_id))

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT
        o.*,
        e.codigo AS equipamento_codigo,
        e.nome AS equipamento_nome,
        e.setor AS equipamento_setor,
        e.criticidade AS equipamento_criticidade,
        o.op_id,
        o.parada_id,
        o.motivo_parada,
        o.hora_abertura,
        o.hora_conclusao,
        o.pecas_utilizadas,
        o.observacoes_finais
    FROM manutencao_ordens o
    JOIN manutencao_equipamentos e ON e.id = o.equipamento_id
    {where}
    ORDER BY
        CASE o.status
            WHEN 'Aberta' THEN 1
            WHEN 'Em andamento' THEN 2
            WHEN 'Aguardando peca' THEN 3
            WHEN 'Concluida' THEN 4
            ELSE 5
        END,
        o.data_abertura DESC,
        o.id DESC
    """), tuple(parametros))
    ordens = cursor.fetchall()
    conn.close()
    return ordens
