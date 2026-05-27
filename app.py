from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
from urllib.parse import urlparse
import os
import uuid
import sqlite3
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "segredo")

DATABASE_URL = os.getenv("DATABASE_URL")
DB_NAME = "abatedouro.db"


def q(sql):
    if DATABASE_URL:
        return sql.replace("?", "%s")
    return sql


def conectar():
    if DATABASE_URL:
        result = urlparse(DATABASE_URL)
        return psycopg2.connect(
            database=result.path[1:],
            user=result.username,
            password=result.password,
            host=result.hostname,
            port=result.port,
            cursor_factory=psycopg2.extras.RealDictCursor
        )

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def tentar_alter_table(cursor, conn, comando):
    try:
        cursor.execute(comando)
        conn.commit()
    except Exception:
        conn.rollback()


def criar_banco():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            perfil TEXT DEFAULT 'admin'
        )
        """)


        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fornecedores (
            id SERIAL PRIMARY KEY,
            nome TEXT UNIQUE NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ordens_producao (
            id SERIAL PRIMARY KEY,
            data TEXT NOT NULL,
            fornecedor TEXT NOT NULL,
            gta TEXT,
            nota_fiscal TEXT,
            quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0,
            peso_vivo REAL NOT NULL,
            peso_medio REAL NOT NULL,
            observacoes TEXT,
            status TEXT DEFAULT 'Aberta',
            sku TEXT DEFAULT 'Galinha Cortada'
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_setor (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            colaboradores INTEGER NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            horas_programadas REAL NOT NULL,
            horas_paradas REAL DEFAULT 0,
            motivo_parada TEXT,
            quantidade_produzida REAL NOT NULL,
            unidade TEXT NOT NULL,
            condenacoes REAL DEFAULT 0,
            perdas REAL DEFAULT 0,
            produtividade REAL NOT NULL,
            observacoes TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_producao (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            quantidade REAL NOT NULL,
            unidade TEXT NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_mao_obra (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            colaborador TEXT NOT NULL,
            funcao TEXT NOT NULL,
            setor TEXT NOT NULL,
            turno TEXT,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_paradas (
            id SERIAL PRIMARY KEY,
            evento_id TEXT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            motivo TEXT NOT NULL,
            hora_inicio TEXT,
            hora_fim TEXT,
            horas_paradas REAL NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_descartes (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            categoria TEXT NOT NULL,
            motivo TEXT NOT NULL,
            quantidade REAL NOT NULL,
            unidade TEXT NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        tentar_alter_table(cursor, conn, "ALTER TABLE usuarios ADD COLUMN perfil TEXT DEFAULT 'admin'")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE ordens_producao ADD COLUMN status TEXT DEFAULT 'Aberta'")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE ordens_producao ADD COLUMN sku TEXT DEFAULT 'Galinha Cortada'")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE apontamentos_paradas ADD COLUMN evento_id TEXT")
        conn = conectar()
        cursor = conn.cursor()

    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            perfil TEXT DEFAULT 'admin'
        )
        """)


        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fornecedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ordens_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            fornecedor TEXT NOT NULL,
            gta TEXT,
            nota_fiscal TEXT,
            quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0,
            peso_vivo REAL NOT NULL,
            peso_medio REAL NOT NULL,
            observacoes TEXT,
            status TEXT DEFAULT 'Aberta',
            sku TEXT DEFAULT 'Galinha Cortada'
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_setor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            colaboradores INTEGER NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            horas_programadas REAL NOT NULL,
            horas_paradas REAL DEFAULT 0,
            motivo_parada TEXT,
            quantidade_produzida REAL NOT NULL,
            unidade TEXT NOT NULL,
            condenacoes REAL DEFAULT 0,
            perdas REAL DEFAULT 0,
            produtividade REAL NOT NULL,
            observacoes TEXT
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_producao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            quantidade REAL NOT NULL,
            unidade TEXT NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_mao_obra (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            colaborador TEXT NOT NULL,
            funcao TEXT NOT NULL,
            setor TEXT NOT NULL,
            turno TEXT,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_paradas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id TEXT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            motivo TEXT NOT NULL,
            hora_inicio TEXT,
            hora_fim TEXT,
            horas_paradas REAL NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_descartes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            categoria TEXT NOT NULL,
            motivo TEXT NOT NULL,
            quantidade REAL NOT NULL,
            unidade TEXT NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        try:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN perfil TEXT DEFAULT 'admin'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ordens_producao ADD COLUMN status TEXT DEFAULT 'Aberta'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ordens_producao ADD COLUMN sku TEXT DEFAULT 'Galinha Cortada'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE apontamentos_paradas ADD COLUMN evento_id TEXT")
        except sqlite3.OperationalError:
            pass

    cursor.execute("SELECT COUNT(*) as total FROM usuarios")
    total = cursor.fetchone()["total"]

    if total == 0:
        cursor.execute(q("""
        INSERT INTO usuarios (nome, email, senha_hash, perfil)
        VALUES (?, ?, ?, ?)
        """), (
            "Administrador",
            "admin@app.com",
            generate_password_hash("admin123"),
            "admin"
        ))
    else:
        cursor.execute(q("""
        UPDATE usuarios
        SET perfil = 'admin'
        WHERE perfil IS NULL OR perfil = ''
        """))

    conn.commit()
    conn.close()


def login_obrigatorio(funcao):
    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return funcao(*args, **kwargs)
    return wrapper


def destino_por_perfil(perfil):
    if perfil == "admin" or perfil == "pcp":
        return "dashboard"

    if perfil == "qualidade":
        return "apontamento_descartes"

    if perfil == "producao":
        return "apontamento_producao"

    return "login"


def perfil_permitido(*perfis_autorizados):
    def decorador(funcao):
        @wraps(funcao)
        def wrapper(*args, **kwargs):
            if "usuario_id" not in session:
                return redirect(url_for("login"))

            perfil = session.get("perfil", "")

            if perfil == "admin" or perfil in perfis_autorizados:
                return funcao(*args, **kwargs)

            flash("Acesso não autorizado para este usuário.")
            return redirect(url_for(destino_por_perfil(perfil)))

        return wrapper

    return decorador


def calcular_horas_programadas(hora_inicio, hora_fim):
    inicio = datetime.strptime(hora_inicio, "%H:%M")
    fim = datetime.strptime(hora_fim, "%H:%M")
    diferenca = fim - inicio
    horas = diferenca.total_seconds() / 3600

    if horas < 0:
        horas += 24

    return round(horas, 2)


def calcular_produtividade(quantidade, colaboradores, horas_programadas, horas_paradas):
    horas_uteis = horas_programadas - horas_paradas

    if horas_uteis <= 0:
        return 0

    homem_hora = colaboradores * horas_uteis

    if homem_hora <= 0:
        return 0

    produtividade = quantidade / homem_hora
    return round(produtividade, 2)


def setores_padrao():
    return [
        "Recepção e Pendura",
        "Escalda e Depenagem",
        "Evisceração",
        "Corte",
        "Embalagem",
        "Expedição"
    ]



def buscar_fornecedores():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM fornecedores
    ORDER BY nome
    """)

    fornecedores = cursor.fetchall()
    conn.close()

    return fornecedores


def buscar_ordens():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT *
    FROM ordens_producao
    ORDER BY id DESC
    """)
    ordens = cursor.fetchall()
    conn.close()
    return ordens


