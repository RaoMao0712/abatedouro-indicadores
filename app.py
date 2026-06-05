from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import calendar
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


CATEGORIAS_CUSTOS = [
    "Mão de obra",
    "Energia",
    "Água",
    "Lenha",
    "Combustível",

    "Manutenção de Equipamentos",
    "Manutenção Predial",

    "Material de Limpeza",
    "Material de Escritório",

    "EPIs",

    "Marketing",
    "Cursos e Treinamentos",

    "Consultoria e Responsabilidade Técnica",

    "Contratos com Clientes",

    "Insumos para Produção",

    "Outros"
]


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

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_tempos_setor (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
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

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_tempos_setor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
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



def criar_tabela_tempos_setor():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_tempos_setor (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS apontamentos_tempos_setor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            setor TEXT NOT NULL,
            hora_inicio TEXT NOT NULL,
            hora_fim TEXT NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()





def criar_tabelas_custos():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS parametros_custos (
            id SERIAL PRIMARY KEY,
            sku TEXT UNIQUE NOT NULL,
            custo_ave REAL DEFAULT 0,
            unidade_custo_ave TEXT DEFAULT '',
            custo_embalagem REAL DEFAULT 0,
            unidade_custo_embalagem TEXT DEFAULT '',
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS custos_mensais (
            id SERIAL PRIMARY KEY,
            competencia TEXT NOT NULL,
            categoria TEXT NOT NULL,
            valor REAL NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS parametros_custos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE NOT NULL,
            custo_ave REAL DEFAULT 0,
            unidade_custo_ave TEXT DEFAULT '',
            custo_embalagem REAL DEFAULT 0,
            unidade_custo_embalagem TEXT DEFAULT '',
            atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS custos_mensais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            competencia TEXT NOT NULL,
            categoria TEXT NOT NULL,
            valor REAL NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()

    parametros_padrao = [
        ("Galinha Cortada", 0, "R$/kg vivo", 0, "R$/kg produzido"),
        ("Galinha Inteira", 0, "R$/ave", 0, "R$/unidade")
    ]

    for item in parametros_padrao:
        try:
            cursor.execute(q("""
            INSERT INTO parametros_custos (
                sku,
                custo_ave,
                unidade_custo_ave,
                custo_embalagem,
                unidade_custo_embalagem
            ) VALUES (?, ?, ?, ?, ?)
            """), item)
            conn.commit()
        except Exception:
            conn.rollback()

    conn.close()


def buscar_parametros_custos():
    criar_tabelas_custos()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM parametros_custos
    ORDER BY sku
    """)

    parametros = cursor.fetchall()
    conn.close()

    return parametros


def buscar_custos_mensais():
    criar_tabelas_custos()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM custos_mensais
    ORDER BY competencia DESC, categoria ASC
    """)

    custos = cursor.fetchall()
    conn.close()

    return custos


def chave_sku_custo(sku):
    return (
        sku.lower()
        .replace(" ", "_")
        .replace("ã", "a")
    )


def salvar_parametros_custos(form):
    criar_tabelas_custos()

    conn = conectar()
    cursor = conn.cursor()

    skus = ["Galinha Cortada", "Galinha Inteira"]

    for sku in skus:
        chave = chave_sku_custo(sku)

        custo_ave = float(form.get(f"custo_ave_{chave}") or 0)
        custo_embalagem = float(form.get(f"custo_embalagem_{chave}") or 0)

        if sku == "Galinha Cortada":
            unidade_custo_ave = "R$/kg vivo"
            unidade_custo_embalagem = "R$/kg produzido"
        else:
            unidade_custo_ave = "R$/ave"
            unidade_custo_embalagem = "R$/unidade"

        cursor.execute(q("""
        UPDATE parametros_custos
        SET custo_ave = ?,
            unidade_custo_ave = ?,
            custo_embalagem = ?,
            unidade_custo_embalagem = ?
        WHERE sku = ?
        """), (
            custo_ave,
            unidade_custo_ave,
            custo_embalagem,
            unidade_custo_embalagem,
            sku
        ))

    conn.commit()
    conn.close()


def salvar_custo_mensal(form):
    criar_tabelas_custos()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO custos_mensais (
        competencia,
        categoria,
        valor,
        observacoes
    ) VALUES (?, ?, ?, ?)
    """), (
        form["competencia"],
        form["categoria"],
        float(form["valor"]),
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()





def criar_tabela_vendas():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendas_diarias (
            id SERIAL PRIMARY KEY,
            data TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantidade REAL NOT NULL,
            unidade TEXT NOT NULL,
            receita REAL NOT NULL,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendas_diarias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            sku TEXT NOT NULL,
            quantidade REAL NOT NULL,
            unidade TEXT NOT NULL,
            receita REAL NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()


def salvar_venda_diaria(form):
    criar_tabela_vendas()

    sku = form["sku"]
    quantidade = float(form["quantidade"])
    receita = float(form["receita"])

    if quantidade <= 0:
        raise ValueError("A quantidade vendida deve ser maior que zero.")

    if receita < 0:
        raise ValueError("A receita não pode ser negativa.")

    unidade = "kg" if sku == "Galinha Cortada" else "unidades"

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO vendas_diarias (
        data, sku, quantidade, unidade, receita, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?)
    """), (
        form["data"],
        sku,
        quantidade,
        unidade,
        receita,
        form.get("observacoes", "")
    ))

    conn.commit()
    conn.close()


def buscar_vendas_diarias():
    criar_tabela_vendas()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT *
    FROM vendas_diarias
    ORDER BY data DESC, id DESC
    """)

    vendas = cursor.fetchall()
    conn.close()

    return vendas



def buscar_custo_mensal_por_id(custo_id):
    criar_tabelas_custos()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM custos_mensais
    WHERE id = ?
    """), (custo_id,))
    custo = cursor.fetchone()
    conn.close()
    return custo


