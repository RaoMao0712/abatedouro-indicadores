from functools import wraps
import os
import threading

import database
from database import DATABASE_URL, conectar, q


ROTINAS_ESTRUTURAIS_EXECUTADAS = set()
ROTINAS_ESTRUTURAIS_LOCK = threading.RLock()


def executar_rotina_estrutural_uma_vez(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        destino_banco = database.DATABASE_URL or os.path.abspath(database.DB_NAME)
        chave = (func.__name__, destino_banco)

        with ROTINAS_ESTRUTURAIS_LOCK:
            if chave in ROTINAS_ESTRUTURAIS_EXECUTADAS:
                return None

            resultado = func(*args, **kwargs)
            ROTINAS_ESTRUTURAIS_EXECUTADAS.add(chave)
            return resultado

    return wrapper


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


@executar_rotina_estrutural_uma_vez
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

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordem_recursos (
            id SERIAL PRIMARY KEY,
            ordem_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            quantidade REAL DEFAULT 0,
            unidade TEXT,
            fornecedor TEXT,
            valor_estimado REAL DEFAULT 0,
            status TEXT DEFAULT 'Pendente',
            observacoes TEXT,
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

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manutencao_ordem_recursos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ordem_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            quantidade REAL DEFAULT 0,
            unidade TEXT,
            fornecedor TEXT,
            valor_estimado REAL DEFAULT 0,
            status TEXT DEFAULT 'Pendente',
            observacoes TEXT,
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


def atualizar_equipamento(equipamento_id, dados):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    UPDATE manutencao_equipamentos
    SET
        codigo = ?,
        nome = ?,
        setor = ?,
        fabricante = ?,
        modelo = ?,
        numero_serie = ?,
        criticidade = ?,
        status = ?,
        observacoes = ?
    WHERE id = ?
    """), (*dados, equipamento_id))
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


def buscar_equipamento_por_codigo(codigo):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM manutencao_equipamentos
    WHERE codigo = ?
    """), (codigo,))
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


def listar_equipamentos_filtrados(busca=""):
    criar_tabelas_manutencao()
    termo = (busca or "").strip()
    parametros = []
    where = ""

    if termo:
        where = """
        WHERE LOWER(codigo) LIKE ?
           OR LOWER(nome) LIKE ?
           OR LOWER(setor) LIKE ?
           OR LOWER(fabricante) LIKE ?
           OR LOWER(modelo) LIKE ?
           OR LOWER(status) LIKE ?
        """
        like = f"%{termo.lower()}%"
        parametros = [like, like, like, like, like, like]

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT *
    FROM manutencao_equipamentos
    {where}
    ORDER BY setor ASC, nome ASC
    """), tuple(parametros))
    equipamentos = cursor.fetchall()
    conn.close()
    return equipamentos


def contar_ordens_por_equipamento(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT COUNT(*) as total
    FROM manutencao_ordens
    WHERE equipamento_id = ?
    """), (equipamento_id,))
    total = cursor.fetchone()["total"]
    conn.close()
    return int(total or 0)


def excluir_equipamento(equipamento_id):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    DELETE FROM manutencao_equipamentos
    WHERE id = ?
    """), (equipamento_id,))
    conn.commit()
    conn.close()


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


def listar_recursos_por_ordens(ordem_ids):
    criar_tabelas_manutencao()
    if not ordem_ids:
        return {}

    placeholders = ", ".join(["?"] * len(ordem_ids))
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT *
    FROM manutencao_ordem_recursos
    WHERE ordem_id IN ({placeholders})
    ORDER BY id ASC
    """), tuple(ordem_ids))
    recursos = cursor.fetchall()
    conn.close()

    recursos_por_ordem = {}
    for recurso in recursos:
        chave = str(recurso["ordem_id"])
        recursos_por_ordem.setdefault(chave, []).append(recurso)
    return recursos_por_ordem


def salvar_recursos_ordem(ordem_id, linhas):
    criar_tabelas_manutencao()
    conn = conectar()
    cursor = conn.cursor()

    for linha in linhas:
        recurso_id = int(linha.get("id") or 0)

        if linha.get("remover") == "Sim":
            if recurso_id:
                cursor.execute(q("""
                DELETE FROM manutencao_ordem_recursos
                WHERE id = ? AND ordem_id = ?
                """), (recurso_id, ordem_id))
            continue

        descricao = (linha.get("descricao") or "").strip()
        if not descricao:
            continue

        dados = (
            ordem_id,
            linha.get("tipo") or "Material",
            descricao,
            float(linha.get("quantidade") or 0),
            (linha.get("unidade") or "").strip(),
            (linha.get("fornecedor") or "").strip(),
            float(linha.get("valor_estimado") or 0),
            linha.get("status") or "Pendente",
            (linha.get("observacoes") or "").strip(),
        )

        if recurso_id:
            cursor.execute(q("""
            UPDATE manutencao_ordem_recursos
            SET
                tipo = ?,
                descricao = ?,
                quantidade = ?,
                unidade = ?,
                fornecedor = ?,
                valor_estimado = ?,
                status = ?,
                observacoes = ?
            WHERE id = ? AND ordem_id = ?
            """), (*dados[1:], recurso_id, ordem_id))
        else:
            cursor.execute(q("""
            INSERT INTO manutencao_ordem_recursos (
                ordem_id,
                tipo,
                descricao,
                quantidade,
                unidade,
                fornecedor,
                valor_estimado,
                status,
                observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), dados)

    conn.commit()
    conn.close()
