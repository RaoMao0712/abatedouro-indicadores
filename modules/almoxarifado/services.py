"""Servicos do modulo de Almoxarifado."""

from database import DATABASE_URL, conectar, q


CATEGORIAS_ALMOXARIFADO = [
    "Matéria-prima",
    "Embalagem",
    "Produto Químico",
    "Peça de Reposição",
    "EPI",
    "Material de Limpeza",
    "Material de Escritório",
    "Combustível / Lubrificante",
    "Outros"
]

UNIDADES_ALMOXARIFADO = [
    "Kg",
    "Un",
    "Cx",
    "Pacote",
    "Litro",
    "Metro",
    "Par",
    "Galão",
    "Saco"
]


def criar_tabelas_almoxarifado():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_insumos (
            id SERIAL PRIMARY KEY,
            descricao TEXT NOT NULL UNIQUE,
            categoria TEXT NOT NULL,
            unidade TEXT NOT NULL,
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descricao TEXT NOT NULL UNIQUE,
            categoria TEXT NOT NULL,
            unidade TEXT NOT NULL,
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()


def salvar_insumo_almoxarifado(form):
    criar_tabelas_almoxarifado()

    descricao = form.get("descricao", "").strip()
    categoria = form.get("categoria", "").strip()
    unidade = form.get("unidade", "").strip()
    ativo = form.get("ativo", "Sim").strip()
    observacoes = form.get("observacoes", "").strip()

    if not descricao:
        raise ValueError("Informe a descrição do insumo.")

    if categoria not in CATEGORIAS_ALMOXARIFADO:
        raise ValueError("Categoria inválida.")

    if unidade not in UNIDADES_ALMOXARIFADO:
        raise ValueError("Unidade inválida.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO almoxarifado_insumos (
        descricao, categoria, unidade, ativo, observacoes
    ) VALUES (?, ?, ?, ?, ?)
    """), (
        descricao,
        categoria,
        unidade,
        ativo,
        observacoes
    ))

    conn.commit()
    conn.close()


def buscar_insumos_almoxarifado(filtro_categoria="Todas", filtro_status="Todos", termo=""):
    criar_tabelas_almoxarifado()

    condicoes = ["1 = 1"]
    parametros = []

    if filtro_categoria and filtro_categoria != "Todas":
        condicoes.append("categoria = ?")
        parametros.append(filtro_categoria)

    if filtro_status and filtro_status != "Todos":
        condicoes.append("ativo = ?")
        parametros.append(filtro_status)

    if termo:
        condicoes.append("LOWER(descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT *
    FROM almoxarifado_insumos
    WHERE {where_sql}
    ORDER BY ativo DESC, categoria ASC, descricao ASC
    """), tuple(parametros))

    insumos = cursor.fetchall()
    conn.close()
    return insumos


def buscar_insumo_almoxarifado_por_id(insumo_id):
    criar_tabelas_almoxarifado()
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM almoxarifado_insumos
    WHERE id = ?
    """), (insumo_id,))

    insumo = cursor.fetchone()
    conn.close()
    return insumo


def atualizar_insumo_almoxarifado(insumo_id, form):
    criar_tabelas_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    UPDATE almoxarifado_insumos
    SET descricao = ?,
        categoria = ?,
        unidade = ?,
        ativo = ?,
        observacoes = ?
    WHERE id = ?
    """), (
        form.get("descricao", "").strip(),
        form.get("categoria", "").strip(),
        form.get("unidade", "").strip(),
        form.get("ativo", "Sim").strip(),
        form.get("observacoes", "").strip(),
        insumo_id
    ))

    conn.commit()
    conn.close()