def buscar_ordens_abertas():
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT *
    FROM ordens_producao
    WHERE status IS NULL OR status <> 'Encerrada'
    ORDER BY id DESC
    """)
    ordens = cursor.fetchall()
    conn.close()
    return ordens


def op_esta_encerrada(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT status
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()
    conn.close()

    if not op:
        return False

    return op["status"] == "Encerrada"


def validar_op_aberta(op_id):
    if op_esta_encerrada(op_id) and session.get("perfil") != "admin":
        raise ValueError("Esta OP já está encerrada. Novos lançamentos não são permitidos.")


def calcular_resumo_op(op, producoes, descartes):
    total_descartes_aves = sum(
        item["quantidade"] for item in descartes
        if item["unidade"].lower() in ["aves", "ave", "unidade", "unidades"]
    )

    total_descartes_kg = sum(
        item["quantidade"] for item in descartes
        if item["unidade"].lower() == "kg"
    )

    kg_produzidos = sum(
        item["quantidade"] for item in producoes
        if item["unidade"].lower() == "kg"
    )

    aves_abatidas = op["quantidade_aves"] - op["mortes_antes_pendura"]
    descartes_aves = op["mortes_antes_pendura"] + total_descartes_aves
    viabilidade = op["quantidade_aves"] - descartes_aves

    viabilidade_percentual = 0
    if op["quantidade_aves"] > 0:
        viabilidade_percentual = (viabilidade / op["quantidade_aves"]) * 100

    rendimento = 0
    if op["peso_vivo"] > 0:
        rendimento = (kg_produzidos / op["peso_vivo"]) * 100

    return {
        "aves_abatidas": aves_abatidas,
        "descartes_aves": total_descartes_aves,
        "descartes_kg": total_descartes_kg,
        "kg_produzidos": kg_produzidos,
        "viabilidade": viabilidade,
        "viabilidade_percentual": round(viabilidade_percentual, 2),
        "rendimento": round(rendimento, 2)
    }


def salvar_apontamento_producao(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_producao (
        op_id, data, setor, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?)
    """), (
        op_id,
        form["data"],
        form["setor"],
        float(form["quantidade"]),
        form["unidade"],
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def salvar_apontamento_mao_obra(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_mao_obra (
        op_id, data, colaborador, funcao, setor, turno, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        op_id,
        form["data"],
        form["colaborador"],
        form["funcao"],
        form["setor"],
        form.get("turno", ""),
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def salvar_apontamento_parada(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    setores_impactados = form.getlist("setores")

    if not setores_impactados and form.get("setor"):
        setores_impactados = [form.get("setor")]

    if not setores_impactados:
        raise ValueError("Selecione pelo menos um setor impactado pela parada.")

    conn = conectar()
    cursor = conn.cursor()

    evento_id = uuid.uuid4().hex

    horas_paradas = float(form.get("horas_paradas") or 0)

    if horas_paradas <= 0 and form.get("hora_inicio") and form.get("hora_fim"):
        horas_paradas = calcular_horas_programadas(
            form["hora_inicio"],
            form["hora_fim"]
        )

    for setor in setores_impactados:
        cursor.execute(q("""
        INSERT INTO apontamentos_paradas (
            evento_id, op_id, data, setor, motivo, hora_inicio, hora_fim, horas_paradas, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            evento_id,
            op_id,
            form["data"],
            setor,
            form["motivo"],
            form.get("hora_inicio", ""),
            form.get("hora_fim", ""),
            horas_paradas,
            form.get("observacoes", "")
        ))

    conn.commit()
    conn.close()

def salvar_apontamento_descarte(form):
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_descartes (
        op_id, data, setor, categoria, motivo, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        op_id,
        form["data"],
        form["setor"],
        form["categoria"],
        form["motivo"],
        float(form["quantidade"]),
        form["unidade"],
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def contexto_apontamento():
    return {
        "hoje": datetime.now().strftime("%Y-%m-%d"),
        "ordens": buscar_ordens_abertas(),
        "setores": setores_padrao()
    }


@app.route("/", methods=["GET", "POST"])
def login():
    criar_banco()

    if request.method == "POST":
        email = request.form["email"]
        senha = request.form["senha"]

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        SELECT *
        FROM usuarios
        WHERE email = ?
        """), (email,))

        usuario = cursor.fetchone()
        conn.close()

        if usuario and check_password_hash(usuario["senha_hash"], senha):
            session["usuario_id"] = usuario["id"]
            session["nome"] = usuario["nome"]

            if usuario["perfil"]:
                session["perfil"] = usuario["perfil"]
            else:
                session["perfil"] = "admin"

            return redirect(url_for(destino_por_perfil(session["perfil"])))

        flash("Usuário ou senha inválidos")

    return render_template("login.html")


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@perfil_permitido("pcp")
def dashboard():
    agora = datetime.now()
    hoje = agora.strftime("%Y-%m-%d")
    primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

    data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
    data_fim = request.args.get("data_fim") or hoje
    status_filtro = request.args.get("status") or "Encerrada"

    jornada_padrao = 8.8
    setores_produtivos = [
        "Recepção e Pendura",
        "Escalda e Depenagem",
        "Evisceração",
        "Corte",
        "Embalagem"
    ]

    status_condicao_op = ""
    status_condicao_alias = ""
    parametros_status = ()

    if status_filtro in ["Aberta", "Encerrada"]:
        status_condicao_op = " AND COALESCE(status, 'Aberta') = ?"
        status_condicao_alias = " AND COALESCE(o.status, 'Aberta') = ?"
        parametros_status = (status_filtro,)
    else:
        status_filtro = "Todas"

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        id,
        data,
        quantidade_aves,
        mortes_antes_pendura,
        peso_vivo
    FROM ordens_producao
    WHERE data BETWEEN ? AND ?
    {status_condicao_op}
    """), (data_inicio, data_fim) + parametros_status)

    ordens_periodo = cursor.fetchall()

    datas_periodo = sorted({op["data"] for op in ordens_periodo})
    dias_periodo = len(datas_periodo)
    horas_programadas = jornada_padrao * dias_periodo

    aves_recebidas = sum(op["quantidade_aves"] or 0 for op in ordens_periodo)
    mortes_antes_pendura = sum(op["mortes_antes_pendura"] or 0 for op in ordens_periodo)
    peso_entrada = sum(op["peso_vivo"] or 0 for op in ordens_periodo)
    aves_abatidas = aves_recebidas - mortes_antes_pendura

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(d.quantidade), 0) as descartes_aves
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      {status_condicao_alias}
    """), (data_inicio, data_fim) + parametros_status)

    descartes_aves = cursor.fetchone()["descartes_aves"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(d.quantidade), 0) as descartes_kg
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) = 'kg'
      {status_condicao_alias}
    """), (data_inicio, data_fim) + parametros_status)

    descartes_kg = cursor.fetchone()["descartes_kg"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(p.quantidade), 0) as kg
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(p.unidade) = 'kg'
      {status_condicao_alias}
    """), (data_inicio, data_fim) + parametros_status)

    kg_produzidos = cursor.fetchone()["kg"] or 0

    total_problemas_aves = mortes_antes_pendura + descartes_aves

    cursor.execute(q(f"""
    SELECT d.setor, COALESCE(SUM(d.quantidade), 0) as quantidade
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      {status_condicao_alias}
    GROUP BY d.setor
    ORDER BY quantidade DESC
    """), (data_inicio, data_fim) + parametros_status)

    descartes_por_setor_raw = cursor.fetchall()

    descartes_por_setor = []
    descartes_aves_por_setor = {}

    if mortes_antes_pendura > 0:
        percentual_transporte = 0

        if total_problemas_aves > 0:
            percentual_transporte = (mortes_antes_pendura / total_problemas_aves) * 100

        descartes_por_setor.append({
            "setor": "Transporte",
            "quantidade": round(mortes_antes_pendura, 2),
            "percentual": round(percentual_transporte, 2)
        })

    for item in descartes_por_setor_raw:
        quantidade = item["quantidade"] or 0
        descartes_aves_por_setor[item["setor"]] = quantidade
        percentual = 0

        if total_problemas_aves > 0:
            percentual = (quantidade / total_problemas_aves) * 100

        descartes_por_setor.append({
            "setor": item["setor"],
            "quantidade": round(quantidade, 2),
            "percentual": round(percentual, 2)
        })

    descartes_por_setor = sorted(
        descartes_por_setor,
        key=lambda item: item["quantidade"],
        reverse=True
    )

    cursor.execute(q(f"""
    SELECT
        p.id,
        p.evento_id,
        p.op_id,
        o.data as data_op,
        p.data as data_apontamento,
        p.setor,
        p.motivo,
        p.horas_paradas,
        p.observacoes
    FROM apontamentos_paradas p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND p.setor <> 'Expedição'
      {status_condicao_alias}
    """), (data_inicio, data_fim) + parametros_status)

    paradas_produtivas = cursor.fetchall()

    horas_perdidas_por_setor = {setor: 0 for setor in setores_produtivos}
    horas_perdidas_por_data_setor = {}
    eventos_parada_unicos = {}

    for parada in paradas_produtivas:
        setor = parada["setor"]

        if setor not in setores_produtivos:
            continue

        horas = float(parada["horas_paradas"] or 0)
        data_base = parada["data_op"] or parada["data_apontamento"]

        horas_perdidas_por_setor[setor] += horas
        chave_data_setor = (data_base, setor)
        horas_perdidas_por_data_setor[chave_data_setor] = (
            horas_perdidas_por_data_setor.get(chave_data_setor, 0) + horas
        )

        if parada["evento_id"]:
            chave_evento = parada["evento_id"]
        else:
            chave_evento = (
                parada["op_id"],
                data_base,
                parada["motivo"],
                round(horas, 4),
                parada["observacoes"] or ""
            )

        eventos_parada_unicos[chave_evento] = horas

    horas_perdidas_total = sum(eventos_parada_unicos.values())
    horas_uteis_total = max(0, horas_programadas - horas_perdidas_total)

    percentual_jornada_perdida = 0
    if horas_programadas > 0:
        percentual_jornada_perdida = (horas_perdidas_total / horas_programadas) * 100

    cursor.execute(q(f"""
    SELECT
        o.data as data_op,
        m.setor,
        m.colaborador
    FROM apontamentos_mao_obra m
    JOIN ordens_producao o ON o.id = m.op_id
    WHERE o.data BETWEEN ? AND ?
      AND m.setor <> 'Expedição'
      {status_condicao_alias}
    """), (data_inicio, data_fim) + parametros_status)

    mao_obra_periodo = cursor.fetchall()

    colaboradores_por_data_setor = {}

    for item in mao_obra_periodo:
        setor = item["setor"]

        if setor not in setores_produtivos:
            continue

        chave = (item["data_op"], setor)
        nome = (item["colaborador"] or "").strip().lower()

        if not nome:
            continue

        colaboradores_por_data_setor.setdefault(chave, set()).add(nome)

    hh_total = 0
    hh_por_setor = {setor: 0 for setor in setores_produtivos}
    colaboradores_por_setor = {setor: set() for setor in setores_produtivos}

    for (data_op, setor), colaboradores in colaboradores_por_data_setor.items():
        horas_perdidas_setor_dia = horas_perdidas_por_data_setor.get((data_op, setor), 0)
        horas_uteis_setor_dia = max(0, jornada_padrao - horas_perdidas_setor_dia)
        hh = len(colaboradores) * horas_uteis_setor_dia

        hh_por_setor[setor] += hh
        hh_total += hh
        colaboradores_por_setor[setor].update(colaboradores)

    viabilidade = aves_recebidas - mortes_antes_pendura - descartes_aves
    viabilidade_percentual = 0

    if aves_recebidas > 0:
        viabilidade_percentual = (viabilidade / aves_recebidas) * 100

    rendimento = 0
    if peso_entrada > 0:
        rendimento = (kg_produzidos / peso_entrada) * 100

    produtividade_hh = 0
    if hh_total > 0:
        produtividade_hh = viabilidade / hh_total

    aves_hora_fabrica = 0
    if horas_uteis_total > 0:
        aves_hora_fabrica = viabilidade / horas_uteis_total

    cursor.execute(q(f"""
    SELECT p.setor, SUM(p.quantidade) as total_produzido
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      {status_condicao_alias}
    GROUP BY p.setor
    ORDER BY p.setor
    """), (data_inicio, data_fim) + parametros_status)

    produtividade_setores = cursor.fetchall()

    produtividade_setores_hora = []
    entrada_setor = aves_abatidas

    for setor in setores_produtivos:
        descartes_setor = descartes_aves_por_setor.get(setor, 0)
        saida_liquida = max(0, entrada_setor - descartes_setor)
        horas_perdidas_setor = horas_perdidas_por_setor.get(setor, 0)
        horas_uteis_setor = max(0, horas_programadas - horas_perdidas_setor)
        hh_setor = hh_por_setor.get(setor, 0)
        aves_hora_setor = 0
        produtividade_hh_setor = 0

        if horas_uteis_setor > 0:
            aves_hora_setor = saida_liquida / horas_uteis_setor

        if hh_setor > 0:
            produtividade_hh_setor = saida_liquida / hh_setor

        produtividade_setores_hora.append({
            "setor": setor,
            "entrada": round(entrada_setor, 2),
            "descartes": round(descartes_setor, 2),
            "saida_liquida": round(saida_liquida, 2),
            "horas_perdidas": round(horas_perdidas_setor, 2),
            "horas_uteis": round(horas_uteis_setor, 2),
            "colaboradores": len(colaboradores_por_setor.get(setor, set())),
            "hh": round(hh_setor, 2),
            "aves_hora": round(aves_hora_setor, 2),
            "produtividade_hh": round(produtividade_hh_setor, 2)
        })

        entrada_setor = saida_liquida

    conn.close()

    return render_template(
        "dashboard.html",
        data_inicio=data_inicio,
        data_fim=data_fim,
        status_filtro=status_filtro,
        aves_recebidas=round(aves_recebidas, 2),
        aves_abatidas=round(aves_abatidas, 2),
        viabilidade=round(viabilidade, 2),
        viabilidade_percentual=round(viabilidade_percentual, 2),
        peso_entrada=round(peso_entrada, 2),
        kg_produzidos=round(kg_produzidos, 2),
        rendimento=round(rendimento, 2),
        mortes_antes_pendura=round(mortes_antes_pendura, 2),
        total_condenacoes=round(descartes_aves, 2),
        total_perdas=round(descartes_kg, 2),
        total_problemas_aves=round(total_problemas_aves, 2),
        jornada_padrao=round(jornada_padrao, 2),
        dias_periodo=dias_periodo,
        horas_programadas=round(horas_programadas, 2),
        horas_perdidas_total=round(horas_perdidas_total, 2),
        percentual_jornada_perdida=round(percentual_jornada_perdida, 2),
        horas_uteis_total=round(horas_uteis_total, 2),
        hh_total=round(hh_total, 2),
        produtividade_hh=round(produtividade_hh, 2),
        aves_hora_fabrica=round(aves_hora_fabrica, 2),
        descartes_por_setor=descartes_por_setor,
        produtividade_setores=produtividade_setores,
        produtividade_setores_hora=produtividade_setores_hora
    )

