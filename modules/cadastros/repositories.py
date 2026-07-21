"""Persistencia dos cadastros operacionais compartilhados."""

from database import DATABASE_URL, conectar, q, transaction
from utils import setores_padrao


def _executar_alteracao(cursor, sql):
    try:
        cursor.execute(q(sql))
    except Exception:
        pass


def criar_tabela_setores():
    conn = conectar(); cursor = conn.cursor()
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(q(f"""CREATE TABLE IF NOT EXISTS cadastros_setores (
        id {pk}, nome TEXT NOT NULL UNIQUE, status TEXT DEFAULT 'Ativo',
        criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP
    )"""))
    for setor in setores_padrao():
        if DATABASE_URL:
            cursor.execute(
                "INSERT INTO cadastros_setores (nome, status) VALUES (%s, 'Ativo') ON CONFLICT (nome) DO NOTHING",
                (setor,)
            )
        else:
            cursor.execute("INSERT OR IGNORE INTO cadastros_setores (nome, status) VALUES (?, 'Ativo')", (setor,))
    conn.commit(); conn.close()


def criar_tabela_locais():
    criar_tabela_setores()
    conn = conectar(); cursor = conn.cursor()
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(q(f"""CREATE TABLE IF NOT EXISTS cadastros_locais (
        id {pk}, tipo TEXT NOT NULL, nome TEXT NOT NULL, setor TEXT NOT NULL,
        classificacao_iluminacao TEXT, status TEXT DEFAULT 'Ativo',
        criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(tipo, nome, setor)
    )"""))
    if DATABASE_URL:
        _executar_alteracao(cursor, "ALTER TABLE cadastros_locais ADD COLUMN IF NOT EXISTS setor_id INTEGER")
        _executar_alteracao(cursor, "ALTER TABLE cadastros_locais ADD COLUMN IF NOT EXISTS descricao TEXT")
        _executar_alteracao(cursor, "ALTER TABLE cadastros_locais ADD COLUMN IF NOT EXISTS ambiente_id INTEGER")
    else:
        _executar_alteracao(cursor, "ALTER TABLE cadastros_locais ADD COLUMN setor_id INTEGER")
        _executar_alteracao(cursor, "ALTER TABLE cadastros_locais ADD COLUMN descricao TEXT")
        _executar_alteracao(cursor, "ALTER TABLE cadastros_locais ADD COLUMN ambiente_id INTEGER")
    conn.commit(); conn.close()


def listar_setores(apenas_ativos=True):
    criar_tabela_setores()
    conn = conectar(); cursor = conn.cursor()
    sql = "SELECT * FROM cadastros_setores"
    params = []
    if apenas_ativos:
        sql += " WHERE status = ?"
        params.append("Ativo")
    cursor.execute(q(sql + " ORDER BY nome"), tuple(params))
    rows = cursor.fetchall(); conn.close(); return rows


def buscar_setor(setor_id, apenas_ativo=True):
    if not setor_id:
        return None
    criar_tabela_setores()
    conn = conectar(); cursor = conn.cursor()
    sql = "SELECT * FROM cadastros_setores WHERE id = ?"
    params = [int(setor_id)]
    if apenas_ativo:
        sql += " AND status = ?"
        params.append("Ativo")
    cursor.execute(q(sql), tuple(params))
    row = cursor.fetchone(); conn.close(); return row


def buscar_setor_por_nome(nome):
    criar_tabela_setores()
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM cadastros_setores WHERE nome = ?"), ((nome or "").strip(),))
    row = cursor.fetchone(); conn.close(); return row


def inserir_setor(nome):
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe o nome do setor.")
    with transaction() as conn:
        conn.cursor().execute(q("INSERT INTO cadastros_setores (nome, status) VALUES (?, 'Ativo')"), (nome,))


def inativar_setor(setor_id):
    with transaction() as conn:
        conn.cursor().execute(q("UPDATE cadastros_setores SET status='Inativo' WHERE id=?"), (int(setor_id),))


def listar_locais(tipo=None, setor_id=None, apenas_ativos=True):
    criar_tabela_locais()
    conn = conectar(); cursor = conn.cursor()
    sql, params = """SELECT l.*, COALESCE(s.nome, l.setor) AS setor_nome,
        a.nome AS ambiente_nome
        FROM cadastros_locais l
        LEFT JOIN cadastros_setores s ON s.id = l.setor_id
        LEFT JOIN cadastros_locais a ON a.id = l.ambiente_id
        WHERE 1=1""", []
    if apenas_ativos:
        sql += " AND l.status = 'Ativo'"
    if tipo:
        sql += " AND l.tipo = ?"; params.append(tipo)
    if setor_id:
        setor = buscar_setor(setor_id)
        sql += " AND (l.setor_id = ? OR (l.setor_id IS NULL AND l.setor = ?))"
        params.extend([int(setor_id), setor["nome"] if setor else ""])
    cursor.execute(q(sql + " ORDER BY COALESCE(s.nome, l.setor), l.nome"), tuple(params))
    rows = cursor.fetchall(); conn.close(); return rows


def inserir_local(tipo, nome, setor, classificacao, descricao="", setor_id=None, ambiente_id=None):
    criar_tabela_locais()
    setor_nome = (setor or "").strip()
    if setor_id:
        setor_row = buscar_setor(setor_id)
        if not setor_row:
            raise ValueError("Setor cadastrado nao encontrado ou inativo.")
        setor_nome = setor_row["nome"]
    elif setor_nome:
        setor_row = buscar_setor_por_nome(setor_nome)
        if setor_row:
            setor_id = setor_row["id"]
    with transaction() as conn:
        conn.cursor().execute(q("""INSERT INTO cadastros_locais
            (tipo, nome, setor, classificacao_iluminacao, setor_id, descricao, ambiente_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)"""),
            (tipo, nome, setor_nome, classificacao or None, setor_id, descricao or None, ambiente_id))


def buscar_local(local_id, apenas_ativo=True):
    criar_tabela_locais()
    conn = conectar(); cursor = conn.cursor()
    sql = """SELECT l.*, COALESCE(s.nome, l.setor) AS setor_nome, a.nome AS ambiente_nome
        FROM cadastros_locais l
        LEFT JOIN cadastros_setores s ON s.id = l.setor_id
        LEFT JOIN cadastros_locais a ON a.id = l.ambiente_id
        WHERE l.id = ?"""
    params = [local_id]
    if apenas_ativo:
        sql += " AND l.status = 'Ativo'"
    cursor.execute(q(sql), tuple(params))
    row = cursor.fetchone(); conn.close(); return row


def inativar_local(local_id):
    with transaction() as conn:
        conn.cursor().execute(q("UPDATE cadastros_locais SET status='Inativo' WHERE id=?"), (int(local_id),))