def criar_tabelas_estoque_almoxarifado():
    criar_tabelas_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_lotes (
            id SERIAL PRIMARY KEY,
            insumo_id INTEGER NOT NULL,
            data_entrada TEXT NOT NULL,
            lote TEXT,
            fornecedor TEXT,
            numero_nf TEXT,
            quantidade_inicial REAL NOT NULL,
            quantidade_atual REAL NOT NULL,
            valor_unitario REAL NOT NULL,
            valor_total REAL NOT NULL,
            status TEXT DEFAULT 'Aberto',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_movimentacoes (
            id SERIAL PRIMARY KEY,
            data_movimentacao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            insumo_id INTEGER NOT NULL,
            lote_id INTEGER,
            quantidade REAL NOT NULL,
            valor_unitario REAL DEFAULT 0,
            valor_total REAL DEFAULT 0,
            fornecedor TEXT,
            numero_nf TEXT,
            lote TEXT,
            origem TEXT DEFAULT 'Manual',
            op_id INTEGER,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_lotes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            insumo_id INTEGER NOT NULL,
            data_entrada TEXT NOT NULL,
            lote TEXT,
            fornecedor TEXT,
            numero_nf TEXT,
            quantidade_inicial REAL NOT NULL,
            quantidade_atual REAL NOT NULL,
            valor_unitario REAL NOT NULL,
            valor_total REAL NOT NULL,
            status TEXT DEFAULT 'Aberto',
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS almoxarifado_movimentacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_movimentacao TEXT NOT NULL,
            tipo TEXT NOT NULL,
            insumo_id INTEGER NOT NULL,
            lote_id INTEGER,
            quantidade REAL NOT NULL,
            valor_unitario REAL DEFAULT 0,
            valor_total REAL DEFAULT 0,
            fornecedor TEXT,
            numero_nf TEXT,
            lote TEXT,
            origem TEXT DEFAULT 'Manual',
            op_id INTEGER,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()


def salvar_entrada_estoque_almoxarifado(form):
    criar_tabelas_estoque_almoxarifado()

    insumo_id = int(form.get("insumo_id") or 0)
    data_entrada = form.get("data_entrada", "").strip()
    quantidade = float(form.get("quantidade") or 0)
    valor_unitario = float(form.get("valor_unitario") or 0)
    fornecedor = form.get("fornecedor", "").strip()
    numero_nf = form.get("numero_nf", "").strip()
    lote = form.get("lote", "").strip()
    observacoes = form.get("observacoes", "").strip()

    if not buscar_insumo_almoxarifado_por_id(insumo_id):
        raise ValueError("Selecione um insumo válido.")

    if not data_entrada:
        raise ValueError("Informe a data de entrada.")

    if quantidade <= 0:
        raise ValueError("A quantidade precisa ser maior que zero.")

    if valor_unitario < 0:
        raise ValueError("O valor unitário não pode ser negativo.")

    valor_total = round(quantidade * valor_unitario, 4)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO almoxarifado_lotes (
        insumo_id,
        data_entrada,
        lote,
        fornecedor,
        numero_nf,
        quantidade_inicial,
        quantidade_atual,
        valor_unitario,
        valor_total,
        status
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        insumo_id,
        data_entrada,
        lote,
        fornecedor,
        numero_nf,
        quantidade,
        quantidade,
        valor_unitario,
        valor_total,
        "Aberto"
    ))

    lote_id = None
    try:
        if DATABASE_URL:
            cursor.execute("SELECT LASTVAL() as id")
            lote_id = cursor.fetchone()["id"]
        else:
            lote_id = cursor.lastrowid
    except Exception:
        lote_id = None

    cursor.execute(q("""
    INSERT INTO almoxarifado_movimentacoes (
        data_movimentacao,
        tipo,
        insumo_id,
        lote_id,
        quantidade,
        valor_unitario,
        valor_total,
        fornecedor,
        numero_nf,
        lote,
        origem,
        observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        data_entrada,
        "ENTRADA",
        insumo_id,
        lote_id,
        quantidade,
        valor_unitario,
        valor_total,
        fornecedor,
        numero_nf,
        lote,
        "Entrada manual",
        observacoes
    ))

    conn.commit()
    conn.close()


def buscar_saldos_almoxarifado():
    criar_tabelas_estoque_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        i.id,
        i.descricao,
        i.categoria,
        i.unidade,
        i.ativo,
        COALESCE(SUM(l.quantidade_atual), 0) as saldo_atual,
        COALESCE(SUM(l.quantidade_atual * l.valor_unitario), 0) as valor_estoque
    FROM almoxarifado_insumos i
    LEFT JOIN almoxarifado_lotes l ON l.insumo_id = i.id
    GROUP BY i.id, i.descricao, i.categoria, i.unidade, i.ativo
    ORDER BY i.categoria ASC, i.descricao ASC
    """)

    saldos = cursor.fetchall()
    conn.close()
    return saldos


def buscar_lotes_almoxarifado(limite=50):
    criar_tabelas_estoque_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        l.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_lotes l
    JOIN almoxarifado_insumos i ON i.id = l.insumo_id
    ORDER BY l.data_entrada ASC, l.id ASC
    LIMIT ?
    """), (limite,))

    lotes = cursor.fetchall()
    conn.close()
    return lotes


def buscar_movimentacoes_almoxarifado(limite=80):
    criar_tabelas_estoque_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        m.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_movimentacoes m
    JOIN almoxarifado_insumos i ON i.id = m.insumo_id
    ORDER BY m.data_movimentacao DESC, m.id DESC
    LIMIT ?
    """), (limite,))

    movimentacoes = cursor.fetchall()
    conn.close()
    return movimentacoes