def criar_tabela_fornecedores():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fornecedores (
            id SERIAL PRIMARY KEY,
            nome TEXT UNIQUE NOT NULL
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS fornecedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT UNIQUE NOT NULL
        )
        """)

    conn.commit()
    conn.close()

@app.route("/fornecedores", methods=["GET", "POST"])
@perfil_permitido("pcp")
def fornecedores():
    criar_banco()

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        nome = request.form["nome"].strip()

        if nome:
            try:
                cursor.execute(q("""
                INSERT INTO fornecedores (nome)
                VALUES (?)
                """), (nome,))

                conn.commit()
                flash("Fornecedor cadastrado com sucesso.")
            except Exception:
                conn.rollback()
                flash("Este fornecedor já está cadastrado.")

        return redirect(url_for("fornecedores"))

    cursor.execute("""
    SELECT *
    FROM fornecedores
    ORDER BY nome
    """)

    fornecedores = cursor.fetchall()
    conn.close()

    return render_template(
        "fornecedores.html",
        fornecedores=fornecedores
    )


@app.route("/ordem-producao", methods=["GET", "POST"])
@perfil_permitido("pcp")
def ordem_producao():
    criar_banco()

    if request.method == "POST":
        data = request.form["data"]
        sku = request.form.get("sku", "Galinha Cortada")
        fornecedor = request.form["fornecedor"]
        gta = request.form["gta"]
        nota_fiscal = request.form["nota_fiscal"]
        quantidade_aves = int(request.form["quantidade_aves"])
        mortes_antes_pendura = int(request.form["mortes_antes_pendura"])
        peso_vivo = float(request.form["peso_vivo"])
        observacoes = request.form["observacoes"]

        peso_medio = peso_vivo / quantidade_aves if quantidade_aves else 0

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        INSERT INTO ordens_producao (
            data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
            mortes_antes_pendura, peso_vivo, peso_medio, observacoes, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
            mortes_antes_pendura, peso_vivo, peso_medio, observacoes, "Aberta"
        ))

        conn.commit()
        conn.close()

        flash("OP cadastrada com sucesso")
        return redirect(url_for("ordem_producao"))

    hoje = datetime.now().strftime("%Y-%m-%d")
    ordens = buscar_ordens()[:10]
    fornecedores = buscar_fornecedores()

    return render_template(
        "ordem_producao.html",
        hoje=hoje,
        ordens=ordens,
        fornecedores=fornecedores
    )


@app.route("/apontamento-setor", methods=["GET", "POST"])
@perfil_permitido("admin")
def apontamento_setor():
    criar_banco()

    if request.method == "POST":
        tipo = request.form.get("tipo_apontamento")

        if tipo == "producao":
            salvar_apontamento_producao(request.form)
            flash("Apontamento de produção salvo.")

        elif tipo == "mao_obra":
            salvar_apontamento_mao_obra(request.form)
            flash("Apontamento de mão de obra salvo.")

        elif tipo == "parada":
            salvar_apontamento_parada(request.form)
            flash("Apontamento de parada salvo.")

        elif tipo == "descarte":
            salvar_apontamento_descarte(request.form)
            flash("Apontamento de descarte/condenação salvo.")

        return redirect(url_for("apontamento_setor"))

    return render_template("apontamento_setor.html", **contexto_apontamento())


@app.route("/apontamento-producao", methods=["GET", "POST"])
@perfil_permitido("producao")
def apontamento_producao():
    criar_banco()

    if request.method == "POST":
        try:
            salvar_apontamento_producao(request.form)
            flash("Apontamento de produção salvo.")
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("apontamento_producao"))

    return render_template("apontamento_producao.html", **contexto_apontamento())


@app.route("/apontamento-mao-obra", methods=["GET", "POST"])
@perfil_permitido("producao")
def apontamento_mao_obra():
    criar_banco()

    if request.method == "POST":
        try:
            salvar_apontamento_mao_obra(request.form)
            flash("Apontamento de mão de obra salvo.")
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("apontamento_mao_obra"))

    return render_template("apontamento_mao_obra.html", **contexto_apontamento())


@app.route("/apontamento-paradas", methods=["GET", "POST"])
@perfil_permitido("producao")
def apontamento_paradas():
    criar_banco()

    if request.method == "POST":
        try:
            salvar_apontamento_parada(request.form)
            flash("Apontamento de horas paradas salvo.")
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("apontamento_paradas"))

    return render_template("apontamento_paradas.html", **contexto_apontamento())


@app.route("/apontamento-descartes", methods=["GET", "POST"])
@perfil_permitido("qualidade")
def apontamento_descartes():
    criar_banco()

    if request.method == "POST":
        try:
            salvar_apontamento_descarte(request.form)
            flash("Apontamento de descarte/condenação salvo.")
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("apontamento_descartes"))

    return render_template("apontamento_descartes.html", **contexto_apontamento())


@app.route("/op/<int:op_id>/editar", methods=["GET", "POST"])
@perfil_permitido("pcp")
def editar_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
    op = cursor.fetchone()

    if not op:
        conn.close()
        flash("OP não encontrada.")
        return redirect(url_for("consultar_op"))

    if op["status"] == "Encerrada" and session.get("perfil") != "admin":
        conn.close()
        flash("Esta OP está encerrada. Edição bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    if request.method == "POST":
        data = request.form["data"]
        sku = request.form.get("sku", "Galinha Cortada")
        fornecedor = request.form["fornecedor"]
        gta = request.form["gta"]
        nota_fiscal = request.form["nota_fiscal"]
        quantidade_aves = int(request.form["quantidade_aves"])
        mortes_antes_pendura = int(request.form["mortes_antes_pendura"])
        peso_vivo = float(request.form["peso_vivo"])
        observacoes = request.form["observacoes"]
        peso_medio = peso_vivo / quantidade_aves if quantidade_aves else 0

        cursor.execute(q("""
        UPDATE ordens_producao
        SET data = ?, sku = ?, fornecedor = ?, gta = ?, nota_fiscal = ?,
            quantidade_aves = ?, mortes_antes_pendura = ?, peso_vivo = ?,
            peso_medio = ?, observacoes = ?
        WHERE id = ?
        """), (
            data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
            mortes_antes_pendura, peso_vivo, peso_medio, observacoes, op_id
        ))

        conn.commit()
        conn.close()

        flash("OP atualizada com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    fornecedores = buscar_fornecedores()

    conn.close()
    return render_template(
        "editar_op.html",
        op=op,
        fornecedores=fornecedores
    )


@app.route("/mao-obra/<int:mao_obra_id>/editar", methods=["GET", "POST"])
@perfil_permitido("producao")
def editar_mao_obra(mao_obra_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        m.*,
        o.status as op_status
    FROM apontamentos_mao_obra m
    JOIN ordens_producao o ON o.id = m.op_id
    WHERE m.id = ?
    """), (mao_obra_id,))

    apontamento = cursor.fetchone()

    if not apontamento:
        conn.close()
        flash("Apontamento de mão de obra não encontrado.")
        return redirect(url_for("consultar_op"))

    if apontamento["op_status"] == "Encerrada" and session.get("perfil") != "admin":
        op_id = apontamento["op_id"]
        conn.close()
        flash("Esta OP está encerrada. Edição de mão de obra bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    if request.method == "POST":
        colaborador = request.form["colaborador"]
        funcao = request.form["funcao"]
        setor = request.form["setor"]
        turno = request.form.get("turno", "")
        observacoes = request.form.get("observacoes", "")

        cursor.execute(q("""
        UPDATE apontamentos_mao_obra
        SET colaborador = ?,
            funcao = ?,
            setor = ?,
            turno = ?,
            observacoes = ?
        WHERE id = ?
        """), (
            colaborador,
            funcao,
            setor,
            turno,
            observacoes,
            mao_obra_id
        ))

        conn.commit()
        op_id = apontamento["op_id"]
        conn.close()

        flash("Apontamento de mão de obra atualizado com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    conn.close()

    lista_funcoes = [
        "Lavar gaiolas",
        "Pendura",
        "Sangria",
        "Depenadeira",
        "Transpasse",
        "Retirada do papo",
        "Retirada da cloaca",
        "Corte abdominal",
        "Eventração",
        "Retirada da moela",
        "Abertura da moela",
        "Retirada do coração",
        "Retirada do pulmão",
        "Retirada da cabeça/Revisão final",
        "Limpeza de miudos",
        "Corte",
        "Organização da bandeja",
        "Ensaque da bandeja",
        "Selagem",
        "Pesagem",
        "Embalagem secundária",
        "Rotulagem",
        "Outra"
    ]

    return render_template(
        "editar_mao_obra.html",
        apontamento=apontamento,
        setores=setores_padrao(),
        lista_funcoes=lista_funcoes
    )


@app.route("/parada/<int:parada_id>/editar", methods=["GET", "POST"])
@perfil_permitido("producao")
def editar_parada(parada_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        p.*,
        o.status as op_status
    FROM apontamentos_paradas p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE p.id = ?
    """), (parada_id,))

    apontamento = cursor.fetchone()

    if not apontamento:
        conn.close()
        flash("Apontamento de parada não encontrado.")
        return redirect(url_for("consultar_op"))

    if apontamento["op_status"] == "Encerrada" and session.get("perfil") != "admin":
        op_id = apontamento["op_id"]
        conn.close()
        flash("Esta OP está encerrada. Edição de parada bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    if request.method == "POST":
        data = request.form["data"]
        setor = request.form["setor"]
        motivo = request.form["motivo"]
        horas_paradas = float(request.form.get("horas_paradas") or 0)
        observacoes = request.form.get("observacoes", "")

        cursor.execute(q("""
        UPDATE apontamentos_paradas
        SET data = ?,
            setor = ?,
            motivo = ?,
            horas_paradas = ?,
            observacoes = ?
        WHERE id = ?
        """), (
            data,
            setor,
            motivo,
            horas_paradas,
            observacoes,
            parada_id
        ))

        conn.commit()
        op_id = apontamento["op_id"]
        conn.close()

        flash("Apontamento de parada atualizado com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    conn.close()

    lista_motivos_parada = [
        "Falta de matéria prima",
        "Falta de insumos",
        "Falta de mão de obra",
        "Quebra de equipamento",
        "Manutenção corretiva",
        "Manutenção preventiva",
        "Falta de energia",
        "Ajuste operacional",
        "Limpeza / higienização",
        "Outro"
    ]

    return render_template(
        "editar_parada.html",
        apontamento=apontamento,
        setores=setores_padrao(),
        lista_motivos_parada=lista_motivos_parada
    )


def obter_registros_por_ids(tabela, ids):
    if not ids:
        return []

    placeholders = ",".join(["?"] * len(ids))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        r.*,
        o.status as op_status
    FROM {tabela} r
    JOIN ordens_producao o ON o.id = r.op_id
    WHERE r.id IN ({placeholders})
    ORDER BY r.id ASC
    """), tuple(ids))

    registros = cursor.fetchall()
    conn.close()
    return registros


def ids_do_request(nome="ids"):
    valores = request.values.getlist(nome)

    if not valores:
        valores = request.form.getlist(nome)

    ids = []

    for valor in valores:
        try:
            ids.append(int(valor))
        except (TypeError, ValueError):
            pass

    return ids


def primeiro_op_id(registros):
    if not registros:
        return None
    return registros[0]["op_id"]


def edicao_bloqueada_por_status(registros):
    if session.get("perfil") == "admin":
        return False

    for registro in registros:
        if registro["op_status"] == "Encerrada":
            return True

    return False


@app.route("/mao-obra/lote/editar", methods=["GET", "POST"])
@perfil_permitido("producao")
def editar_mao_obra_lote():
    ids = ids_do_request("ids")

    if not ids:
        flash("Selecione pelo menos um lançamento de mão de obra.")
        return redirect(url_for("consultar_op"))

    registros = obter_registros_por_ids("apontamentos_mao_obra", ids)

    if not registros:
        flash("Nenhum lançamento de mão de obra encontrado.")
        return redirect(url_for("consultar_op"))

    op_id = primeiro_op_id(registros)

    if edicao_bloqueada_por_status(registros):
        flash("Esta OP está encerrada. Edição de mão de obra bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    if request.method == "POST" and request.form.get("acao") == "salvar":
        funcao = request.form["funcao"]
        setor = request.form["setor"]
        turno = request.form.get("turno", "")
        observacoes = request.form.get("observacoes", "")

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        UPDATE apontamentos_mao_obra
        SET funcao = ?,
            setor = ?,
            turno = ?,
            observacoes = ?
        WHERE id IN ({placeholders})
        """), (funcao, setor, turno, observacoes, *ids))

        conn.commit()
        conn.close()

        flash("Lançamentos de mão de obra atualizados com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    lista_funcoes = [
        "Lavar gaiolas",
        "Pendura",
        "Sangria",
        "Depenadeira",
        "Transpasse",
        "Retirada do papo",
        "Retirada da cloaca",
        "Corte abdominal",
        "Eventração",
        "Retirada da moela",
        "Abertura da moela",
        "Retirada do coração",
        "Retirada do pulmão",
        "Retirada da cabeça/Revisão final",
        "Limpeza de miudos",
        "Corte",
        "Organização da bandeja",
        "Ensaque da bandeja",
        "Selagem",
        "Pesagem",
        "Embalagem secundária",
        "Rotulagem",
        "Outra"
    ]

    return render_template(
        "editar_mao_obra_lote.html",
        registros=registros,
        ids=ids,
        setores=setores_padrao(),
        lista_funcoes=lista_funcoes
    )


@app.route("/mao-obra/lote/excluir", methods=["POST"])
@perfil_permitido("producao")
def excluir_mao_obra_lote():
    ids = ids_do_request("ids")

    if not ids:
        flash("Selecione pelo menos um lançamento de mão de obra para excluir.")
        return redirect(url_for("consultar_op"))

    registros = obter_registros_por_ids("apontamentos_mao_obra", ids)
    op_id = primeiro_op_id(registros)

    if not registros:
        flash("Nenhum lançamento de mão de obra encontrado.")
        return redirect(url_for("consultar_op"))

    if edicao_bloqueada_por_status(registros):
        flash("Esta OP está encerrada. Exclusão de mão de obra bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    placeholders = ",".join(["?"] * len(ids))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    DELETE FROM apontamentos_mao_obra
    WHERE id IN ({placeholders})
    """), tuple(ids))

    conn.commit()
    conn.close()

    flash("Lançamentos de mão de obra excluídos com sucesso.")
    return redirect(url_for("consultar_op", op_id=op_id))