def buscar_venda_diaria_por_id(venda_id):
    criar_tabela_vendas()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT *
    FROM vendas_diarias
    WHERE id = ?
    """), (venda_id,))
    venda = cursor.fetchone()
    conn.close()
    return venda





def normalizar_competencia(competencia):
    if not competencia:
        return ""

    competencia = str(competencia).strip()

    if len(competencia) >= 7:
        return competencia[:7]

    return competencia


def listar_competencias_periodo(competencia_inicio, competencia_fim):
    inicio = datetime.strptime(competencia_inicio + "-01", "%Y-%m-%d")
    fim = datetime.strptime(competencia_fim + "-01", "%Y-%m-%d")

    competencias = []
    atual = inicio

    while atual <= fim:
        competencias.append(atual.strftime("%Y-%m"))

        if atual.month == 12:
            atual = atual.replace(year=atual.year + 1, month=1)
        else:
            atual = atual.replace(month=atual.month + 1)

    return competencias


def buscar_dados_relatorio_custos(competencia_inicio, competencia_fim):
    criar_tabelas_custos()

    competencias = listar_competencias_periodo(
        competencia_inicio,
        competencia_fim
    )

    categorias_padrao = CATEGORIAS_CUSTOS

    dados_por_categoria = {
        categoria: {competencia: 0 for competencia in competencias}
        for categoria in categorias_padrao
    }

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT
        competencia,
        categoria,
        COALESCE(SUM(valor), 0) as total
    FROM custos_mensais
    WHERE competencia BETWEEN ? AND ?
    GROUP BY competencia, categoria
    ORDER BY competencia, categoria
    """), (
        competencia_inicio,
        competencia_fim
    ))

    registros = cursor.fetchall()
    conn.close()

    for item in registros:
        competencia = normalizar_competencia(item["competencia"])
        categoria = item["categoria"]

        if categoria not in dados_por_categoria:
            dados_por_categoria[categoria] = {
                comp: 0 for comp in competencias
            }

        if competencia in dados_por_categoria[categoria]:
            dados_por_categoria[categoria][competencia] = float(item["total"] or 0)

    totais_por_categoria = {
        categoria: sum(valores.values())
        for categoria, valores in dados_por_categoria.items()
    }

    totais_por_competencia = {
        competencia: sum(
            dados_por_categoria[categoria].get(competencia, 0)
            for categoria in dados_por_categoria
        )
        for competencia in competencias
    }

    custo_total = sum(totais_por_categoria.values())
    media_mensal = custo_total / len(competencias) if competencias else 0

    maior_categoria = "Sem dados"
    valor_maior_categoria = 0

    if totais_por_categoria:
        maior_categoria = max(
            totais_por_categoria,
            key=lambda categoria: totais_por_categoria[categoria]
        )
        valor_maior_categoria = totais_por_categoria.get(maior_categoria, 0)

        if valor_maior_categoria == 0:
            maior_categoria = "Sem dados"

    maior_crescimento_categoria = "Sem dados"
    maior_crescimento_valor = 0

    for categoria, valores in dados_por_categoria.items():
        lista_valores = [valores.get(comp, 0) for comp in competencias]

        if len(lista_valores) < 2:
            continue

        crescimento = lista_valores[-1] - lista_valores[0]

        if crescimento > maior_crescimento_valor:
            maior_crescimento_valor = crescimento
            maior_crescimento_categoria = categoria

    datasets = []

    for categoria, valores in dados_por_categoria.items():
        datasets.append({
            "label": categoria,
            "data": [
                round(valores.get(competencia, 0), 2)
                for competencia in competencias
            ]
        })

    resumo_categorias = []

    for categoria, total in sorted(
        totais_por_categoria.items(),
        key=lambda item: item[1],
        reverse=True
    ):
        percentual = 0

        if custo_total > 0:
            percentual = (total / custo_total) * 100

        resumo_categorias.append({
            "categoria": categoria,
            "total": round(total, 2),
            "percentual": round(percentual, 2)
        })

    return {
        "competencias": competencias,
        "datasets": datasets,
        "custo_total": round(custo_total, 2),
        "media_mensal": round(media_mensal, 2),
        "maior_categoria": maior_categoria,
        "valor_maior_categoria": round(valor_maior_categoria, 2),
        "maior_crescimento_categoria": maior_crescimento_categoria,
        "maior_crescimento_valor": round(maior_crescimento_valor, 2),
        "totais_por_competencia": totais_por_competencia,
        "resumo_categorias": resumo_categorias
    }




