"""Persistencia dos cadastros operacionais compartilhados."""

from database import DATABASE_URL, conectar, q, transaction


def criar_tabela_locais():
    conn = conectar(); cursor = conn.cursor()
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(q(f"""CREATE TABLE IF NOT EXISTS cadastros_locais (
        id {pk}, tipo TEXT NOT NULL, nome TEXT NOT NULL, setor TEXT NOT NULL,
        classificacao_iluminacao TEXT, status TEXT DEFAULT 'Ativo',
        criado_em {timestamp} DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(tipo, nome, setor)
    )"""))
    conn.commit(); conn.close()


def listar_locais(tipo=None):
    conn = conectar(); cursor = conn.cursor()
    sql, params = "SELECT * FROM cadastros_locais WHERE status = 'Ativo'", []
    if tipo:
        sql += " AND tipo = ?"; params.append(tipo)
    cursor.execute(q(sql + " ORDER BY setor, nome"), tuple(params))
    rows = cursor.fetchall(); conn.close(); return rows


def inserir_local(tipo, nome, setor, classificacao):
    with transaction() as conn:
        conn.cursor().execute(q("""INSERT INTO cadastros_locais
            (tipo, nome, setor, classificacao_iluminacao) VALUES (?, ?, ?, ?)"""),
            (tipo, nome, setor, classificacao or None))


def buscar_local(local_id):
    conn = conectar(); cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM cadastros_locais WHERE id = ? AND status = 'Ativo'"), (local_id,))
    row = cursor.fetchone(); conn.close(); return row
