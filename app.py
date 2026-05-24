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


def criar_banco():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL
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
            observacoes TEXT
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
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL
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
            observacoes TEXT
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

    cursor.execute("SELECT COUNT(*) as total FROM usuarios")
    total = cursor.fetchone()["total"]

    if total == 0:
        cursor.execute(q("""
        INSERT INTO usuarios (nome, email, senha_hash)
        VALUES (?, ?, ?)
        """), (
            "Administrador",
            "admin@app.com",
            generate_password_hash("admin123")
        ))

    conn.commit()
    conn.close()


def login_obrigatorio(funcao):
    @wraps(funcao)
    def wrapper(*args, **kwargs):
        if "usuario_id" not in session:
            return redirect(url_for("login"))
        return funcao(*args, **kwargs)
    return wrapper


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


def calcular_resumo_op(op, apontamentos):
    total_condenacoes = sum(item["condenacoes"] for item in apontamentos)
    total_perdas = sum(item["perdas"] for item in apontamentos)

    kg_produzidos = sum(
        item["quantidade_produzida"]
        for item in apontamentos
        if item["unidade"].lower() == "kg"
    )

    aves_abatidas = op["quantidade_aves"] - op["mortes_antes_pendura"]
    descartes = op["mortes_antes_pendura"] + total_condenacoes + total_perdas
    viabilidade = op["quantidade_aves"] - descartes

    viabilidade_percentual = 0
    if op["quantidade_aves"] > 0:
        viabilidade_percentual = (viabilidade / op["quantidade_aves"]) * 100

    rendimento = 0
    if op["peso_vivo"] > 0:
        rendimento = (kg_produzidos / op["peso_vivo"]) * 100

    return {
        "aves_abatidas": aves_abatidas,
        "total_condenacoes": total_condenacoes,
        "total_perdas": total_perdas,
        "kg_produzidos": kg_produzidos,
        "viabilidade": viabilidade,
        "viabilidade_percentual": round(viabilidade_percentual, 2),
        "rendimento": round(rendimento, 2)
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
            return redirect(url_for("dashboard"))

        flash("Usuário ou senha inválidos")

    return render_template("login.html")


@app.route("/sair")
def sair():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_obrigatorio
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
    SELECT
        COALESCE(SUM(a.condenacoes), 0) as condenacoes,
        COALESCE(SUM(a.perdas), 0) as perdas
    FROM apontamentos_setor a
    JOIN ordens_producao o ON o.id = a.op_id
    WHERE o.data BETWEEN ? AND ?
    """), (data_inicio, data_fim))

    perdas = cursor.fetchone()

    total_condenacoes = perdas["condenacoes"]
    total_perdas = perdas["perdas"]

    descartes = mortes_antes_pendura + total_condenacoes + total_perdas
    viabilidade = aves_recebidas - descartes

    viabilidade_percentual = 0
    if aves_recebidas > 0:
        viabilidade_percentual = (viabilidade / aves_recebidas) * 100

    cursor.execute(q("""
    SELECT
        COALESCE(SUM(a.quantidade_produzida), 0) as kg
    FROM apontamentos_setor a
    JOIN ordens_producao o ON o.id = a.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(a.unidade) = 'kg'
    """), (data_inicio, data_fim))

    kg_produzidos = cursor.fetchone()["kg"]

    rendimento = 0
    if peso_entrada > 0:
        rendimento = (kg_produzidos / peso_entrada) * 100

    cursor.execute(q("""
    SELECT
        a.setor,
        AVG(a.produtividade) as produtividade_media
    FROM apontamentos_setor a
    JOIN ordens_producao o ON o.id = a.op_id
    WHERE o.data BETWEEN ? AND ?
    GROUP BY a.setor
    ORDER BY produtividade_media DESC
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
        total_condenacoes=round(total_condenacoes, 2),
        total_perdas=round(total_perdas, 2),
        produtividade_setores=produtividade_setores
    )