def buscar_dados_dre_gerencial(competencia):
    criar_tabelas_custos()
    criar_tabela_vendas()

    ano, mes = competencia.split("-")
    ultimo_dia = calendar.monthrange(int(ano), int(mes))[1]
    data_inicio = f"{competencia}-01"
    data_fim = f"{competencia}-{ultimo_dia:02d}"

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT sku, COALESCE(SUM(receita), 0) as receita, COALESCE(SUM(quantidade), 0) as quantidade
    FROM vendas_diarias
    WHERE data BETWEEN ? AND ?
    GROUP BY sku
    ORDER BY sku
    """), (data_inicio, data_fim))
    vendas_raw = cursor.fetchall()

    vendas_por_sku = []
    receita_bruta = 0
    for item in vendas_raw:
        receita = float(item["receita"] or 0)
        receita_bruta += receita
        vendas_por_sku.append({
            "sku": item["sku"],
            "receita": round(receita, 2),
            "quantidade": round(float(item["quantidade"] or 0), 2)
        })

    cursor.execute("SELECT * FROM parametros_custos")
    parametros = {item["sku"]: item for item in cursor.fetchall()}

    cursor.execute(q("""
    SELECT COALESCE(sku, 'Galinha Cortada') as sku,
           COALESCE(SUM(quantidade_aves), 0) as aves_recebidas,
           COALESCE(SUM(peso_vivo), 0) as peso_vivo
    FROM ordens_producao
    WHERE data BETWEEN ? AND ?
      AND COALESCE(status, 'Aberta') = 'Encerrada'
    GROUP BY COALESCE(sku, 'Galinha Cortada')
    """), (data_inicio, data_fim))
    producao = {}
    for item in cursor.fetchall():
        producao[item["sku"]] = {
            "aves_recebidas": float(item["aves_recebidas"] or 0),
            "peso_vivo": float(item["peso_vivo"] or 0),
            "kg_produzidos": 0,
            "unidades_produzidas": 0
        }

    cursor.execute(q("""
    SELECT COALESCE(o.sku, 'Galinha Cortada') as sku,
           LOWER(p.unidade) as unidade,
           COALESCE(SUM(p.quantidade), 0) as quantidade
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND COALESCE(o.status, 'Aberta') = 'Encerrada'
      AND p.setor = 'Expedição'
    GROUP BY COALESCE(o.sku, 'Galinha Cortada'), LOWER(p.unidade)
    """), (data_inicio, data_fim))

    for item in cursor.fetchall():
        sku = item["sku"]
        if sku not in producao:
            producao[sku] = {"aves_recebidas": 0, "peso_vivo": 0, "kg_produzidos": 0, "unidades_produzidas": 0}
        unidade = item["unidade"]
        quantidade = float(item["quantidade"] or 0)
        if unidade == "kg":
            producao[sku]["kg_produzidos"] += quantidade
        if unidade in ["unidades", "unidade", "aves", "ave"]:
            producao[sku]["unidades_produzidas"] += quantidade

    cmv_por_sku = []
    cmv_total = 0
    for sku, prod in producao.items():
        param = parametros.get(sku)
        custo_ave = float(param["custo_ave"] or 0) if param else 0
        custo_embalagem = float(param["custo_embalagem"] or 0) if param else 0
        if sku == "Galinha Cortada":
            materia_prima = prod["peso_vivo"] * custo_ave
            embalagem = prod["kg_produzidos"] * custo_embalagem
        else:
            materia_prima = prod["aves_recebidas"] * custo_ave
            embalagem = prod["unidades_produzidas"] * custo_embalagem
        cmv = materia_prima + embalagem
        cmv_total += cmv
        cmv_por_sku.append({"sku": sku, "materia_prima": round(materia_prima, 2), "embalagem": round(embalagem, 2), "cmv": round(cmv, 2)})

    cursor.execute(q("""
    SELECT categoria, COALESCE(SUM(valor), 0) as total
    FROM custos_mensais
    WHERE competencia = ?
    GROUP BY categoria
    ORDER BY categoria
    """), (competencia,))
    custos_raw = cursor.fetchall()
    conn.close()

    categorias = CATEGORIAS_CUSTOS
    custos = {categoria: 0 for categoria in categorias}
    for item in custos_raw:
        custos[item["categoria"]] = custos.get(item["categoria"], 0) + float(item["total"] or 0)

    custos_operacionais_total = sum(custos.values())
    margem_bruta = receita_bruta - cmv_total
    resultado_operacional = margem_bruta - custos_operacionais_total

    def perc(valor):
        return (valor / receita_bruta * 100) if receita_bruta > 0 else 0

    linhas_custos = [{"categoria": cat, "valor": round(val, 2), "percentual": round(perc(val), 2)} for cat, val in custos.items()]

    return {
        "receita_bruta": round(receita_bruta, 2),
        "vendas_por_sku": vendas_por_sku,
        "cmv_total": round(cmv_total, 2),
        "cmv_percentual": round(perc(cmv_total), 2),
        "cmv_por_sku": cmv_por_sku,
        "margem_bruta": round(margem_bruta, 2),
        "margem_bruta_percentual": round(perc(margem_bruta), 2),
        "custos_operacionais_total": round(custos_operacionais_total, 2),
        "custos_operacionais_percentual": round(perc(custos_operacionais_total), 2),
        "linhas_custos": linhas_custos,
        "resultado_operacional": round(resultado_operacional, 2),
        "margem_operacional_percentual": round(perc(resultado_operacional), 2)
    }



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


def buscar_fornecedores():
    criar_tabela_fornecedores()

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



def copiar_mao_obra_de_op(origem_op_id, destino_op_id, data_destino):
    origem_op_id = int(origem_op_id)
    destino_op_id = int(destino_op_id)

    if origem_op_id == destino_op_id:
        raise ValueError("A OP de origem não pode ser a mesma OP de destino.")

    validar_op_aberta(destino_op_id)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM apontamentos_mao_obra
    WHERE op_id = ?
    ORDER BY id ASC
    """), (origem_op_id,))

    registros_origem = cursor.fetchall()

    if not registros_origem:
        conn.close()
        raise ValueError("A OP de origem não possui lançamentos de mão de obra para copiar.")

    cursor.execute(q("""
    DELETE FROM apontamentos_mao_obra
    WHERE op_id = ?
    """), (destino_op_id,))

    for item in registros_origem:
        cursor.execute(q("""
        INSERT INTO apontamentos_mao_obra (
            op_id, data, colaborador, funcao, setor, turno, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """), (
            destino_op_id,
            data_destino,
            item["colaborador"],
            item["funcao"],
            item["setor"],
            item["turno"],
            item["observacoes"]
        ))

    conn.commit()
    conn.close()

    return len(registros_origem)



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