@app.route("/paradas/lote/editar", methods=["GET", "POST"])
@perfil_permitido("producao")
def editar_paradas_lote():
    ids = ids_do_request("ids")

    if not ids:
        flash("Selecione pelo menos um lançamento de parada.")
        return redirect(url_for("consultar_op"))

    registros = obter_registros_por_ids("apontamentos_paradas", ids)

    if not registros:
        flash("Nenhum lançamento de parada encontrado.")
        return redirect(url_for("consultar_op"))

    op_id = primeiro_op_id(registros)

    if edicao_bloqueada_por_status(registros):
        flash("Esta OP está encerrada. Edição de parada bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    if request.method == "POST" and request.form.get("acao") == "salvar":
        data = request.form["data"]
        setor = request.form["setor"]
        motivo = request.form["motivo"]
        horas_paradas = float(request.form.get("horas_paradas") or 0)
        observacoes = request.form.get("observacoes", "")

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        UPDATE apontamentos_paradas
        SET data = ?,
            setor = ?,
            motivo = ?,
            horas_paradas = ?,
            observacoes = ?
        WHERE id IN ({placeholders})
        """), (data, setor, motivo, horas_paradas, observacoes, *ids))

        conn.commit()
        conn.close()

        flash("Lançamentos de parada atualizados com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    lista_motivos_parada = [
        "Falta de matéria prima",
        "Falta de insumos",
        "Falta de mão de obra",
        "Quebra de equipamento",
        "Manutenção corretiva",
        "Manutenção preventiva",
        "Falta de energia",
        "Ajuste operacional",
        "Limpeza / higienização",
        "Outro"
    ]

    return render_template(
        "editar_paradas_lote.html",
        registros=registros,
        ids=ids,
        setores=setores_padrao(),
        lista_motivos_parada=lista_motivos_parada
    )


@app.route("/paradas/lote/excluir", methods=["POST"])
@perfil_permitido("producao")
def excluir_paradas_lote():
    ids = ids_do_request("ids")

    if not ids:
        flash("Selecione pelo menos um lançamento de parada para excluir.")
        return redirect(url_for("consultar_op"))

    registros = obter_registros_por_ids("apontamentos_paradas", ids)
    op_id = primeiro_op_id(registros)

    if not registros:
        flash("Nenhum lançamento de parada encontrado.")
        return redirect(url_for("consultar_op"))

    if edicao_bloqueada_por_status(registros):
        flash("Esta OP está encerrada. Exclusão de parada bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    placeholders = ",".join(["?"] * len(ids))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    DELETE FROM apontamentos_paradas
    WHERE id IN ({placeholders})
    """), tuple(ids))

    conn.commit()
    conn.close()

    flash("Lançamentos de parada excluídos com sucesso.")
    return redirect(url_for("consultar_op", op_id=op_id))