@app.route("/ordem-producao", methods=["GET", "POST"])
@login_obrigatorio
def ordem_producao():
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
            data,
            fornecedor,
            gta,
            nota_fiscal,
            quantidade_aves,
            mortes_antes_pendura,
            peso_vivo,
            peso_medio,
            observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            data,
            fornecedor,
            gta,
            nota_fiscal,
            quantidade_aves,
            mortes_antes_pendura,
            peso_vivo,
            peso_medio,
            observacoes
        ))

        conn.commit()
        conn.close()

        flash("OP cadastrada com sucesso")
        return redirect(url_for("ordem_producao"))

    hoje = datetime.now().strftime("%Y-%m-%d")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM ordens_producao
    ORDER BY id DESC
    LIMIT 10
    """)

    ordens = cursor.fetchall()
    conn.close()

    return render_template(
        "ordem_producao.html",
        hoje=hoje,
        ordens=ordens
    )


@app.route("/op/<int:op_id>/editar", methods=["GET", "POST"])
@login_obrigatorio
def editar_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

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
        SET
            data = ?,
            fornecedor = ?,
            gta = ?,
            nota_fiscal = ?,
            quantidade_aves = ?,
            mortes_antes_pendura = ?,
            peso_vivo = ?,
            peso_medio = ?,
            observacoes = ?
        WHERE id = ?
        """), (
            data,
            fornecedor,
            gta,
            nota_fiscal,
            quantidade_aves,
            mortes_antes_pendura,
            peso_vivo,
            peso_medio,
            observacoes,
            op_id
        ))

        conn.commit()
        conn.close()

        flash("OP atualizada com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    conn.close()

    return render_template(
        "editar_op.html",
        op=op
    )


@app.route("/op/<int:op_id>/excluir", methods=["POST"])
@login_obrigatorio
def excluir_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    DELETE FROM apontamentos_setor
    WHERE op_id = ?
    """), (op_id,))

    cursor.execute(q("""
    DELETE FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    conn.commit()
    conn.close()

    flash("OP excluída com sucesso.")
    return redirect(url_for("consultar_op"))


@app.route("/consultar-op")
@login_obrigatorio
def consultar_op():
    op_id = request.args.get("op_id")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM ordens_producao
    ORDER BY id DESC
    """)

    ordens = cursor.fetchall()

    op = None
    apontamentos = []
    resumo = None

    if op_id:
        cursor.execute(q("""
        SELECT *
        FROM ordens_producao
        WHERE id = ?
        """), (op_id,))

        op = cursor.fetchone()

        cursor.execute(q("""
        SELECT *
        FROM apontamentos_setor
        WHERE op_id = ?
        ORDER BY id ASC
        """), (op_id,))

        apontamentos = cursor.fetchall()

        if op:
            resumo = calcular_resumo_op(op, apontamentos)

    conn.close()

    return render_template(
        "consultar_op.html",
        ordens=ordens,
        op=op,
        apontamentos=apontamentos,
        resumo=resumo
    )


@app.route("/op/<int:op_id>/imprimir")
@login_obrigatorio
def imprimir_op(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()

    cursor.execute(q("""
    SELECT *
    FROM apontamentos_setor
    WHERE op_id = ?
    ORDER BY id ASC
    """), (op_id,))

    apontamentos = cursor.fetchall()

    resumo = None
    if op:
        resumo = calcular_resumo_op(op, apontamentos)

    conn.close()

    return render_template(
        "op_impressao.html",
        op=op,
        apontamentos=apontamentos,
        resumo=resumo
    )


@app.route("/apontamento-setor", methods=["GET", "POST"])
@login_obrigatorio
def apontamento_setor():
    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        op_id = int(request.form["op_id"])
        data = request.form["data"]
        setor = request.form["setor"]
        colaboradores = int(request.form["colaboradores"])
        hora_inicio = request.form["hora_inicio"]
        hora_fim = request.form["hora_fim"]
        horas_paradas = float(request.form["horas_paradas"])
        motivo_parada = request.form["motivo_parada"]
        quantidade_produzida = float(request.form["quantidade_produzida"])
        unidade = request.form["unidade"]
        condenacoes = float(request.form["condenacoes"])
        perdas = float(request.form["perdas"])
        observacoes = request.form["observacoes"]

        horas_programadas = calcular_horas_programadas(
            hora_inicio,
            hora_fim
        )

        produtividade = calcular_produtividade(
            quantidade_produzida,
            colaboradores,
            horas_programadas,
            horas_paradas
        )

        cursor.execute(q("""
        INSERT INTO apontamentos_setor (
            op_id,
            data,
            setor,
            colaboradores,
            hora_inicio,
            hora_fim,
            horas_programadas,
            horas_paradas,
            motivo_parada,
            quantidade_produzida,
            unidade,
            condenacoes,
            perdas,
            produtividade,
            observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            op_id,
            data,
            setor,
            colaboradores,
            hora_inicio,
            hora_fim,
            horas_programadas,
            horas_paradas,
            motivo_parada,
            quantidade_produzida,
            unidade,
            condenacoes,
            perdas,
            produtividade,
            observacoes
        ))

        conn.commit()
        conn.close()

        flash(f"Produtividade calculada: {produtividade} {unidade}/HH")
        return redirect(url_for("apontamento_setor"))

    hoje = datetime.now().strftime("%Y-%m-%d")

    cursor.execute("""
    SELECT *
    FROM ordens_producao
    ORDER BY id DESC
    """)

    ordens = cursor.fetchall()
    conn.close()

    setores = [
        "Recepção/Pendura",
        "Escalda",
        "Evisceração",
        "Corte",
        "Embalagem",
        "Expedição"
    ]

    return render_template(
        "apontamento_setor.html",
        hoje=hoje,
        ordens=ordens,
        setores=setores
    )