def gerar_producao_automatica_setores(op, data_lancamento, hora_inicio, hora_fim, unidades_produzidas, kg_produzidos=None, descontar_almoco=False):
    setores_por_sku = {
        "Galinha Inteira": [
            "Recepção e Pendura",
            "Escalda e Depenagem",
            "Evisceração",
            "Embalagem"
        ],
        "Galinha Cortada": [
            "Recepção e Pendura",
            "Escalda e Depenagem",
            "Evisceração",
            "Corte",
            "Embalagem"
        ]
    }

    sku = op["sku"] or "Galinha Cortada"
    setores = setores_por_sku.get(sku, setores_por_sku["Galinha Cortada"])

    texto_almoco = "Sim" if descontar_almoco else "Não"

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    DELETE FROM apontamentos_producao
    WHERE op_id = ?
    """), (op["id"],))

    cursor.execute(q("""
    SELECT setor, COALESCE(SUM(quantidade), 0) as total
    FROM apontamentos_descartes
    WHERE op_id = ?
      AND LOWER(unidade) IN ('aves', 'ave', 'unidade', 'unidades')
    GROUP BY setor
    """), (op["id"],))

    descartes = cursor.fetchall()
    descartes_por_setor = {
        item["setor"]: float(item["total"] or 0)
        for item in descartes
    }

    entrada_setor = float((op["quantidade_aves"] or 0) - (op["mortes_antes_pendura"] or 0))

    for setor in setores:
        quantidade_setor = max(0, entrada_setor)

        cursor.execute(q("""
        INSERT INTO apontamentos_producao (
            op_id, data, setor, quantidade, unidade, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            op["id"],
            data_lancamento,
            setor,
            quantidade_setor,
            "unidades",
            f"Gerado automaticamente no encerramento da OP | Início: {hora_inicio} | Fim: {hora_fim} | Descontar almoço 1h12: {texto_almoco}"
        ))

        entrada_setor = quantidade_setor - descartes_por_setor.get(setor, 0)

    cursor.execute(q("""
    INSERT INTO apontamentos_producao (
        op_id, data, setor, quantidade, unidade, observacoes
    ) VALUES (?, ?, ?, ?, ?, ?)
    """), (
        op["id"],
        data_lancamento,
        "Expedição",
        float(unidades_produzidas),
        "unidades",
        f"Produção final informada no encerramento da OP | Início: {hora_inicio} | Fim: {hora_fim} | Descontar almoço 1h12: {texto_almoco}"
    ))

    if sku == "Galinha Cortada" and kg_produzidos is not None:
        cursor.execute(q("""
        INSERT INTO apontamentos_producao (
            op_id, data, setor, quantidade, unidade, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            op["id"],
            data_lancamento,
            "Expedição",
            float(kg_produzidos),
            "kg",
            f"Kg final produzido informado no encerramento da OP | Início: {hora_inicio} | Fim: {hora_fim} | Descontar almoço 1h12: {texto_almoco}"
        ))

    conn.commit()
    conn.close()


def buscar_op_por_id(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()
    conn.close()

    return op




def normalizar_chave_setor(setor):
    return (
        setor
        .replace(" ", "_")
        .replace("/", "_")
        .replace("ç", "c")
        .replace("ã", "a")
        .replace("é", "e")
    )


def setores_por_sku(sku):
    if sku == "Galinha Inteira":
        return [
            "Recepção e Pendura",
            "Escalda e Depenagem",
            "Evisceração",
            "Embalagem"
        ]

    return [
        "Recepção e Pendura",
        "Escalda e Depenagem",
        "Evisceração",
        "Corte",
        "Embalagem"
    ]


def salvar_tempos_setor(form):
    criar_tabela_tempos_setor()
    op_id = int(form["op_id"])
    validar_op_aberta(op_id)

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
        raise ValueError("OP não encontrada.")

    setores = setores_por_sku(op["sku"] or "Galinha Cortada")

    cursor.execute(q("""
    DELETE FROM apontamentos_tempos_setor
    WHERE op_id = ?
    """), (op_id,))

    for setor in setores:
        chave = normalizar_chave_setor(setor)
        hora_inicio = form.get(f"hora_inicio_{chave}")
        hora_fim = form.get(f"hora_fim_{chave}")

        if not hora_inicio or not hora_fim:
            conn.close()
            raise ValueError(f"Informe hora inicial e final para o setor {setor}.")

        cursor.execute(q("""
        INSERT INTO apontamentos_tempos_setor (
            op_id, data, setor, hora_inicio, hora_fim, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """), (
            op_id,
            op["data"],
            setor,
            hora_inicio,
            hora_fim,
            form.get("observacoes", "")
        ))

    conn.commit()
    conn.close()


def buscar_tempos_setor_por_op(op_id):
    criar_tabela_tempos_setor()
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM apontamentos_tempos_setor
    WHERE op_id = ?
    ORDER BY id ASC
    """), (op_id,))

    tempos = cursor.fetchall()
    conn.close()

    return tempos


def buscar_op_por_id(op_id):
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM ordens_producao
    WHERE id = ?
    """), (op_id,))

    op = cursor.fetchone()
    conn.close()

    return op



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
    sku_filtro = request.args.get("sku") or "Todos"

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

    sku_condicao_op = ""
    sku_condicao_alias = ""
    parametros_sku = ()

    if sku_filtro in ["Galinha Cortada", "Galinha Inteira"]:
        sku_condicao_op = " AND COALESCE(sku, 'Galinha Cortada') = ?"
        sku_condicao_alias = " AND COALESCE(o.sku, 'Galinha Cortada') = ?"
        parametros_sku = (sku_filtro,)
    else:
        sku_filtro = "Todos"

    parametros_filtros = parametros_status + parametros_sku

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
    {sku_condicao_op}
    """), (data_inicio, data_fim) + parametros_filtros)

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
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)

    descartes_aves = cursor.fetchone()["descartes_aves"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(d.quantidade), 0) as descartes_kg
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) = 'kg'
      {status_condicao_alias}
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)

    descartes_kg = cursor.fetchone()["descartes_kg"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(p.quantidade), 0) as kg
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(p.unidade) = 'kg'
      {status_condicao_alias}
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)

    kg_produzidos = cursor.fetchone()["kg"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(p.quantidade), 0) as unidades
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND p.setor = 'Expedição'
      AND LOWER(p.unidade) IN ('unidades', 'unidade', 'aves', 'ave')
      {status_condicao_alias}
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)

    unidades_produzidas = cursor.fetchone()["unidades"] or 0

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
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)

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
        o.id as op_id,
        o.data as data_op,
        m.setor,
        m.colaborador
    FROM apontamentos_mao_obra m
    JOIN ordens_producao o ON o.id = m.op_id
    WHERE o.data BETWEEN ? AND ?
      AND m.setor <> 'Expedição'
      {status_condicao_alias}
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)

    mao_obra_periodo = cursor.fetchall()

    colaboradores_por_op_setor = {}

    for item in mao_obra_periodo:
        setor = item["setor"]

        if setor not in setores_produtivos:
            continue

        op_id = item["op_id"]
        nome = (item["colaborador"] or "").strip().lower()

        if not nome:
            continue

        chave = (op_id, setor)
        colaboradores_por_op_setor.setdefault(chave, set()).add(nome)

    hh_total = 0
    hh_por_setor = {setor: 0 for setor in setores_produtivos}
    colaboradores_medio_por_setor = {setor: 0 for setor in setores_produtivos}
    contagens_por_setor = {setor: [] for setor in setores_produtivos}
    mao_obra_direta_por_op = {}

    data_por_op = {
        op["id"]: op["data"]
        for op in ordens_periodo
    }

    for (op_id, setor), colaboradores in colaboradores_por_op_setor.items():
        data_op = data_por_op.get(op_id)
        horas_perdidas_setor_dia = horas_perdidas_por_data_setor.get((data_op, setor), 0)
        horas_uteis_setor_dia = max(0, jornada_padrao - horas_perdidas_setor_dia)
        quantidade_colaboradores = len(colaboradores)

        hh = quantidade_colaboradores * horas_uteis_setor_dia

        hh_por_setor[setor] += hh
        hh_total += hh

        contagens_por_setor[setor].append(quantidade_colaboradores)
        mao_obra_direta_por_op[op_id] = mao_obra_direta_por_op.get(op_id, 0) + quantidade_colaboradores

    for setor in setores_produtivos:
        contagens = contagens_por_setor.get(setor, [])

        if contagens:
            colaboradores_medio_por_setor[setor] = sum(contagens) / len(contagens)

    mao_obra_direta_media = 0

    if mao_obra_direta_por_op:
        mao_obra_direta_media = (
            sum(mao_obra_direta_por_op.values()) / len(mao_obra_direta_por_op)
        )

    viabilidade = aves_recebidas - mortes_antes_pendura - descartes_aves
    viabilidade_percentual = 0

    if aves_recebidas > 0:
        viabilidade_percentual = (viabilidade / aves_recebidas) * 100

    rendimento = 0
    if peso_entrada > 0:
        rendimento = (kg_produzidos / peso_entrada) * 100

    meta_viabilidade = 99.5
    meta_rendimento = 63.0

    variacao_viabilidade = viabilidade_percentual - meta_viabilidade
    variacao_rendimento = rendimento - meta_rendimento

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
            "colaboradores": round(colaboradores_medio_por_setor.get(setor, 0), 2),
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
        sku_filtro=sku_filtro,
        mostrar_indicadores_kg=(sku_filtro == "Galinha Cortada"),
        mostrar_indicadores_unidade=(sku_filtro == "Galinha Inteira"),
        aves_recebidas=round(aves_recebidas, 2),
        aves_abatidas=round(aves_abatidas, 2),
        viabilidade=round(viabilidade, 2),
        viabilidade_percentual=round(viabilidade_percentual, 2),
        peso_entrada=round(peso_entrada, 2),
        kg_produzidos=round(kg_produzidos, 2),
        unidades_produzidas=round(unidades_produzidas, 2),
        rendimento=round(rendimento, 2),
        meta_viabilidade=round(meta_viabilidade, 2),
        meta_rendimento=round(meta_rendimento, 2),
        variacao_viabilidade=round(variacao_viabilidade, 2),
        variacao_rendimento=round(variacao_rendimento, 2),
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
        mao_obra_direta_media=round(mao_obra_direta_media, 2),
        produtividade_hh=round(produtividade_hh, 2),
        aves_hora_fabrica=round(aves_hora_fabrica, 2),
        descartes_por_setor=descartes_por_setor,
        produtividade_setores=produtividade_setores,
        produtividade_setores_hora=produtividade_setores_hora
    )






