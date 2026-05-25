from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
from urllib.parse import urlparse
import os
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
            status TEXT DEFAULT 'Aberta'
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
            status TEXT DEFAULT 'Aberta'
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
            return redirect(url_for("dashboard"))

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
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_producao (
        op_id, data, setor, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?)
    """), (
        int(form["op_id"]),
        form["data"],
        form["setor"],
        float(form["quantidade"]),
        form["unidade"],
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def salvar_apontamento_mao_obra(form):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_mao_obra (
        op_id, data, colaborador, funcao, setor, turno, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        int(form["op_id"]),
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
    conn = conectar()
    cursor = conn.cursor()

    horas_paradas = float(form.get("horas_paradas") or 0)

    if horas_paradas <= 0 and form.get("hora_inicio") and form.get("hora_fim"):
        horas_paradas = calcular_horas_programadas(
            form["hora_inicio"],
            form["hora_fim"]
        )

    cursor.execute(q("""
    INSERT INTO apontamentos_paradas (
        op_id, data, setor, motivo, hora_inicio, hora_fim, horas_paradas, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        int(form["op_id"]),
        form["data"],
        form["setor"],
        form["motivo"],
        form.get("hora_inicio", ""),
        form.get("hora_fim", ""),
        horas_paradas,
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def salvar_apontamento_descarte(form):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO apontamentos_descartes (
        op_id, data, setor, categoria, motivo, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        int(form["op_id"]),
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
        "ordens": buscar_ordens(),
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

            if session["perfil"] == "admin":
                return redirect(url_for("dashboard"))

            elif session["perfil"] == "pcp":
                return redirect(url_for("dashboard"))

            elif session["perfil"] == "qualidade":
                return redirect(url_for("apontamento_descartes"))

            elif session["perfil"] == "producao":
                return redirect(url_for("apontamento_producao"))

            return redirect(url_for("dashboard"))

        flash("Usuário ou senha inválidos")

    return render_template("login.html")


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@perfil_permitido("pcp")
def dashboard():
    hoje = datetime.now().strftime("%Y-%m-%d")

    data_inicio = request.args.get("data_inicio") or hoje
    data_fim = request.args.get("data_fim") or hoje

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        COALESCE(SUM(quantidade_aves), 0) as aves_recebidas,
        COALESCE(SUM(mortes_antes_pendura), 0) as mortes_antes_pendura,
        COALESCE(SUM(peso_vivo), 0) as peso_entrada
    FROM ordens_producao
    WHERE data BETWEEN ? AND ?
    """), (data_inicio, data_fim))

    dados = cursor.fetchone()
    aves_recebidas = dados["aves_recebidas"]
    mortes_antes_pendura = dados["mortes_antes_pendura"]
    peso_entrada = dados["peso_entrada"]
    aves_abatidas = aves_recebidas - mortes_antes_pendura

    cursor.execute(q("""
    SELECT COALESCE(SUM(d.quantidade), 0) as descartes_aves
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
    """), (data_inicio, data_fim))

    descartes_aves = cursor.fetchone()["descartes_aves"]

    cursor.execute(q("""
    SELECT COALESCE(SUM(d.quantidade), 0) as descartes_kg
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) = 'kg'
    """), (data_inicio, data_fim))

    descartes_kg = cursor.fetchone()["descartes_kg"]

    cursor.execute(q("""
    SELECT COALESCE(SUM(p.quantidade), 0) as kg
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(p.unidade) = 'kg'
    """), (data_inicio, data_fim))

    kg_produzidos = cursor.fetchone()["kg"]

    viabilidade = aves_recebidas - mortes_antes_pendura - descartes_aves
    viabilidade_percentual = 0

    if aves_recebidas > 0:
        viabilidade_percentual = (viabilidade / aves_recebidas) * 100

    rendimento = 0
    if peso_entrada > 0:
        rendimento = (kg_produzidos / peso_entrada) * 100

    cursor.execute(q("""
    SELECT p.setor, SUM(p.quantidade) as total_produzido
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
    GROUP BY p.setor
    ORDER BY p.setor
    """), (data_inicio, data_fim))

    produtividade_setores = cursor.fetchall()
    conn.close()

    return render_template(
        "dashboard.html",
        data_inicio=data_inicio,
        data_fim=data_fim,
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
        produtividade_setores=produtividade_setores
    )


@app.route("/ordem-producao", methods=["GET", "POST"])
@perfil_permitido("pcp")
def ordem_producao():
    criar_banco()

    if request.method == "POST":
        data = request.form["data"]
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
            data, fornecedor, gta, nota_fiscal, quantidade_aves,
            mortes_antes_pendura, peso_vivo, peso_medio, observacoes, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            data, fornecedor, gta, nota_fiscal, quantidade_aves,
            mortes_antes_pendura, peso_vivo, peso_medio, observacoes, "Aberta"
        ))

        conn.commit()
        conn.close()

        flash("OP cadastrada com sucesso")
        return redirect(url_for("ordem_producao"))

    hoje = datetime.now().strftime("%Y-%m-%d")
    ordens = buscar_ordens()[:10]

    return render_template(
        "ordem_producao.html",
        hoje=hoje,
        ordens=ordens
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
        salvar_apontamento_producao(request.form)
        flash("Apontamento de produção salvo.")
        return redirect(url_for("apontamento_producao"))

    return render_template("apontamento_producao.html", **contexto_apontamento())


@app.route("/apontamento-mao-obra", methods=["GET", "POST"])
@perfil_permitido("producao")
def apontamento_mao_obra():
    criar_banco()

    if request.method == "POST":
        salvar_apontamento_mao_obra(request.form)
        flash("Apontamento de mão de obra salvo.")
        return redirect(url_for("apontamento_mao_obra"))

    return render_template("apontamento_mao_obra.html", **contexto_apontamento())


@app.route("/apontamento-paradas", methods=["GET", "POST"])
@perfil_permitido("producao")
def apontamento_paradas():
    criar_banco()

    if request.method == "POST":
        salvar_apontamento_parada(request.form)
        flash("Apontamento de horas paradas salvo.")
        return redirect(url_for("apontamento_paradas"))

    return render_template("apontamento_paradas.html", **contexto_apontamento())


@app.route("/apontamento-descartes", methods=["GET", "POST"])
@perfil_permitido("qualidade")
def apontamento_descartes():
    criar_banco()

    if request.method == "POST":
        salvar_apontamento_descarte(request.form)
        flash("Apontamento de descarte/condenação salvo.")
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

    if request.method == "POST":
        data = request.form["data"]
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
        SET data = ?, fornecedor = ?, gta = ?, nota_fiscal = ?,
            quantidade_aves = ?, mortes_antes_pendura = ?, peso_vivo = ?,
            peso_medio = ?, observacoes = ?
        WHERE id = ?
        """), (
            data, fornecedor, gta, nota_fiscal, quantidade_aves,
            mortes_antes_pendura, peso_vivo, peso_medio, observacoes, op_id
        ))

        conn.commit()
        conn.close()

        flash("OP atualizada com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    conn.close()
    return render_template("editar_op.html", op=op)


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
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