@app.route("/descartes/lote/editar", methods=["GET", "POST"])
@perfil_permitido("qualidade")
def editar_descartes_lote():
    ids = ids_do_request("ids")

    if not ids:
        flash("Selecione pelo menos um descarte.")
        return redirect(url_for("consultar_op"))

    registros = obter_registros_por_ids("apontamentos_descartes", ids)

    if not registros:
        flash("Nenhum descarte encontrado.")
        return redirect(url_for("consultar_op"))

    op_id = primeiro_op_id(registros)

    if edicao_bloqueada_por_status(registros):
        flash("Esta OP está encerrada. Edição de descartes bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    if request.method == "POST" and request.form.get("acao") == "salvar":
        categoria = request.form["categoria"]
        motivo = request.form["motivo"]
        unidade = request.form["unidade"]
        observacoes = request.form.get("observacoes", "")

        placeholders = ",".join(["?"] * len(ids))

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q(f"""
        UPDATE apontamentos_descartes
        SET categoria = ?,
            motivo = ?,
            unidade = ?,
            observacoes = ?
        WHERE id IN ({placeholders})
        """), (categoria, motivo, unidade, observacoes, *ids))

        conn.commit()
        conn.close()

        flash("Descartes atualizados com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    return render_template(
        "editar_descartes_lote.html",
        registros=registros,
        ids=ids
    )