@app.route("/dre-gerencial")
@perfil_permitido("pcp")
def dre_gerencial():
    criar_banco()
    criar_tabelas_custos()
    criar_tabela_vendas()

    competencia = request.args.get("competencia") or datetime.now().strftime("%Y-%m")
    dados = buscar_dados_dre_gerencial(competencia)

    return render_template(
        "dre_gerencial.html",
        competencia=competencia,
        receita_bruta=dados["receita_bruta"],
        vendas_por_sku=dados["vendas_por_sku"],
        cmv_total=dados["cmv_total"],
        cmv_percentual=dados["cmv_percentual"],
        cmv_por_sku=dados["cmv_por_sku"],
        margem_bruta=dados["margem_bruta"],
        margem_bruta_percentual=dados["margem_bruta_percentual"],
        custos_operacionais_total=dados["custos_operacionais_total"],
        custos_operacionais_percentual=dados["custos_operacionais_percentual"],
        linhas_custos=dados["linhas_custos"],
        resultado_operacional=dados["resultado_operacional"],
        margem_operacional_percentual=dados["margem_operacional_percentual"]
    )



@app.route("/relatorio-custos")
@perfil_permitido("pcp")
def relatorio_custos():
    criar_banco()
    criar_tabelas_custos()

    agora = datetime.now()
    competencia_fim = request.args.get("competencia_fim") or agora.strftime("%Y-%m")

    seis_meses_atras = agora

    for _ in range(5):
        if seis_meses_atras.month == 1:
            seis_meses_atras = seis_meses_atras.replace(
                year=seis_meses_atras.year - 1,
                month=12
            )
        else:
            seis_meses_atras = seis_meses_atras.replace(
                month=seis_meses_atras.month - 1
            )

    competencia_inicio = (
        request.args.get("competencia_inicio")
        or seis_meses_atras.strftime("%Y-%m")
    )

    if competencia_inicio > competencia_fim:
        competencia_inicio, competencia_fim = competencia_fim, competencia_inicio

    dados = buscar_dados_relatorio_custos(
        competencia_inicio,
        competencia_fim
    )

    return render_template(
        "relatorio_custos.html",
        competencia_inicio=competencia_inicio,
        competencia_fim=competencia_fim,
        competencias=dados["competencias"],
        datasets=dados["datasets"],
        custo_total=dados["custo_total"],
        media_mensal=dados["media_mensal"],
        maior_categoria=dados["maior_categoria"],
        valor_maior_categoria=dados["valor_maior_categoria"],
        maior_crescimento_categoria=dados["maior_crescimento_categoria"],
        maior_crescimento_valor=dados["maior_crescimento_valor"],
        resumo_categorias=dados["resumo_categorias"]
    )



@app.route("/custos", methods=["GET", "POST"])
@perfil_permitido("pcp")
def custos():
    criar_banco()
    criar_tabelas_custos()

    if request.method == "POST":
        acao = request.form.get("acao")

        try:
            if acao == "salvar_parametros":
                salvar_parametros_custos(request.form)
                flash("Parâmetros de CMV atualizados com sucesso.")

            elif acao == "salvar_custo_mensal":
                salvar_custo_mensal(request.form)
                flash("Custo mensal cadastrado com sucesso.")

        except ValueError:
            flash("Verifique os valores informados. Use apenas números nos campos de custo.")

        return redirect(url_for("custos"))

    categorias_custos = CATEGORIAS_CUSTOS

    competencia_atual = datetime.now().strftime("%Y-%m")

    return render_template(
        "custos.html",
        parametros=buscar_parametros_custos(),
        custos_mensais=buscar_custos_mensais(),
        categorias_custos=categorias_custos,
        competencia_atual=competencia_atual
    )




@app.route("/vendas", methods=["GET", "POST"])
@perfil_permitido("pcp")
def vendas():
    criar_banco()
    criar_tabela_vendas()

    if request.method == "POST":
        try:
            salvar_venda_diaria(request.form)
            flash("Venda diária cadastrada com sucesso.")
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("vendas"))

    hoje = datetime.now().strftime("%Y-%m-%d")

    return render_template(
        "vendas.html",
        hoje=hoje,
        vendas_diarias=buscar_vendas_diarias()
    )



@app.route("/custos/mensal/<int:custo_id>/editar", methods=["GET", "POST"])
@perfil_permitido("pcp")
def editar_custo_mensal(custo_id):
    criar_banco()
    criar_tabelas_custos()

    custo = buscar_custo_mensal_por_id(custo_id)

    if not custo:
        flash("Custo mensal não encontrado.")
        return redirect(url_for("custos"))

    categorias_custos = CATEGORIAS_CUSTOS

    if request.method == "POST":
        try:
            conn = conectar()
            cursor = conn.cursor()
            cursor.execute(q("""
            UPDATE custos_mensais
            SET competencia = ?,
                categoria = ?,
                valor = ?,
                observacoes = ?
            WHERE id = ?
            """), (
                request.form["competencia"],
                request.form["categoria"],
                float(request.form["valor"]),
                request.form.get("observacoes", ""),
                custo_id
            ))
            conn.commit()
            conn.close()
            flash("Custo mensal atualizado com sucesso.")
            return redirect(url_for("custos"))
        except ValueError:
            flash("Verifique o valor informado. Use apenas números no campo de valor.")

    return render_template(
        "editar_custo_mensal.html",
        custo=custo,
        categorias_custos=categorias_custos
    )