@app.route("/apontamento/<int:apontamento_id>/editar", methods=["GET", "POST"])
@login_obrigatorio
def editar_apontamento(apontamento_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM apontamentos_setor
    WHERE id = ?
    """), (apontamento_id,))

    apontamento = cursor.fetchone()

    if not apontamento:
        conn.close()
        flash("Apontamento não encontrado.")
        return redirect(url_for("consultar_op"))

    if request.method == "POST":
        data = request.form["data"]
        setor = request.form["setor"]
        colaboradores = int(request.form["colaboradores"])
        hora_inicio = request.form["hora_inicio"]
        hora_fim = request.form["hora_fim"]
        horas_paradas = float(request.form["horas_paradas"])
        motivo_parada = request.form["motivo_parada"]
        quantidade_produzida = float(request.form["quantidade_produzida"])
        unidade = request.form["unidade"]
        condenacoes = float(request.form["condenacoes"])
        perdas = float(request.form["perdas"])
        observacoes = request.form["observacoes"]

        horas_programadas = calcular_horas_programadas(hora_inicio, hora_fim)

        produtividade = calcular_produtividade(
            quantidade_produzida,
            colaboradores,
            horas_programadas,
            horas_paradas
        )

        cursor.execute(q("""
        UPDATE apontamentos_setor
        SET
            data = ?,
            setor = ?,
            colaboradores = ?,
            hora_inicio = ?,
            hora_fim = ?,
            horas_programadas = ?,
            horas_paradas = ?,
            motivo_parada = ?,
            quantidade_produzida = ?,
            unidade = ?,
            condenacoes = ?,
            perdas = ?,
            produtividade = ?,
            observacoes = ?
        WHERE id = ?
        """), (
            data,
            setor,
            colaboradores,
            hora_inicio,
            hora_fim,
            horas_programadas,
            horas_paradas,
            motivo_parada,
            quantidade_produzida,
            unidade,
            condenacoes,
            perdas,
            produtividade,
            observacoes,
            apontamento_id
        ))

        conn.commit()
        op_id = apontamento["op_id"]
        conn.close()

        flash("Apontamento atualizado com sucesso.")
        return redirect(url_for("consultar_op", op_id=op_id))

    conn.close()

    setores = [
        "Recepção/Pendura",
        "Escalda",
        "Evisceração",
        "Corte",
        "Embalagem",
        "Expedição"
    ]

    return render_template(
        "editar_apontamento.html",
        apontamento=apontamento,
        setores=setores
    )


@app.route("/apontamento/<int:apontamento_id>/excluir", methods=["POST"])
@login_obrigatorio
def excluir_apontamento(apontamento_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT op_id
    FROM apontamentos_setor
    WHERE id = ?
    """), (apontamento_id,))

    apontamento = cursor.fetchone()

    if not apontamento:
        conn.close()
        flash("Apontamento não encontrado.")
        return redirect(url_for("consultar_op"))

    op_id = apontamento["op_id"]

    cursor.execute(q("""
    DELETE FROM apontamentos_setor
    WHERE id = ?
    """), (apontamento_id,))

    conn.commit()
    conn.close()

    flash("Apontamento excluído com sucesso.")
    return redirect(url_for("consultar_op", op_id=op_id))


@app.route("/relatorio")
@login_obrigatorio
def relatorio():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        setor,
        COUNT(*) as registros,
        SUM(quantidade_produzida) as total_produzido,
        SUM(condenacoes) as total_condenacoes,
        SUM(perdas) as total_perdas,
        AVG(produtividade) as produtividade_media
    FROM apontamentos_setor
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