@app.route("/descartes/lote/excluir", methods=["POST"])
@perfil_permitido("qualidade")
def excluir_descartes_lote():
    ids = ids_do_request("ids")

    if not ids:
        flash("Selecione pelo menos um descarte.")
        return redirect(url_for("consultar_op"))

    registros = obter_registros_por_ids("apontamentos_descartes", ids)

    if not registros:
        flash("Nenhum descarte encontrado.")
        return redirect(url_for("consultar_op"))

    op_id = primeiro_op_id(registros)

    if edicao_bloqueada_por_status(registros):
        flash("Esta OP está encerrada. Exclusão de descartes bloqueada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    placeholders = ",".join(["?"] * len(ids))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    DELETE FROM apontamentos_descartes
    WHERE id IN ({placeholders})
    """), tuple(ids))

    conn.commit()
    conn.close()

    flash("Descartes excluídos com sucesso.")
    return redirect(url_for("consultar_op", op_id=op_id))


@app.route("/op/<int:op_id>/excluir", methods=["POST"])
@perfil_permitido("admin")
def excluir_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    for tabela in [
        "apontamentos_setor",
        "apontamentos_producao",
        "apontamentos_mao_obra",
        "apontamentos_paradas",
        "apontamentos_descartes"
    ]:
        cursor.execute(q(f"DELETE FROM {tabela} WHERE op_id = ?"), (op_id,))

    cursor.execute(q("DELETE FROM ordens_producao WHERE id = ?"), (op_id,))

    conn.commit()
    conn.close()

    flash("OP excluída com sucesso.")
    return redirect(url_for("consultar_op"))


@app.route("/op/<int:op_id>/encerrar", methods=["POST"])
@perfil_permitido("pcp")
def encerrar_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    UPDATE ordens_producao
    SET status = ?
    WHERE id = ?
    """), ("Encerrada", op_id))

    conn.commit()
    conn.close()

    flash("OP encerrada com sucesso.")
    return redirect(url_for("consultar_op", op_id=op_id))