@app.route("/custos/mensal/<int:custo_id>/excluir", methods=["POST"])
@perfil_permitido("pcp")
def excluir_custo_mensal(custo_id):
    criar_banco()
    criar_tabelas_custos()

    if not buscar_custo_mensal_por_id(custo_id):
        flash("Custo mensal não encontrado.")
        return redirect(url_for("custos"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    DELETE FROM custos_mensais
    WHERE id = ?
    """), (custo_id,))
    conn.commit()
    conn.close()

    flash("Custo mensal excluído com sucesso.")
    return redirect(url_for("custos"))


@app.route("/vendas/<int:venda_id>/editar", methods=["GET", "POST"])
@perfil_permitido("pcp")
def editar_venda_diaria(venda_id):
    criar_banco()
    criar_tabela_vendas()

    venda = buscar_venda_diaria_por_id(venda_id)

    if not venda:
        flash("Venda diária não encontrada.")
        return redirect(url_for("vendas"))

    if request.method == "POST":
        try:
            sku = request.form["sku"]
            quantidade = float(request.form["quantidade"])
            receita = float(request.form["receita"])

            if quantidade <= 0:
                raise ValueError("A quantidade vendida deve ser maior que zero.")

            if receita < 0:
                raise ValueError("A receita não pode ser negativa.")

            unidade = "kg" if sku == "Galinha Cortada" else "unidades"

            conn = conectar()
            cursor = conn.cursor()
            cursor.execute(q("""
            UPDATE vendas_diarias
            SET data = ?,
                sku = ?,
                quantidade = ?,
                unidade = ?,
                receita = ?,
                observacoes = ?
            WHERE id = ?
            """), (
                request.form["data"],
                sku,
                quantidade,
                unidade,
                receita,
                request.form.get("observacoes", ""),
                venda_id
            ))
            conn.commit()
            conn.close()

            flash("Venda diária atualizada com sucesso.")
            return redirect(url_for("vendas"))
        except ValueError as erro:
            flash(str(erro))

    return render_template("editar_venda_diaria.html", venda=venda)


@app.route("/vendas/<int:venda_id>/excluir", methods=["POST"])
@perfil_permitido("pcp")
def excluir_venda_diaria(venda_id):
    criar_banco()
    criar_tabela_vendas()

    if not buscar_venda_diaria_por_id(venda_id):
        flash("Venda diária não encontrada.")
        return redirect(url_for("vendas"))

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    DELETE FROM vendas_diarias
    WHERE id = ?
    """), (venda_id,))
    conn.commit()
    conn.close()

    flash("Venda diária excluída com sucesso.")
    return redirect(url_for("vendas"))


@app.route("/fornecedores", methods=["GET", "POST"])
@perfil_permitido("pcp")
def fornecedores():
    criar_banco()
    criar_tabela_fornecedores()

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

        conn.close()
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
        tipo = request.form.get("tipo_apontamento")

        try:
            if tipo == "copiar_mao_obra":
                origem_op_id = request.form["origem_op_id"]
                destino_op_id = request.form["destino_op_id"]
                data_destino = request.form["data_destino"]

                total = copiar_mao_obra_de_op(
                    origem_op_id,
                    destino_op_id,
                    data_destino
                )

                flash(f"Equipe copiada com sucesso. {total} colaboradores foram lançados na OP destino.")

            else:
                salvar_apontamento_mao_obra(request.form)
                flash("Apontamento de mão de obra salvo.")

        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("apontamento_mao_obra"))

    contexto = contexto_apontamento()
    contexto["ordens_origem"] = buscar_ordens()

    return render_template(
        "apontamento_mao_obra.html",
        **contexto
    )

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