def calcular_resumo_estoque_almoxarifado(saldos):
    total_itens_com_saldo = sum(1 for item in saldos if float(item["saldo_atual"] or 0) > 0)
    valor_total = sum(float(item["valor_estoque"] or 0) for item in saldos)
    itens_zerados = sum(1 for item in saldos if float(item["saldo_atual"] or 0) <= 0)

    return {
        "itens_com_saldo": total_itens_com_saldo,
        "itens_zerados": itens_zerados,
        "valor_total": round(valor_total, 2),
        "total_itens": len(saldos)
    }



def buscar_saldos_almoxarifado_filtrado(filtro_categoria="Todas", termo=""):
    criar_tabelas_estoque_almoxarifado()

    condicoes = ["1 = 1"]
    parametros = []

    if filtro_categoria and filtro_categoria != "Todas":
        condicoes.append("i.categoria = ?")
        parametros.append(filtro_categoria)

    if termo:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        i.id,
        i.descricao,
        i.categoria,
        i.unidade,
        i.ativo,
        COALESCE(SUM(l.quantidade_atual), 0) as saldo_atual,
        COALESCE(SUM(l.quantidade_atual * l.valor_unitario), 0) as valor_estoque
    FROM almoxarifado_insumos i
    LEFT JOIN almoxarifado_lotes l ON l.insumo_id = i.id
    WHERE {where_sql}
    GROUP BY i.id, i.descricao, i.categoria, i.unidade, i.ativo
    ORDER BY i.categoria ASC, i.descricao ASC
    """), tuple(parametros))

    saldos = cursor.fetchall()
    conn.close()
    return saldos


def buscar_movimentacoes_almoxarifado_filtrado(data_inicio, data_fim, tipo_filtro="Todos", termo="", limite=300):
    criar_tabelas_estoque_almoxarifado()

    condicoes = ["m.data_movimentacao BETWEEN ? AND ?"]
    parametros = [data_inicio, data_fim]

    if tipo_filtro and tipo_filtro != "Todos":
        condicoes.append("m.tipo = ?")
        parametros.append(tipo_filtro)

    if termo:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        m.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_movimentacoes m
    JOIN almoxarifado_insumos i ON i.id = m.insumo_id
    WHERE {where_sql}
    ORDER BY m.data_movimentacao DESC, m.id DESC
    LIMIT ?
    """), tuple(parametros + [limite]))

    movimentacoes = cursor.fetchall()
    conn.close()
    return movimentacoes


def buscar_lotes_almoxarifado_filtrado(insumo_id="", status_filtro="Todos", termo="", limite=300):
    criar_tabelas_estoque_almoxarifado()

    condicoes = ["1 = 1"]
    parametros = []

    if insumo_id:
        condicoes.append("l.insumo_id = ?")
        parametros.append(int(insumo_id))

    if status_filtro and status_filtro != "Todos":
        condicoes.append("l.status = ?")
        parametros.append(status_filtro)

    if termo:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{termo.lower()}%")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        l.*,
        i.descricao as insumo,
        i.unidade as unidade,
        i.categoria as categoria
    FROM almoxarifado_lotes l
    JOIN almoxarifado_insumos i ON i.id = l.insumo_id
    WHERE {where_sql}
    ORDER BY l.data_entrada ASC, l.id ASC
    LIMIT ?
    """), tuple(parametros + [limite]))

    lotes = cursor.fetchall()
    conn.close()
    return lotes


def calcular_resumo_rastreabilidade(lotes):
    lotes_abertos = sum(1 for item in lotes if item["status"] == "Aberto")
    lotes_fechados = sum(1 for item in lotes if item["status"] == "Fechado")
    quantidade_total = sum(float(item["quantidade_atual"] or 0) for item in lotes)
    valor_total = sum(float(item["quantidade_atual"] or 0) * float(item["valor_unitario"] or 0) for item in lotes)

    return {
        "total_lotes": len(lotes),
        "lotes_abertos": lotes_abertos,
        "lotes_fechados": lotes_fechados,
        "quantidade_total": round(quantidade_total, 4),
        "valor_total": round(valor_total, 2)
    }


def calcular_resumo_almoxarifado(insumos):
    total_itens = len(insumos)
    itens_ativos = sum(1 for item in insumos if item["ativo"] == "Sim")
    itens_inativos = total_itens - itens_ativos
    categorias_usadas = len(set(item["categoria"] for item in insumos))

    return {
        "total_itens": total_itens,
        "itens_ativos": itens_ativos,
        "itens_inativos": itens_inativos,
        "categorias_usadas": categorias_usadas
    }