@app.route("/op/<int:op_id>/reabrir", methods=["POST"])
@perfil_permitido("admin")
def reabrir_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    UPDATE ordens_producao
    SET status = ?
    WHERE id = ?
    """), ("Aberta", op_id))

    conn.commit()
    conn.close()

    flash("OP reaberta com sucesso.")
    return redirect(url_for("consultar_op", op_id=op_id))


@app.route("/consultar-op")
@perfil_permitido("pcp", "qualidade", "producao")
def consultar_op():
    criar_banco()

    op_id = request.args.get("op_id")
    ordens = buscar_ordens()

    op = None
    producoes = []
    mao_obra = []
    paradas = []
    descartes = []
    resumo = None

    if op_id:
        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
        op = cursor.fetchone()

        cursor.execute(q("SELECT * FROM apontamentos_producao WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        producoes = cursor.fetchall()

        cursor.execute(q("SELECT * FROM apontamentos_mao_obra WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        mao_obra = cursor.fetchall()

        cursor.execute(q("SELECT * FROM apontamentos_paradas WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        paradas = cursor.fetchall()

        cursor.execute(q("SELECT * FROM apontamentos_descartes WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        descartes = cursor.fetchall()

        if op:
            resumo = calcular_resumo_op(op, producoes, descartes)

        conn.close()

    return render_template(
        "consultar_op.html",
        ordens=ordens,
        op=op,
        producoes=producoes,
        mao_obra=mao_obra,
        paradas=paradas,
        descartes=descartes,
        resumo=resumo
    )


@app.route("/op/<int:op_id>/imprimir")
@perfil_permitido("pcp", "qualidade", "producao")
def imprimir_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
    op = cursor.fetchone()

    cursor.execute(q("SELECT * FROM apontamentos_producao WHERE op_id = ? ORDER BY id ASC"), (op_id,))
    producoes = cursor.fetchall()

    cursor.execute(q("SELECT * FROM apontamentos_mao_obra WHERE op_id = ? ORDER BY id ASC"), (op_id,))
    mao_obra = cursor.fetchall()

    cursor.execute(q("SELECT * FROM apontamentos_paradas WHERE op_id = ? ORDER BY id ASC"), (op_id,))
    paradas = cursor.fetchall()

    cursor.execute(q("SELECT * FROM apontamentos_descartes WHERE op_id = ? ORDER BY id ASC"), (op_id,))
    descartes = cursor.fetchall()

    resumo = calcular_resumo_op(op, producoes, descartes) if op else None

    conn.close()

    return render_template(
        "op_impressao.html",
        op=op,
        producoes=producoes,
        mao_obra=mao_obra,
        paradas=paradas,
        descartes=descartes,
        resumo=resumo
    )


@app.route("/cadastrar-usuario", methods=["GET", "POST"])
@perfil_permitido("admin")
def cadastrar_usuario():
    criar_banco()

    if request.method == "POST":
        nome = request.form["nome"]
        email = request.form["email"]
        senha = request.form["senha"]
        perfil = request.form["perfil"]

        senha_hash = generate_password_hash(senha)

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        INSERT INTO usuarios (
            nome,
            email,
            senha_hash,
            perfil
        )
        VALUES (?, ?, ?, ?)
        """), (
            nome,
            email,
            senha_hash,
            perfil
        ))

        conn.commit()
        conn.close()

        flash("Usuário cadastrado com sucesso.")

        return redirect(url_for("cadastrar_usuario"))

    return render_template("cadastrar_usuario.html")


@app.route("/relatorio")
@perfil_permitido("pcp")
def relatorio():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        setor,
        COUNT(*) as registros,
        SUM(quantidade) as total_produzido
    FROM apontamentos_producao
    GROUP BY setor
    ORDER BY setor
    """)

    dados_setores = cursor.fetchall()
    conn.close()

    return render_template(
        "relatorio.html",
        dados_setores=dados_setores
    )


if __name__ == "__main__":
    criar_banco()
    criar_tabela_fornecedores()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