@app.route("/tempos-setor", methods=["GET", "POST"])
@perfil_permitido("producao")
def tempos_setor():
    criar_banco()
    criar_tabela_tempos_setor()

    if request.method == "POST":
        try:
            salvar_tempos_setor(request.form)
            flash("Tempos dos setores salvos com sucesso.")
        except ValueError as erro:
            flash(str(erro))

        return redirect(url_for("tempos_setor", op_id=request.form.get("op_id")))

    op_id = request.args.get("op_id")
    op = None
    tempos_salvos = []
    setores_op = []

    if op_id:
        op = buscar_op_por_id(op_id)

        if op:
            setores_op = setores_por_sku(op["sku"] or "Galinha Cortada")
            tempos_salvos = buscar_tempos_setor_por_op(op_id)

    tempos_por_setor = {
        item["setor"]: item
        for item in tempos_salvos
    }

    return render_template(
        "tempos_setor.html",
        hoje=datetime.now().strftime("%Y-%m-%d"),
        ordens=buscar_ordens_abertas(),
        op=op,
        setores_op=setores_op,
        tempos_por_setor=tempos_por_setor,
        normalizar_chave_setor=normalizar_chave_setor
    )


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
        "Setup / Troca de Produto",
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
        "Setup / Troca de Produto",
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
        "apontamentos_descartes",
        "apontamentos_tempos_setor"
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
    op = buscar_op_por_id(op_id)

    if not op:
        flash("OP não encontrada.")
        return redirect(url_for("consultar_op"))

    if op["status"] == "Encerrada":
        flash("Esta OP já está encerrada.")
        return redirect(url_for("consultar_op", op_id=op_id))

    try:
        hora_inicio = request.form["hora_inicio"]
        hora_fim = request.form["hora_fim"]
        unidades_produzidas = float(request.form["unidades_produzidas"])
        kg_produzidos_raw = request.form.get("kg_produzidos", "")
        descontar_almoco = request.form.get("descontar_almoco") == "sim"

        kg_produzidos = None
        if (op["sku"] or "Galinha Cortada") == "Galinha Cortada":
            if not kg_produzidos_raw:
                raise ValueError("Informe o kg produzido para Galinha Cortada.")
            kg_produzidos = float(kg_produzidos_raw)

        gerar_producao_automatica_setores(
            op=op,
            data_lancamento=op["data"],
            hora_inicio=hora_inicio,
            hora_fim=hora_fim,
            unidades_produzidas=unidades_produzidas,
            kg_produzidos=kg_produzidos,
            descontar_almoco=descontar_almoco
        )

        conn = conectar()
        cursor = conn.cursor()

        cursor.execute(q("""
        UPDATE ordens_producao
        SET status = ?
        WHERE id = ?
        """), ("Encerrada", op_id))

        conn.commit()
        conn.close()

        flash("OP encerrada com sucesso. A produção foi gerada automaticamente.")

    except ValueError as erro:
        flash(str(erro))

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
    criar_tabela_tempos_setor()

    op_id = request.args.get("op_id")
    ordens = buscar_ordens()

    op = None
    producoes = []
    mao_obra = []
    paradas = []
    descartes = []
    tempos_setor = []
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

        cursor.execute(q("SELECT * FROM apontamentos_tempos_setor WHERE op_id = ? ORDER BY id ASC"), (op_id,))
        tempos_setor = cursor.fetchall()

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
        tempos_setor=tempos_setor,
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
    criar_banco()

    agora = datetime.now()
    hoje = agora.strftime("%Y-%m-%d")
    primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

    data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
    data_fim = request.args.get("data_fim") or hoje
    fornecedor_filtro = request.args.get("fornecedor") or "Todos"
    sku_filtro = request.args.get("sku") or "Todos"
    status_filtro = request.args.get("status") or "Encerrada"

    jornada_padrao = 8.8
    setores_produtivos = ["Recepção e Pendura", "Escalda e Depenagem", "Evisceração", "Corte", "Embalagem"]

    cond_op = ["data BETWEEN ? AND ?"]
    params_op = [data_inicio, data_fim]
    cond_alias = ["o.data BETWEEN ? AND ?"]
    params_alias = [data_inicio, data_fim]

    if fornecedor_filtro != "Todos":
        cond_op.append("fornecedor = ?")
        params_op.append(fornecedor_filtro)
        cond_alias.append("o.fornecedor = ?")
        params_alias.append(fornecedor_filtro)

    if sku_filtro != "Todos":
        cond_op.append("COALESCE(sku, 'Galinha Cortada') = ?")
        params_op.append(sku_filtro)
        cond_alias.append("COALESCE(o.sku, 'Galinha Cortada') = ?")
        params_alias.append(sku_filtro)

    if status_filtro != "Todas":
        cond_op.append("COALESCE(status, 'Aberta') = ?")
        params_op.append(status_filtro)
        cond_alias.append("COALESCE(o.status, 'Aberta') = ?")
        params_alias.append(status_filtro)

    where_op = " AND ".join(cond_op)
    where_alias = " AND ".join(cond_alias)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT *
    FROM ordens_producao
    WHERE {where_op}
    ORDER BY data ASC, id ASC
    """), tuple(params_op))
    ordens_periodo = cursor.fetchall()

    datas_periodo = sorted({op["data"] for op in ordens_periodo})
    dias_periodo = len(datas_periodo)
    horas_programadas = jornada_padrao * dias_periodo

    aves_recebidas = sum(op["quantidade_aves"] or 0 for op in ordens_periodo)
    mortes_antes_pendura = sum(op["mortes_antes_pendura"] or 0 for op in ordens_periodo)
    peso_entrada = sum(op["peso_vivo"] or 0 for op in ordens_periodo)
    aves_abatidas = aves_recebidas - mortes_antes_pendura

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(p.quantidade), 0) as total
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE {where_alias}
      AND LOWER(p.unidade) = 'kg'
    """), tuple(params_alias))
    kg_produzidos = cursor.fetchone()["total"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(d.quantidade), 0) as total
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE {where_alias}
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
    """), tuple(params_alias))
    descartes_aves = cursor.fetchone()["total"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(d.quantidade), 0) as total
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE {where_alias}
      AND LOWER(d.unidade) = 'kg'
    """), tuple(params_alias))
    descartes_kg = cursor.fetchone()["total"] or 0

    total_problemas_aves = mortes_antes_pendura + descartes_aves
    viabilidade = aves_recebidas - total_problemas_aves
    viabilidade_percentual = (viabilidade / aves_recebidas * 100) if aves_recebidas > 0 else 0
    rendimento = (kg_produzidos / peso_entrada * 100) if peso_entrada > 0 else 0

    cursor.execute(q(f"""
    SELECT p.evento_id, p.op_id, o.data as data_op, p.data as data_apontamento,
           p.setor, p.motivo, p.horas_paradas, p.observacoes
    FROM apontamentos_paradas p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE {where_alias}
      AND p.setor <> 'Expedição'
    """), tuple(params_alias))
    paradas = cursor.fetchall()

    eventos_parada_unicos = {}
    horas_perdidas_por_data_setor = {}
    for parada in paradas:
        horas = float(parada["horas_paradas"] or 0)
        data_base = parada["data_op"] or parada["data_apontamento"]
        setor = parada["setor"]
        chave_data_setor = (data_base, setor)
        horas_perdidas_por_data_setor[chave_data_setor] = horas_perdidas_por_data_setor.get(chave_data_setor, 0) + horas
        chave_evento = parada["evento_id"] or (parada["op_id"], data_base, parada["motivo"], round(horas, 4), parada["observacoes"] or "")
        eventos_parada_unicos[chave_evento] = horas

    horas_perdidas_total = sum(eventos_parada_unicos.values())
    horas_uteis_total = max(0, horas_programadas - horas_perdidas_total)
    percentual_jornada_perdida = (horas_perdidas_total / horas_programadas * 100) if horas_programadas > 0 else 0

    cursor.execute(q(f"""
    SELECT o.data as data_op, m.setor, m.colaborador
    FROM apontamentos_mao_obra m
    JOIN ordens_producao o ON o.id = m.op_id
    WHERE {where_alias}
      AND m.setor <> 'Expedição'
    """), tuple(params_alias))
    mao_obra = cursor.fetchall()

    colaboradores_por_data_setor = {}
    for item in mao_obra:
        setor = item["setor"]
        if setor not in setores_produtivos:
            continue
        nome = (item["colaborador"] or "").strip().lower()
        if nome:
            colaboradores_por_data_setor.setdefault((item["data_op"], setor), set()).add(nome)

    hh_total = 0
    for (data_op, setor), colaboradores in colaboradores_por_data_setor.items():
        horas_perdidas = horas_perdidas_por_data_setor.get((data_op, setor), 0)
        hh_total += len(colaboradores) * max(0, jornada_padrao - horas_perdidas)

    produtividade_hh = (viabilidade / hh_total) if hh_total > 0 else 0
    aves_hora_fabrica = (viabilidade / horas_uteis_total) if horas_uteis_total > 0 else 0

    cursor.execute(q(f"""
    SELECT d.setor, COALESCE(SUM(d.quantidade), 0) as quantidade
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE {where_alias}
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
    GROUP BY d.setor
    ORDER BY quantidade DESC
    """), tuple(params_alias))
    descartes_por_setor = cursor.fetchall()

    cursor.execute(q(f"""
    SELECT p.motivo, COALESCE(SUM(p.horas_paradas), 0) as horas
    FROM apontamentos_paradas p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE {where_alias}
      AND p.setor <> 'Expedição'
    GROUP BY p.motivo
    ORDER BY horas DESC
    """), tuple(params_alias))
    paradas_por_motivo = cursor.fetchall()

    linhas_op = []
    for op in ordens_periodo:
        op_id = op["id"]
        cursor.execute(q("""
        SELECT COALESCE(SUM(quantidade), 0) as total
        FROM apontamentos_producao
        WHERE op_id = ? AND LOWER(unidade) = 'kg'
        """), (op_id,))
        kg_op = cursor.fetchone()["total"] or 0

        cursor.execute(q("""
        SELECT COALESCE(SUM(quantidade), 0) as total
        FROM apontamentos_descartes
        WHERE op_id = ? AND LOWER(unidade) IN ('aves', 'ave', 'unidade', 'unidades')
        """), (op_id,))
        descartes_op = cursor.fetchone()["total"] or 0

        cursor.execute(q("""
        SELECT COALESCE(SUM(quantidade), 0) as total
        FROM apontamentos_descartes
        WHERE op_id = ? AND LOWER(unidade) = 'kg'
        """), (op_id,))
        perdas_kg_op = cursor.fetchone()["total"] or 0

        aves_op = op["quantidade_aves"] or 0
        mortes_op = op["mortes_antes_pendura"] or 0
        peso_op = op["peso_vivo"] or 0
        viabilidade_op = aves_op - mortes_op - descartes_op
        linhas_op.append({
            "id": op["id"],
            "data": op["data"],
            "fornecedor": op["fornecedor"],
            "sku": op["sku"] or "Galinha Cortada",
            "status": op["status"] or "Aberta",
            "aves_recebidas": round(aves_op, 2),
            "mortes": round(mortes_op, 2),
            "descartes": round(descartes_op, 2),
            "perdas_kg": round(perdas_kg_op, 2),
            "kg_produzidos": round(kg_op, 2),
            "rendimento": round((kg_op / peso_op * 100) if peso_op > 0 else 0, 2),
            "viabilidade_percentual": round((viabilidade_op / aves_op * 100) if aves_op > 0 else 0, 2)
        })


    # ================================
    # RELATÓRIO DE MÃO DE OBRA
    # ================================

    colaboradores_distintos = set()
    registros_por_setor = {}
    colaboradores_por_setor_distintos = {}
    registros_por_funcao = {}
    colaboradores_por_funcao_distintos = {}
    registros_por_colaborador = {}
    ops_por_colaborador = {}

    for item in mao_obra:
        nome_original = (item["colaborador"] or "").strip()
        nome = nome_original.lower()
        setor = item["setor"] or "Não informado"

        if not nome:
            continue

        colaboradores_distintos.add(nome)

        registros_por_setor[setor] = registros_por_setor.get(setor, 0) + 1
        colaboradores_por_setor_distintos.setdefault(setor, set()).add(nome)

        registros_por_colaborador[nome_original] = registros_por_colaborador.get(nome_original, 0) + 1

    cursor.execute(q(f"""
    SELECT
        m.colaborador,
        m.funcao,
        m.setor,
        m.op_id
    FROM apontamentos_mao_obra m
    JOIN ordens_producao o ON o.id = m.op_id
    WHERE {where_alias}
      AND m.setor <> 'Expedição'
    """), tuple(params_alias))

    mao_obra_detalhada = cursor.fetchall()

    for item in mao_obra_detalhada:
        nome_original = (item["colaborador"] or "").strip()
        nome = nome_original.lower()
        funcao = item["funcao"] or "Não informada"

        if not nome:
            continue

        registros_por_funcao[funcao] = registros_por_funcao.get(funcao, 0) + 1
        colaboradores_por_funcao_distintos.setdefault(funcao, set()).add(nome)
        ops_por_colaborador.setdefault(nome_original, set()).add(item["op_id"])

    mao_obra_por_setor = []

    for setor in setores_produtivos:
        hh_setor = 0

        for (data_op, setor_base), colaboradores in colaboradores_por_data_setor.items():
            if setor_base != setor:
                continue

            horas_perdidas = horas_perdidas_por_data_setor.get((data_op, setor_base), 0)
            horas_uteis = max(0, jornada_padrao - horas_perdidas)
            hh_setor += len(colaboradores) * horas_uteis

        percentual_hh = (hh_setor / hh_total * 100) if hh_total > 0 else 0

        mao_obra_por_setor.append({
            "setor": setor,
            "registros": registros_por_setor.get(setor, 0),
            "colaboradores": len(colaboradores_por_setor_distintos.get(setor, set())),
            "hh": round(hh_setor, 2),
            "percentual_hh": round(percentual_hh, 2)
        })

    mao_obra_por_funcao = []

    for funcao, registros in registros_por_funcao.items():
        mao_obra_por_funcao.append({
            "funcao": funcao,
            "registros": registros,
            "colaboradores": len(colaboradores_por_funcao_distintos.get(funcao, set()))
        })

    mao_obra_por_funcao = sorted(
        mao_obra_por_funcao,
        key=lambda item: item["registros"],
        reverse=True
    )

    colaboradores_mais_utilizados = []

    for colaborador, registros in registros_por_colaborador.items():
        colaboradores_mais_utilizados.append({
            "colaborador": colaborador,
            "registros": registros,
            "ops": len(ops_por_colaborador.get(colaborador, set()))
        })

    colaboradores_mais_utilizados = sorted(
        colaboradores_mais_utilizados,
        key=lambda item: item["registros"],
        reverse=True
    )

    kg_por_hh = (kg_produzidos / hh_total) if hh_total > 0 else 0
    total_colaboradores_distintos = len(colaboradores_distintos)


    conn.close()

    return render_template(
        "relatorio.html",
        data_inicio=data_inicio,
        data_fim=data_fim,
        fornecedor_filtro=fornecedor_filtro,
        sku_filtro=sku_filtro,
        status_filtro=status_filtro,
        fornecedores=buscar_fornecedores(),
        skus=["Galinha Inteira", "Galinha Cortada"],
        total_ops=len(ordens_periodo),
        dias_periodo=dias_periodo,
        aves_recebidas=round(aves_recebidas, 2),
        aves_abatidas=round(aves_abatidas, 2),
        mortes_antes_pendura=round(mortes_antes_pendura, 2),
        descartes_aves=round(descartes_aves, 2),
        descartes_kg=round(descartes_kg, 2),
        total_problemas_aves=round(total_problemas_aves, 2),
        viabilidade=round(viabilidade, 2),
        viabilidade_percentual=round(viabilidade_percentual, 2),
        peso_entrada=round(peso_entrada, 2),
        kg_produzidos=round(kg_produzidos, 2),
        rendimento=round(rendimento, 2),
        horas_programadas=round(horas_programadas, 2),
        horas_perdidas_total=round(horas_perdidas_total, 2),
        percentual_jornada_perdida=round(percentual_jornada_perdida, 2),
        horas_uteis_total=round(horas_uteis_total, 2),
        hh_total=round(hh_total, 2),
        produtividade_hh=round(produtividade_hh, 2),
        aves_hora_fabrica=round(aves_hora_fabrica, 2),
        descartes_por_setor=descartes_por_setor,
        paradas_por_motivo=paradas_por_motivo,
        linhas_op=linhas_op
    )



if __name__ == "__main__":
    criar_banco()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
