from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import calendar
from io import BytesIO
from urllib.parse import urlparse
import os
import uuid
import sqlite3
import psycopg2
import psycopg2.extras
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from auth import login_obrigatorio, destino_por_perfil, perfil_permitido
from utils import calcular_horas_programadas, calcular_produtividade, setores_padrao, normalizar_chave_setor

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "segredo")


# ============================================================
# FORMATAÇÃO BR / APRESENTAÇÃO EXECUTIVA
# ============================================================

def formatar_numero_br(valor, casas=2):
    try:
        numero = float(valor or 0)
    except Exception:
        numero = 0

    texto = f"{numero:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_moeda_br(valor):
    return f"R$ {formatar_numero_br(valor, 2)}"


def formatar_percentual_br(valor):
    return f"{formatar_numero_br(valor, 2)}%"


@app.template_filter("br_numero")
def filtro_br_numero(valor, casas=2):
    return formatar_numero_br(valor, int(casas))


@app.template_filter("br_moeda")
def filtro_br_moeda(valor):
    return formatar_moeda_br(valor)


@app.template_filter("br_percentual")
def filtro_br_percentual(valor):
    return formatar_percentual_br(valor)


def preparar_grafico_despesas_operacionais(linhas_custos, receita_bruta, limite=6):
    """
    Prepara os dados visuais do gráfico de rosca da DRE.
    O tamanho das fatias usa participação dentro das despesas operacionais.
    O rótulo exibido usa % da receita, para manter leitura gerencial.
    """
    itens_validos = [
        {
            "categoria": item["categoria"],
            "valor": float(item["valor"] or 0),
            "percentual_receita": float(item["percentual"] or 0)
        }
        for item in linhas_custos
        if float(item["valor"] or 0) > 0
    ]

    itens_validos = sorted(itens_validos, key=lambda item: item["valor"], reverse=True)
    total_despesas = sum(item["valor"] for item in itens_validos)

    if total_despesas <= 0:
        return {
            "itens": [],
            "gradiente": "#e5e7eb 0deg 360deg",
            "total": 0,
            "percentual_receita_total": 0
        }

    cores = [
        "#2563eb",
        "#16a34a",
        "#f97316",
        "#8b5cf6",
        "#0891b2",
        "#64748b",
        "#dc2626"
    ]

    limite_principal = max(1, limite - 1)
    principais = itens_validos[:limite_principal]
    restantes = itens_validos[limite_principal:]

    itens_grafico = []

    for item in principais:
        itens_grafico.append(item)

    if restantes:
        valor_outras = sum(item["valor"] for item in restantes)
        percentual_receita_outras = sum(item["percentual_receita"] for item in restantes)
        itens_grafico.append({
            "categoria": f"Outras categorias ({len(restantes)})",
            "valor": valor_outras,
            "percentual_receita": percentual_receita_outras
        })

    segmentos = []
    angulo_atual = 0
    itens_saida = []

    for indice, item in enumerate(itens_grafico):
        fatia = item["valor"] / total_despesas
        graus = fatia * 360
        inicio = angulo_atual
        fim = 360 if indice == len(itens_grafico) - 1 else angulo_atual + graus
        meio = (inicio + fim) / 2
        cor = cores[indice % len(cores)]
        segmentos.append(f"{cor} {inicio:.2f}deg {fim:.2f}deg")

        # Coordenadas dos rótulos ao redor da rosca.
        # Regra visual validada: só exibimos rótulos externos para categorias
        # com pelo menos 5% da receita. As demais continuam na tabela lateral.
        #
        # Também limitamos a distância dos rótulos para impedir invasão da tabela
        # lateral e evitar balões excessivamente afastados do gráfico.
        import math
        rad = math.radians(meio - 90)
        x = 50 + (32 * math.cos(rad))
        y = 50 + (31 * math.sin(rad))
        x = max(28, min(72, x))
        y = max(22, min(78, y))
        alinhamento = "right" if x < 50 else "left"
        mostrar_rotulo = float(item["percentual_receita"] or 0) >= 5

        itens_saida.append({
            "categoria": item["categoria"],
            "valor": round(item["valor"], 2),
            "valor_formatado": formatar_moeda_br(item["valor"]),
            "percentual_receita": round(item["percentual_receita"], 2),
            "percentual_receita_formatado": formatar_percentual_br(item["percentual_receita"]),
            "percentual_despesa": round(fatia * 100, 2),
            "percentual_despesa_formatado": formatar_percentual_br(fatia * 100),
            "cor": cor,
            "x": round(x, 2),
            "y": round(y, 2),
            "alinhamento": alinhamento,
            "mostrar_rotulo": mostrar_rotulo
        })

        angulo_atual = fim

    return {
        "itens": itens_saida,
        "gradiente": ", ".join(segmentos),
        "total": round(total_despesas, 2),
        "total_formatado": formatar_moeda_br(total_despesas),
        "percentual_receita_total": round((total_despesas / receita_bruta * 100) if receita_bruta > 0 else 0, 2),
        "percentual_receita_total_formatado": formatar_percentual_br((total_despesas / receita_bruta * 100) if receita_bruta > 0 else 0)
    }


def preparar_linhas_custos_executivas(linhas_custos, limite=6):
    itens = [item for item in linhas_custos if float(item["valor"] or 0) > 0]
    itens = sorted(itens, key=lambda item: float(item["valor"] or 0), reverse=True)

    if len(itens) <= limite:
        return itens

    principais = itens[:limite - 1]
    restantes = itens[limite - 1:]
    principais.append({
        "categoria": f"Outras categorias ({len(restantes)})",
        "valor": round(sum(float(item["valor"] or 0) for item in restantes), 2),
        "percentual": round(sum(float(item["percentual"] or 0) for item in restantes), 2)
    })
    return principais

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
    "Manutenção de Veículos",

    "Material de Limpeza",
    "Material de Escritório",
    "Serviços",

    "EPIs",

    "Marketing",
    "Cursos e Treinamentos",
    "Despesas com Viagens",

    "Consultoria e Responsabilidade Técnica",

    "Contratos com Clientes",

    "Insumos para Produção",

    "Impostos e Taxas",

    "Despesas Financeiras",


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
        ("Galinha Cortada", 0, "R$/ave", 0, "R$/bandeja"),
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
            unidade_custo_ave = "R$/ave"
            unidade_custo_embalagem = "R$/bandeja"
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
            quantidade_unidades REAL DEFAULT 0,
            quantidade_kg REAL DEFAULT 0,
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
            quantidade_unidades REAL DEFAULT 0,
            quantidade_kg REAL DEFAULT 0,
            receita REAL NOT NULL,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    tentar_alter_table(cursor, conn, "ALTER TABLE vendas_diarias ADD COLUMN quantidade_unidades REAL DEFAULT 0")
    tentar_alter_table(cursor, conn, "ALTER TABLE vendas_diarias ADD COLUMN quantidade_kg REAL DEFAULT 0")

    conn.commit()
    conn.close()



def preparar_quantidades_venda(sku, form, quantidade_atual=None, unidade_atual=None):
    """
    Padroniza as quantidades de venda para suportar a lógica correta da DRE.

    Galinha Cortada:
    - quantidade_unidades = bandejas vendidas, usada para CMV;
    - quantidade_kg = kg vendidos, usado para receita/kg e CMV/kg;
    - quantidade legado = kg, para compatibilidade com telas antigas.

    Galinha Inteira:
    - quantidade_unidades = unidades vendidas;
    - quantidade_kg = 0;
    - quantidade legado = unidades.
    """
    quantidade_legacy = form.get("quantidade")
    quantidade_unidades_raw = (
        form.get("quantidade_unidades")
        or form.get("unidades_vendidas")
        or form.get("bandejas_vendidas")
        or ""
    )
    quantidade_kg_raw = (
        form.get("quantidade_kg")
        or form.get("kg_vendidos")
        or ""
    )

    if sku == "Galinha Cortada":
        quantidade_unidades = float(quantidade_unidades_raw or 0)
        quantidade_kg = float(quantidade_kg_raw or quantidade_legacy or quantidade_atual or 0)

        if quantidade_unidades <= 0:
            raise ValueError("Informe a quantidade de bandejas/unidades vendidas para Galinha Cortada.")

        if quantidade_kg <= 0:
            raise ValueError("Informe a quantidade em kg vendida para Galinha Cortada.")

        return {
            "quantidade": quantidade_kg,
            "unidade": "kg",
            "quantidade_unidades": quantidade_unidades,
            "quantidade_kg": quantidade_kg
        }

    quantidade_unidades = float(quantidade_unidades_raw or quantidade_legacy or quantidade_atual or 0)

    if quantidade_unidades <= 0:
        raise ValueError("Informe a quantidade de unidades vendidas.")

    return {
        "quantidade": quantidade_unidades,
        "unidade": "unidades",
        "quantidade_unidades": quantidade_unidades,
        "quantidade_kg": 0
    }


def buscar_venda_diaria_por_data_sku(data, sku, ignorar_id=None):
    """
    Busca lançamento de venda já existente para a mesma data e SKU.

    Regra de negócio:
    - A tela de Vendas Diárias registra a receita consolidada do dia por SKU.
    - Portanto, deve existir no máximo um lançamento para cada combinação Data + SKU.
    - Se o usuário precisar corrigir valores, deve editar o lançamento existente.
    """
    criar_tabela_vendas()

    conn = conectar()
    cursor = conn.cursor()

    if ignorar_id:
        cursor.execute(q("""
        SELECT *
        FROM vendas_diarias
        WHERE data = ?
          AND sku = ?
          AND id <> ?
        ORDER BY id DESC
        LIMIT 1
        """), (data, sku, ignorar_id))
    else:
        cursor.execute(q("""
        SELECT *
        FROM vendas_diarias
        WHERE data = ?
          AND sku = ?
        ORDER BY id DESC
        LIMIT 1
        """), (data, sku))

    venda = cursor.fetchone()
    conn.close()

    return venda


def salvar_venda_diaria(form):
    criar_tabela_vendas()

    data_venda = form["data"]
    sku = form["sku"]
    receita = float(form["receita"])

    if receita < 0:
        raise ValueError("A receita não pode ser negativa.")

    quantidades = preparar_quantidades_venda(sku, form)

    venda_existente = buscar_venda_diaria_por_data_sku(data_venda, sku)

    if venda_existente:
        raise ValueError(
            "Já existe uma venda lançada para esta data e SKU. "
            "Edite o lançamento existente em vez de cadastrar novamente."
        )

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO vendas_diarias (
        data,
        sku,
        quantidade,
        unidade,
        quantidade_unidades,
        quantidade_kg,
        receita,
        observacoes
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        data_venda,
        sku,
        quantidades["quantidade"],
        quantidades["unidade"],
        quantidades["quantidade_unidades"],
        quantidades["quantidade_kg"],
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



# ============================================================
# EXPEDIÇÃO - SPRINT 1.0
# ============================================================

def criar_tabelas_expedicao():
    """
    Cria a fundação do módulo de Expedição.

    Sprint 1.0:
    - Apenas estrutura, listagem e ponto de entrada no menu.
    - Não baixa estoque.
    - Não gera venda.
    - Não interfere na DRE nem no Financeiro.
    """
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicoes (
            id SERIAL PRIMARY KEY,
            numero_romaneio TEXT UNIQUE NOT NULL,
            data TEXT NOT NULL,
            tipo_movimentacao TEXT NOT NULL DEFAULT 'TRANSFERENCIA',
            destino TEXT NOT NULL,
            responsavel TEXT,
            observacoes TEXT,
            status TEXT NOT NULL DEFAULT 'Aberto',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicao_itens (
            id SERIAL PRIMARY KEY,
            expedicao_id INTEGER NOT NULL,
            op_id INTEGER,
            sku TEXT NOT NULL,
            quantidade_unidades REAL DEFAULT 0,
            quantidade_kg REAL DEFAULT 0,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_romaneio TEXT UNIQUE NOT NULL,
            data TEXT NOT NULL,
            tipo_movimentacao TEXT NOT NULL DEFAULT 'TRANSFERENCIA',
            destino TEXT NOT NULL,
            responsavel TEXT,
            observacoes TEXT,
            status TEXT NOT NULL DEFAULT 'Aberto',
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS expedicao_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expedicao_id INTEGER NOT NULL,
            op_id INTEGER,
            sku TEXT NOT NULL,
            quantidade_unidades REAL DEFAULT 0,
            quantidade_kg REAL DEFAULT 0,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()
    conn.close()


def buscar_expedicoes(data_inicio=None, data_fim=None, status=None):
    criar_tabelas_expedicao()

    filtros = []
    parametros = []

    if data_inicio:
        filtros.append("data >= ?")
        parametros.append(data_inicio)

    if data_fim:
        filtros.append("data <= ?")
        parametros.append(data_fim)

    if status and status != "Todos":
        filtros.append("status = ?")
        parametros.append(status)

    where = ""
    if filtros:
        where = "WHERE " + " AND ".join(filtros)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT
        e.*,
        COALESCE(COUNT(i.id), 0) as total_itens,
        COALESCE(SUM(i.quantidade_unidades), 0) as total_unidades,
        COALESCE(SUM(i.quantidade_kg), 0) as total_kg
    FROM expedicoes e
    LEFT JOIN expedicao_itens i ON i.expedicao_id = e.id
    {where}
    GROUP BY e.id, e.numero_romaneio, e.data, e.tipo_movimentacao, e.destino, e.responsavel, e.observacoes, e.status, e.criado_em
    ORDER BY e.data DESC, e.id DESC
    """), tuple(parametros))

    expedicoes = cursor.fetchall()
    conn.close()
    return expedicoes


def calcular_resumo_expedicao(expedicoes):
    total_romaneios = len(expedicoes)
    abertos = sum(1 for item in expedicoes if item["status"] == "Aberto")
    concluidos = sum(1 for item in expedicoes if item["status"] == "Concluído")
    cancelados = sum(1 for item in expedicoes if item["status"] == "Cancelado")

    total_unidades = sum(float(item["total_unidades"] or 0) for item in expedicoes)
    total_kg = sum(float(item["total_kg"] or 0) for item in expedicoes)

    return {
        "total_romaneios": total_romaneios,
        "abertos": abertos,
        "concluidos": concluidos,
        "cancelados": cancelados,
        "total_unidades": round(total_unidades, 2),
        "total_kg": round(total_kg, 2)
    }




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

    # Gráfico executivo: exibe apenas as 5 maiores categorias do período
    # e agrupa as demais em "Outras Categorias".
    categorias_com_movimento = [
        categoria
        for categoria, total in sorted(
            totais_por_categoria.items(),
            key=lambda item: item[1],
            reverse=True
        )
        if float(total or 0) > 0
    ]

    categorias_principais = categorias_com_movimento[:5]
    categorias_restantes = categorias_com_movimento[5:]

    datasets = []

    for categoria in categorias_principais:
        valores = dados_por_categoria.get(categoria, {})
        datasets.append({
            "label": categoria,
            "data": [
                round(valores.get(competencia, 0), 2)
                for competencia in competencias
            ]
        })

    if categorias_restantes:
        datasets.append({
            "label": f"Outras Categorias ({len(categorias_restantes)})",
            "data": [
                round(
                    sum(
                        dados_por_categoria.get(categoria, {}).get(competencia, 0)
                        for categoria in categorias_restantes
                    ),
                    2
                )
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




def valor_linha_venda(item, campo, padrao=0):
    try:
        valor = item[campo]
    except Exception:
        valor = padrao

    if valor is None:
        return padrao

    return float(valor or 0)


def normalizar_venda_para_dre(item):
    sku = item["sku"]
    quantidade = valor_linha_venda(item, "quantidade")
    unidade = (item["unidade"] or "").lower()
    quantidade_unidades = valor_linha_venda(item, "quantidade_unidades")
    quantidade_kg = valor_linha_venda(item, "quantidade_kg")
    receita = valor_linha_venda(item, "receita")

    # Compatibilidade com registros antigos: antes a Galinha Cortada era lançada só em kg.
    if sku == "Galinha Cortada":
        if quantidade_kg <= 0 and unidade == "kg":
            quantidade_kg = quantidade

        if quantidade_unidades <= 0 and unidade in ["unidades", "unidade", "aves", "ave"]:
            quantidade_unidades = quantidade
    else:
        if quantidade_unidades <= 0:
            quantidade_unidades = quantidade

        quantidade_kg = 0

    return {
        "sku": sku,
        "receita": receita,
        "quantidade": quantidade,
        "unidade": unidade,
        "quantidade_unidades": quantidade_unidades,
        "quantidade_kg": quantidade_kg
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
    SELECT *
    FROM vendas_diarias
    WHERE data BETWEEN ? AND ?
    ORDER BY sku ASC, data ASC, id ASC
    """), (data_inicio, data_fim))

    vendas_linhas = [normalizar_venda_para_dre(item) for item in cursor.fetchall()]

    vendas_por_sku_dict = {}
    receita_bruta = 0

    for item in vendas_linhas:
        sku = item["sku"]

        if sku not in vendas_por_sku_dict:
            vendas_por_sku_dict[sku] = {
                "receita": 0,
                "quantidade": 0,
                "quantidade_unidades": 0,
                "quantidade_kg": 0
            }

        vendas_por_sku_dict[sku]["receita"] += item["receita"]
        vendas_por_sku_dict[sku]["quantidade_unidades"] += item["quantidade_unidades"]
        vendas_por_sku_dict[sku]["quantidade_kg"] += item["quantidade_kg"]

        if sku == "Galinha Cortada":
            vendas_por_sku_dict[sku]["quantidade"] += item["quantidade_kg"]
        else:
            vendas_por_sku_dict[sku]["quantidade"] += item["quantidade_unidades"]

        receita_bruta += item["receita"]

    vendas_por_sku = []

    for sku, venda in vendas_por_sku_dict.items():
        quantidade_base = venda["quantidade_kg"] if sku == "Galinha Cortada" else venda["quantidade_unidades"]
        unidade_base = "kg" if sku == "Galinha Cortada" else "unidades"
        preco_medio = venda["receita"] / quantidade_base if quantidade_base > 0 else 0

        vendas_por_sku.append({
            "sku": sku,
            "receita": round(venda["receita"], 2),
            "quantidade": round(quantidade_base, 2),
            "unidade": unidade_base,
            "quantidade_unidades": round(venda["quantidade_unidades"], 2),
            "quantidade_kg": round(venda["quantidade_kg"], 2),
            "preco_medio": round(preco_medio, 4)
        })

    cursor.execute("SELECT * FROM parametros_custos")

    parametros = {
        item["sku"]: item
        for item in cursor.fetchall()
    }

    cmv_por_sku = []
    cmv_total = 0

    for sku, venda in vendas_por_sku_dict.items():
        parametros_sku = parametros.get(sku)

        custo_ave = 0
        custo_embalagem = 0

        if parametros_sku:
            custo_ave = float(parametros_sku["custo_ave"] or 0)
            custo_embalagem = float(parametros_sku["custo_embalagem"] or 0)

        quantidade_unidades = float(venda["quantidade_unidades"] or 0)
        quantidade_kg = float(venda["quantidade_kg"] or 0)

        # Regra atual validada:
        # Galinha Cortada: (ave viva + embalagem) x bandejas vendidas.
        # CMV por kg = CMV total / kg vendidos.
        # Galinha Inteira: 1 x 1 por unidade vendida.
        custo_materia_prima_unitario = custo_ave
        custo_embalagem_unitario = custo_embalagem
        quantidade_cmv = quantidade_unidades

        custo_materia_prima = quantidade_cmv * custo_materia_prima_unitario
        custo_embalagens = quantidade_cmv * custo_embalagem_unitario
        cmv_sku = custo_materia_prima + custo_embalagens
        cmv_total += cmv_sku

        cmv_por_kg = 0
        if sku == "Galinha Cortada" and quantidade_kg > 0:
            cmv_por_kg = cmv_sku / quantidade_kg

        cmv_por_unidade = 0
        if quantidade_cmv > 0:
            cmv_por_unidade = cmv_sku / quantidade_cmv

        cmv_por_sku.append({
            "sku": sku,
            "quantidade_vendida": round(quantidade_kg if sku == "Galinha Cortada" else quantidade_unidades, 2),
            "quantidade_unidades": round(quantidade_unidades, 2),
            "quantidade_kg": round(quantidade_kg, 2),
            "custo_materia_prima_unitario": round(custo_materia_prima_unitario, 4),
            "custo_embalagem_unitario": round(custo_embalagem_unitario, 4),
            "materia_prima": round(custo_materia_prima, 2),
            "embalagem": round(custo_embalagens, 2),
            "cmv": round(cmv_sku, 2),
            "cmv_por_kg": round(cmv_por_kg, 4),
            "cmv_por_unidade": round(cmv_por_unidade, 4),
            "observacao_calculo": "CMV por bandeja vendida; CMV/kg calculado pelos kg vendidos." if sku == "Galinha Cortada" else "CMV 1 x 1 por unidade vendida."
        })

    cursor.execute(q("""
    SELECT
        categoria,
        COALESCE(SUM(valor), 0) as total
    FROM custos_mensais
    WHERE competencia = ?
    GROUP BY categoria
    ORDER BY categoria
    """), (competencia,))

    custos_raw = cursor.fetchall()
    conn.close()

    categorias = CATEGORIAS_CUSTOS
    custos = {
        categoria: 0
        for categoria in categorias
    }

    for item in custos_raw:
        categoria = item["categoria"]
        valor = float(item["total"] or 0)
        custos[categoria] = custos.get(categoria, 0) + valor

    custos_operacionais_total = sum(custos.values())
    margem_bruta = receita_bruta - cmv_total
    resultado_operacional = margem_bruta - custos_operacionais_total

    def perc(valor):
        if receita_bruta > 0:
            return (valor / receita_bruta) * 100

        return 0

    linhas_custos = [
        {
            "categoria": categoria,
            "valor": round(valor, 2),
            "percentual": round(perc(valor), 2)
        }
        for categoria, valor in custos.items()
    ]

    linhas_custos_executivas = preparar_linhas_custos_executivas(linhas_custos)
    despesas_grafico = preparar_grafico_despesas_operacionais(linhas_custos, receita_bruta)

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
        "linhas_custos_executivas": linhas_custos_executivas,
        "despesas_grafico": despesas_grafico,
        "resultado_operacional": round(resultado_operacional, 2),
        "margem_operacional_percentual": round(perc(resultado_operacional), 2)
    }

def gerar_excel_dre_gerencial(competencia, dados):
    wb = Workbook()
    ws = wb.active
    ws.title = "DRE Gerencial"

    azul = "1F3B4D"
    laranja = "F97316"
    cinza = "F8FAFC"
    branco = "FFFFFF"
    azul_resultado = "2563EB"
    vermelho = "DC2626"

    fill_topo = PatternFill("solid", fgColor=azul)
    fill_laranja = PatternFill("solid", fgColor=laranja)
    fill_cinza = PatternFill("solid", fgColor=cinza)
    fill_resultado = PatternFill(
        "solid",
        fgColor=azul_resultado if dados["resultado_operacional"] >= 0 else vermelho
    )

    fonte_titulo = Font(color=branco, bold=True, size=16)
    fonte_subtitulo = Font(color=branco, bold=True, size=11)
    fonte_header = Font(color=branco, bold=True)
    fonte_negrito = Font(bold=True, color=azul)
    fonte_resultado = Font(color=branco, bold=True, size=13)

    borda = Border(
        left=Side(style="thin", color="E2E8F0"),
        right=Side(style="thin", color="E2E8F0"),
        top=Side(style="thin", color="E2E8F0"),
        bottom=Side(style="thin", color="E2E8F0")
    )

    ws.merge_cells("A1:D1")
    ws["A1"] = "FRIGODATTA — DRE Gerencial Industrial"
    ws["A1"].fill = fill_topo
    ws["A1"].font = fonte_titulo
    ws["A1"].alignment = Alignment(horizontal="center")

    ws.merge_cells("A2:D2")
    ws["A2"] = f"Competência: {competencia}"
    ws["A2"].fill = fill_topo
    ws["A2"].font = fonte_subtitulo
    ws["A2"].alignment = Alignment(horizontal="center")

    linha = 4

    ws[f"A{linha}"] = "Indicador"
    ws[f"B{linha}"] = "Valor"
    ws[f"C{linha}"] = "% Receita"
    ws[f"D{linha}"] = "Observação"

    for col in range(1, 5):
        celula = ws.cell(row=linha, column=col)
        celula.fill = fill_laranja
        celula.font = fonte_header
        celula.alignment = Alignment(horizontal="center")
        celula.border = borda

    kpis = [
        ("Receita Bruta", dados["receita_bruta"], 100 if dados["receita_bruta"] > 0 else 0, "Venda de galinhas"),
        ("CMV", dados["cmv_total"], dados["cmv_percentual"], "Custo das vendas"),
        ("Margem Bruta", dados["margem_bruta"], dados["margem_bruta_percentual"], "Receita - CMV"),
        ("Custos Operacionais", dados["custos_operacionais_total"], dados["custos_operacionais_percentual"], "Custos mensais"),
        ("Resultado Operacional", dados["resultado_operacional"], dados["margem_operacional_percentual"], "Margem Bruta - Custos")
    ]

    for item in kpis:
        linha += 1
        ws[f"A{linha}"] = item[0]
        ws[f"B{linha}"] = item[1]
        ws[f"C{linha}"] = item[2] / 100
        ws[f"D{linha}"] = item[3]

        for col in range(1, 5):
            celula = ws.cell(row=linha, column=col)
            celula.border = borda
            celula.fill = fill_cinza
            if col == 1:
                celula.font = fonte_negrito

        ws[f"B{linha}"].number_format = 'R$ #,##0.00'
        ws[f"C{linha}"].number_format = '0.00%'

    linha += 3
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=4)
    ws.cell(row=linha, column=1).value = "DRE"
    ws.cell(row=linha, column=1).fill = fill_topo
    ws.cell(row=linha, column=1).font = fonte_header
    ws.cell(row=linha, column=1).alignment = Alignment(horizontal="center")

    linhas_dre = []

    linhas_dre.append(("Receita Bruta", dados["receita_bruta"], "receita"))

    for venda in dados["vendas_por_sku"]:
        linhas_dre.append((f"  Venda — {venda['sku']}", venda["receita"], "subitem"))

    linhas_dre.append(("(-) CMV", dados["cmv_total"], "normal"))

    for cmv in dados["cmv_por_sku"]:
        linhas_dre.append((f"  CMV — {cmv['sku']}", cmv["cmv"], "subitem"))

    linhas_dre.append(("= Margem Bruta", dados["margem_bruta"], "total"))
    linhas_dre.append(("Custos Operacionais", None, "grupo"))

    for custo in dados["linhas_custos"]:
        linhas_dre.append((f"(-) {custo['categoria']}", custo["valor"], "normal"))

    linhas_dre.append(("Total de Custos Operacionais", dados["custos_operacionais_total"], "total"))
    linhas_dre.append(("= Resultado Operacional", dados["resultado_operacional"], "resultado"))

    for descricao, valor, tipo in linhas_dre:
        linha += 1

        ws[f"A{linha}"] = descricao

        if valor is not None:
            ws[f"B{linha}"] = valor
            ws[f"B{linha}"].number_format = 'R$ #,##0.00'

        ws.merge_cells(start_row=linha, start_column=2, end_row=linha, end_column=4)

        for col in range(1, 5):
            celula = ws.cell(row=linha, column=col)
            celula.border = borda

        if tipo == "grupo":
            for col in range(1, 5):
                ws.cell(row=linha, column=col).fill = fill_topo
                ws.cell(row=linha, column=col).font = fonte_header
        elif tipo == "resultado":
            for col in range(1, 5):
                ws.cell(row=linha, column=col).fill = fill_resultado
                ws.cell(row=linha, column=col).font = fonte_resultado
        elif tipo == "total":
            for col in range(1, 5):
                ws.cell(row=linha, column=col).fill = fill_cinza
                ws.cell(row=linha, column=col).font = fonte_negrito
        elif tipo == "subitem":
            ws[f"A{linha}"].font = Font(color="64748B")
            ws[f"B{linha}"].font = Font(color="64748B")
        else:
            ws[f"A{linha}"].font = fonte_negrito

    linha += 3
    ws.merge_cells(start_row=linha, start_column=1, end_row=linha, end_column=4)
    ws.cell(row=linha, column=1).value = (
        "Leitura executiva: "
        + ("A operação apresentou resultado operacional positivo." if dados["resultado_operacional"] >= 0 else "A operação apresentou resultado operacional negativo.")
    )
    ws.cell(row=linha, column=1).alignment = Alignment(wrap_text=True)
    ws.cell(row=linha, column=1).fill = PatternFill("solid", fgColor="FFF7ED")

    larguras = {
        "A": 38,
        "B": 18,
        "C": 14,
        "D": 32
    }

    for coluna, largura in larguras.items():
        ws.column_dimensions[coluna].width = largura

    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(
                vertical="center",
                horizontal="right" if cell.column >= 2 else "left",
                wrap_text=True
            )

    ws.page_setup.orientation = "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.freeze_panes = "A4"

    arquivo = BytesIO()
    wb.save(arquivo)
    arquivo.seek(0)

    return arquivo






# ============================================================
# MÓDULO ALMOXARIFADO
# ============================================================

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


@app.route("/almoxarifado", methods=["GET", "POST"])
@perfil_permitido("pcp")
def almoxarifado():
    criar_tabelas_almoxarifado()

    categoria_filtro = request.args.get("categoria") or "Todas"
    status_filtro = request.args.get("status") or "Todos"
    termo = request.args.get("termo") or ""

    if request.method == "POST":
        try:
            salvar_insumo_almoxarifado(request.form)
            flash("Insumo cadastrado com sucesso.")
            return redirect(url_for("almoxarifado"))
        except Exception as erro:
            flash(f"Erro ao cadastrar insumo: {erro}")

    insumos = buscar_insumos_almoxarifado(categoria_filtro, status_filtro, termo)
    resumo = calcular_resumo_almoxarifado(insumos)

    return render_template(
        "almoxarifado.html",
        insumos=insumos,
        resumo=resumo,
        categorias=CATEGORIAS_ALMOXARIFADO,
        unidades=UNIDADES_ALMOXARIFADO,
        categoria_filtro=categoria_filtro,
        status_filtro=status_filtro,
        termo=termo
    )


@app.route("/almoxarifado/editar/<int:insumo_id>", methods=["GET", "POST"])
@perfil_permitido("pcp")
def editar_insumo_almoxarifado(insumo_id):
    insumo = buscar_insumo_almoxarifado_por_id(insumo_id)

    if not insumo:
        flash("Insumo não encontrado.")
        return redirect(url_for("almoxarifado"))

    if request.method == "POST":
        try:
            atualizar_insumo_almoxarifado(insumo_id, request.form)
            flash("Insumo atualizado com sucesso.")
            return redirect(url_for("almoxarifado"))
        except Exception as erro:
            flash(f"Erro ao atualizar insumo: {erro}")

    return render_template(
        "almoxarifado_editar.html",
        insumo=insumo,
        categorias=CATEGORIAS_ALMOXARIFADO,
        unidades=UNIDADES_ALMOXARIFADO
    )


@app.route("/almoxarifado/entrada", methods=["GET", "POST"])
@perfil_permitido("pcp")
def entrada_estoque_almoxarifado():
    criar_tabelas_estoque_almoxarifado()

    if request.method == "POST":
        try:
            salvar_entrada_estoque_almoxarifado(request.form)
            flash("Entrada de estoque registrada com sucesso.")
            return redirect(url_for("entrada_estoque_almoxarifado"))
        except Exception as erro:
            flash(f"Erro ao registrar entrada de estoque: {erro}")

    hoje = datetime.now().strftime("%Y-%m-%d")
    insumos = buscar_insumos_almoxarifado("Todas", "Sim", "")
    saldos = buscar_saldos_almoxarifado()
    lotes = buscar_lotes_almoxarifado()
    movimentacoes = buscar_movimentacoes_almoxarifado()
    resumo = calcular_resumo_estoque_almoxarifado(saldos)

    return render_template(
        "almoxarifado_entrada.html",
        hoje=hoje,
        insumos=insumos,
        saldos=saldos,
        lotes=lotes,
        movimentacoes=movimentacoes,
        resumo=resumo
    )



@app.route("/almoxarifado/saldo")
@perfil_permitido("pcp")
def saldo_almoxarifado():
    criar_tabelas_estoque_almoxarifado()

    categoria_filtro = request.args.get("categoria") or "Todas"
    termo = request.args.get("termo") or ""

    saldos = buscar_saldos_almoxarifado_filtrado(categoria_filtro, termo)
    resumo = calcular_resumo_estoque_almoxarifado(saldos)

    return render_template(
        "almoxarifado_saldo.html",
        saldos=saldos,
        resumo=resumo,
        categorias=CATEGORIAS_ALMOXARIFADO,
        categoria_filtro=categoria_filtro,
        termo=termo
    )


@app.route("/almoxarifado/movimentacoes")
@perfil_permitido("pcp")
def movimentacoes_almoxarifado():
    criar_tabelas_estoque_almoxarifado()

    agora = datetime.now()
    hoje = agora.strftime("%Y-%m-%d")
    primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

    data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
    data_fim = request.args.get("data_fim") or hoje
    tipo_filtro = request.args.get("tipo") or "Todos"
    termo = request.args.get("termo") or ""

    movimentacoes = buscar_movimentacoes_almoxarifado_filtrado(
        data_inicio,
        data_fim,
        tipo_filtro,
        termo
    )

    entradas = sum(float(item["valor_total"] or 0) for item in movimentacoes if item["tipo"] == "ENTRADA")
    saidas = sum(float(item["valor_total"] or 0) for item in movimentacoes if item["tipo"] == "SAIDA")

    resumo = {
        "total_movimentacoes": len(movimentacoes),
        "valor_entradas": round(entradas, 2),
        "valor_saidas": round(saidas, 2),
        "saldo_valor": round(entradas - saidas, 2)
    }

    return render_template(
        "almoxarifado_movimentacoes.html",
        movimentacoes=movimentacoes,
        resumo=resumo,
        data_inicio=data_inicio,
        data_fim=data_fim,
        tipo_filtro=tipo_filtro,
        termo=termo
    )


@app.route("/almoxarifado/rastreabilidade")
@perfil_permitido("pcp")
def rastreabilidade_almoxarifado():
    criar_tabelas_estoque_almoxarifado()

    insumo_id = request.args.get("insumo_id") or ""
    status_filtro = request.args.get("status") or "Todos"
    termo = request.args.get("termo") or ""

    insumos = buscar_insumos_almoxarifado("Todas", "Sim", "")
    lotes = buscar_lotes_almoxarifado_filtrado(insumo_id, status_filtro, termo)
    resumo = calcular_resumo_rastreabilidade(lotes)

    return render_template(
        "almoxarifado_rastreabilidade.html",
        insumos=insumos,
        lotes=lotes,
        resumo=resumo,
        insumo_id=insumo_id,
        status_filtro=status_filtro,
        termo=termo
    )



# ============================================================
# MÓDULO RECEITAS DOS SKUS
# ============================================================

UNIDADES_VENDA_SKU = [
    "Kg",
    "Un"
]

TIPOS_CONSUMO_RECEITA = [
    "Matéria-prima",
    "Embalagem primária - 1 pra 1",
    "Embalagem secundária - proporcional",
    "Outro"
]


def criar_tabelas_receitas_sku():
    criar_tabelas_estoque_almoxarifado()

    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS skus (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL UNIQUE,
            unidade_venda TEXT NOT NULL DEFAULT 'Kg',
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS receitas_sku (
            id SERIAL PRIMARY KEY,
            sku_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            quantidade_por_unidade REAL NOT NULL,
            tipo_consumo TEXT DEFAULT '',
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS skus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            unidade_venda TEXT NOT NULL DEFAULT 'Kg',
            ativo TEXT DEFAULT 'Sim',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS receitas_sku (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            quantidade_por_unidade REAL NOT NULL,
            tipo_consumo TEXT DEFAULT '',
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    conn.commit()

    skus_padrao = [
        ("Galinha Cortada", "Kg", "Produto vendido por kg. A OP consome insumos por unidade produzida e forma estoque em kg."),
        ("Galinha Inteira", "Un", "Produto vendido por unidade.")
    ]

    for sku in skus_padrao:
        try:
            cursor.execute(q("""
            INSERT INTO skus (nome, unidade_venda, ativo, observacoes)
            VALUES (?, ?, ?, ?)
            """), (sku[0], sku[1], "Sim", sku[2]))
            conn.commit()
        except Exception:
            conn.rollback()

    conn.close()


def buscar_skus(filtro_status="Todos"):
    criar_tabelas_receitas_sku()

    condicoes = ["1 = 1"]
    parametros = []

    if filtro_status and filtro_status != "Todos":
        condicoes.append("ativo = ?")
        parametros.append(filtro_status)

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT *
    FROM skus
    WHERE {where_sql}
    ORDER BY ativo DESC, nome ASC
    """), tuple(parametros))

    skus = cursor.fetchall()
    conn.close()
    return skus


def salvar_sku(form):
    criar_tabelas_receitas_sku()

    nome = form.get("nome", "").strip()
    unidade_venda = form.get("unidade_venda", "Kg").strip()
    ativo = form.get("ativo", "Sim").strip()
    observacoes = form.get("observacoes", "").strip()

    if not nome:
        raise ValueError("Informe o nome do SKU.")

    if unidade_venda not in UNIDADES_VENDA_SKU:
        raise ValueError("Unidade de venda inválida.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO skus (nome, unidade_venda, ativo, observacoes)
    VALUES (?, ?, ?, ?)
    """), (nome, unidade_venda, ativo, observacoes))

    conn.commit()
    conn.close()


def salvar_item_receita_sku(form):
    criar_tabelas_receitas_sku()

    sku_id = int(form.get("sku_id") or 0)
    insumo_id = int(form.get("insumo_id") or 0)
    quantidade_por_unidade = float(form.get("quantidade_por_unidade") or 0)
    tipo_consumo = form.get("tipo_consumo", "").strip()
    observacoes = form.get("observacoes", "").strip()

    if quantidade_por_unidade <= 0:
        raise ValueError("A quantidade por unidade precisa ser maior que zero.")

    if tipo_consumo and tipo_consumo not in TIPOS_CONSUMO_RECEITA:
        raise ValueError("Tipo de consumo inválido.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("SELECT id FROM skus WHERE id = ?"), (sku_id,))
    if not cursor.fetchone():
        conn.close()
        raise ValueError("Selecione um SKU válido.")

    cursor.execute(q("SELECT id FROM almoxarifado_insumos WHERE id = ?"), (insumo_id,))
    if not cursor.fetchone():
        conn.close()
        raise ValueError("Selecione um insumo válido.")

    cursor.execute(q("""
    INSERT INTO receitas_sku (
        sku_id,
        insumo_id,
        quantidade_por_unidade,
        tipo_consumo,
        observacoes
    ) VALUES (?, ?, ?, ?, ?)
    """), (
        sku_id,
        insumo_id,
        quantidade_por_unidade,
        tipo_consumo,
        observacoes
    ))

    conn.commit()
    conn.close()


def excluir_item_receita_sku(item_id):
    criar_tabelas_receitas_sku()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("DELETE FROM receitas_sku WHERE id = ?"), (item_id,))

    conn.commit()
    conn.close()


def buscar_receitas_sku():
    criar_tabelas_receitas_sku()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        r.*,
        s.nome as sku,
        s.unidade_venda as unidade_venda,
        i.descricao as insumo,
        i.categoria as categoria_insumo,
        i.unidade as unidade_insumo
    FROM receitas_sku r
    JOIN skus s ON s.id = r.sku_id
    JOIN almoxarifado_insumos i ON i.id = r.insumo_id
    ORDER BY s.nome ASC, r.id ASC
    """)

    itens = cursor.fetchall()
    conn.close()

    receitas = {}

    for item in itens:
        sku = item["sku"]
        if sku not in receitas:
            receitas[sku] = {
                "sku": sku,
                "unidade_venda": item["unidade_venda"],
                "itens": [],
                "total_itens": 0
            }

        receitas[sku]["itens"].append(item)
        receitas[sku]["total_itens"] += 1

    return list(receitas.values())


def calcular_resumo_receitas_sku(skus, receitas):
    total_skus = len(skus)
    skus_ativos = sum(1 for item in skus if item["ativo"] == "Sim")
    total_itens = sum(receita["total_itens"] for receita in receitas)
    skus_com_receita = len(receitas)

    return {
        "total_skus": total_skus,
        "skus_ativos": skus_ativos,
        "skus_com_receita": skus_com_receita,
        "total_itens": total_itens
    }


@app.route("/receitas-sku", methods=["GET", "POST"])
@perfil_permitido("pcp")
def receitas_sku():
    criar_tabelas_receitas_sku()

    if request.method == "POST":
        acao = request.form.get("acao")

        try:
            if acao == "salvar_sku":
                salvar_sku(request.form)
                flash("SKU cadastrado com sucesso.")

            elif acao == "salvar_item_receita":
                salvar_item_receita_sku(request.form)
                flash("Item adicionado à receita com sucesso.")

            else:
                flash("Ação inválida.")

        except Exception as erro:
            flash(f"Erro ao salvar receita/SKU: {erro}")

        return redirect(url_for("receitas_sku"))

    skus = buscar_skus()
    skus_ativos = buscar_skus("Sim")
    insumos = buscar_insumos_almoxarifado("Todas", "Sim", "")
    receitas = buscar_receitas_sku()
    resumo = calcular_resumo_receitas_sku(skus, receitas)

    return render_template(
        "receitas_sku.html",
        skus=skus,
        skus_ativos=skus_ativos,
        insumos=insumos,
        receitas=receitas,
        resumo=resumo,
        unidades_venda=UNIDADES_VENDA_SKU,
        tipos_consumo=TIPOS_CONSUMO_RECEITA
    )


@app.route("/receitas-sku/item/<int:item_id>/excluir", methods=["POST"])
@perfil_permitido("pcp")
def excluir_item_receita_sku_rota(item_id):
    excluir_item_receita_sku(item_id)
    flash("Item removido da receita com sucesso.")
    return redirect(url_for("receitas_sku"))


# ============================================================
# MÓDULO FINANCEIRO - MOVIMENTAÇÃO DE CAIXA
# ============================================================

CATEGORIAS_FINANCEIRAS_ENTRADA = [
    "Venda de produtos",
    "Recebimento de cliente",
    "Aporte",
    "Empréstimo recebido",
    "Outras entradas"
]

CATEGORIAS_FINANCEIRAS_SAIDA = [
    "Fornecedor",
    "Mão de obra",
    "Energia",
    "Água",
    "Lenha",
    "Combustível",
    "Manutenção",
    "Embalagens",
    "Impostos",
    "Marketing",
    "Serviços terceiros",
    "Empréstimos e financiamentos",
    "Outras saídas"
]

FORMAS_PAGAMENTO_FINANCEIRO = [
    "Pix",
    "Dinheiro",
    "Boleto",
    "Cartão",
    "Transferência",
    "Cheque",
    "Outro"
]

# Status que o usuário escolhe no lançamento.
# "Em atraso" não deve ser escolhido manualmente; o sistema calcula pela data de vencimento.
STATUS_FINANCEIRO = [
    "Pendente",
    "Realizado",
    "Cancelado"
]

# Opções usadas nos filtros e na leitura gerencial da tela.
STATUS_FINANCEIRO_FILTRO = [
    "Todos",
    "A vencer",
    "Em atraso",
    "Realizado",
    "Cancelado"
]


def calcular_status_financeiro_visual(item, data_referencia=None):
    """
    Calcula o status visual/gerencial sem alterar o status gravado no banco.

    Regra:
    - Cancelado permanece Cancelado;
    - Realizado vira Liquidado;
    - Pendente com vencimento anterior à data de referência vira Em atraso;
    - Pendente com vencimento igual ou posterior vira A vencer.

    Observação de segurança:
    Se existir algum registro antigo com status "Atrasado", ele será exibido como "Em atraso"
    para manter compatibilidade com dados já lançados.
    """
    if data_referencia is None:
        data_referencia = datetime.now().date()

    status = (item.get("status") if hasattr(item, "get") else item["status"]) or "Pendente"
    data_vencimento = (item.get("data_vencimento") if hasattr(item, "get") else item["data_vencimento"]) or ""

    if status == "Cancelado":
        return "Cancelado"

    if status == "Realizado":
        return "Liquidado"

    if status == "Atrasado":
        return "Em atraso"

    try:
        vencimento = datetime.strptime(data_vencimento, "%Y-%m-%d").date()
    except Exception:
        return "A vencer"

    if vencimento < data_referencia:
        return "Em atraso"

    return "A vencer"


def preparar_movimentacoes_financeiras_para_tela(movimentacoes, status_filtro="Todos"):
    """
    Converte as linhas retornadas do banco em dicionários e adiciona campos calculados.
    Isso evita alterar a estrutura do banco e protege a lógica já existente.
    """
    hoje_data = datetime.now().date()
    resultado = []

    for item in movimentacoes:
        item_dict = dict(item)
        status_visual = calcular_status_financeiro_visual(item_dict, hoje_data)
        item_dict["status_original"] = item_dict.get("status", "Pendente")
        item_dict["status_visual"] = status_visual

        # Classe CSS simples para futura estilização do badge, sem obrigar mudança no template.
        item_dict["status_classe"] = (
            status_visual.lower()
            .replace(" ", "-")
            .replace("ç", "c")
            .replace("ã", "a")
        )

        if status_filtro == "Todos" or status_visual == status_filtro:
            resultado.append(item_dict)

    return resultado


def criar_tabela_movimentacoes_financeiras():
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes_financeiras (
            id SERIAL PRIMARY KEY,
            data_vencimento TEXT NOT NULL,
            data_realizacao TEXT,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            forma_pagamento TEXT,
            status TEXT DEFAULT 'Pendente',
            parcelas INTEGER DEFAULT 1,
            parcela_atual INTEGER DEFAULT 1,
            intervalo_dias INTEGER DEFAULT 30,
            documento_id TEXT,
            data_documento TEXT,
            valor_documento REAL DEFAULT 0,
            prazo_medio_dias REAL DEFAULT 0,
            observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimentacoes_financeiras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_vencimento TEXT NOT NULL,
            data_realizacao TEXT,
            tipo TEXT NOT NULL,
            categoria TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            forma_pagamento TEXT,
            status TEXT DEFAULT 'Pendente',
            parcelas INTEGER DEFAULT 1,
            parcela_atual INTEGER DEFAULT 1,
            intervalo_dias INTEGER DEFAULT 30,
            documento_id TEXT,
            data_documento TEXT,
            valor_documento REAL DEFAULT 0,
            prazo_medio_dias REAL DEFAULT 0,
            observacoes TEXT,
            criado_em TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)

    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN intervalo_dias INTEGER DEFAULT 30")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN documento_id TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN data_documento TEXT")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN valor_documento REAL DEFAULT 0")
    tentar_alter_table(cursor, conn, "ALTER TABLE movimentacoes_financeiras ADD COLUMN prazo_medio_dias REAL DEFAULT 0")

    conn.commit()
    conn.close()


def adicionar_meses(data_base, meses):
    ano = data_base.year
    mes = data_base.month + meses

    while mes > 12:
        mes -= 12
        ano += 1

    while mes < 1:
        mes += 12
        ano -= 1

    ultimo_dia = calendar.monthrange(ano, mes)[1]
    dia = min(data_base.day, ultimo_dia)

    return data_base.replace(year=ano, month=mes, day=dia)


def salvar_movimentacao_financeira(form):
    criar_tabela_movimentacoes_financeiras()

    tipo = form.get("tipo", "").strip()
    categoria = form.get("categoria", "").strip()
    descricao = form.get("descricao", "").strip()
    data_documento = form.get("data_documento") or datetime.now().strftime("%Y-%m-%d")
    data_realizacao = form.get("data_realizacao", "")
    forma_pagamento = form.get("forma_pagamento", "")
    status = form.get("status", "Pendente")
    observacoes = form.get("observacoes", "")
    valor_documento = float(form.get("valor") or 0)

    vencimentos = form.getlist("parcela_vencimento[]")
    valores = form.getlist("parcela_valor[]")

    if tipo not in ["Entrada", "Saída"]:
        raise ValueError("Tipo de movimentação inválido.")

    if not descricao:
        raise ValueError("Informe uma descrição para a movimentação.")

    if valor_documento <= 0:
        raise ValueError("O valor total do documento deve ser maior que zero.")

    parcelas_validas = []

    for vencimento, valor in zip(vencimentos, valores):
        vencimento = (vencimento or "").strip()
        valor = float(valor or 0)

        if vencimento and valor > 0:
            parcelas_validas.append({
                "vencimento": vencimento,
                "valor": round(valor, 2)
            })

    if not parcelas_validas:
        parcelas_validas.append({
            "vencimento": data_documento,
            "valor": round(valor_documento, 2)
        })

    soma_parcelas = round(sum(item["valor"] for item in parcelas_validas), 2)

    if abs(soma_parcelas - round(valor_documento, 2)) > 0.02:
        raise ValueError(
            f"A soma das parcelas (R$ {soma_parcelas:.2f}) precisa bater com o valor total do documento (R$ {valor_documento:.2f})."
        )

    data_base = datetime.strptime(data_documento, "%Y-%m-%d")
    prazo_ponderado = 0

    for item in parcelas_validas:
        data_vencimento = datetime.strptime(item["vencimento"], "%Y-%m-%d")
        dias = (data_vencimento - data_base).days
        prazo_ponderado += item["valor"] * dias

    prazo_medio_dias = prazo_ponderado / valor_documento if valor_documento > 0 else 0
    documento_id = uuid.uuid4().hex
    total_parcelas = len(parcelas_validas)

    conn = conectar()
    cursor = conn.cursor()

    for indice, parcela in enumerate(parcelas_validas, start=1):
        descricao_parcela = descricao

        if total_parcelas > 1:
            descricao_parcela = f"{descricao} ({indice}/{total_parcelas})"

        cursor.execute(q("""
        INSERT INTO movimentacoes_financeiras (
            data_vencimento,
            data_realizacao,
            tipo,
            categoria,
            descricao,
            valor,
            forma_pagamento,
            status,
            parcelas,
            parcela_atual,
            intervalo_dias,
            documento_id,
            data_documento,
            valor_documento,
            prazo_medio_dias,
            observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            parcela["vencimento"],
            data_realizacao if status == "Realizado" else "",
            tipo,
            categoria,
            descricao_parcela,
            parcela["valor"],
            forma_pagamento,
            status,
            total_parcelas,
            indice,
            0,
            documento_id,
            data_documento,
            valor_documento,
            round(prazo_medio_dias, 2),
            observacoes
        ))

    conn.commit()
    conn.close()


def buscar_movimentacao_financeira_por_id(movimentacao_id):
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE id = ?
    """), (movimentacao_id,))

    movimentacao = cursor.fetchone()
    conn.close()

    return movimentacao


def atualizar_movimentacao_financeira(movimentacao_id, form):
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    UPDATE movimentacoes_financeiras
    SET data_vencimento = ?,
        data_realizacao = ?,
        tipo = ?,
        categoria = ?,
        descricao = ?,
        valor = ?,
        forma_pagamento = ?,
        status = ?,
        intervalo_dias = ?,
        observacoes = ?
    WHERE id = ?
    """), (
        form.get("data_vencimento", ""),
        form.get("data_realizacao", ""),
        form.get("tipo", ""),
        form.get("categoria", ""),
        form.get("descricao", ""),
        float(form.get("valor") or 0),
        form.get("forma_pagamento", ""),
        form.get("status", ""),
        int(form.get("intervalo_dias") or 30),
        form.get("observacoes", ""),
        movimentacao_id
    ))

    conn.commit()
    conn.close()


def excluir_movimentacao_financeira(movimentacao_id):
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    DELETE FROM movimentacoes_financeiras
    WHERE id = ?
    """), (movimentacao_id,))

    conn.commit()
    conn.close()


def buscar_movimentacoes_financeiras(data_inicio, data_fim, tipo_filtro, status_filtro):
    criar_tabela_movimentacoes_financeiras()

    condicoes = ["data_vencimento BETWEEN ? AND ?"]
    parametros = [data_inicio, data_fim]

    if tipo_filtro in ["Entrada", "Saída"]:
        condicoes.append("tipo = ?")
        parametros.append(tipo_filtro)

    # O filtro por status visual é aplicado depois da consulta, porque "A vencer" e
    # "Em atraso" são calculados pela data de vencimento, não gravados no banco.
    if status_filtro == "Realizado":
        condicoes.append("status = ?")
        parametros.append("Realizado")
    elif status_filtro == "Cancelado":
        condicoes.append("status = ?")
        parametros.append("Cancelado")

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE {where_sql}
    ORDER BY data_vencimento ASC, id ASC
    """), tuple(parametros))

    movimentacoes = cursor.fetchall()
    conn.close()

    return preparar_movimentacoes_financeiras_para_tela(movimentacoes, status_filtro)


def calcular_resumo_financeiro(movimentacoes):
    entradas_previstas = 0
    saidas_previstas = 0
    entradas_realizadas = 0
    saidas_realizadas = 0

    for item in movimentacoes:
        valor = float(item["valor"] or 0)
        tipo = item["tipo"]
        status = item.get("status_original", item.get("status", "Pendente")) if hasattr(item, "get") else item["status"]

        # Cancelados não entram no previsto nem no realizado.
        if status == "Cancelado":
            continue

        if tipo == "Entrada":
            entradas_previstas += valor

            if status == "Realizado":
                entradas_realizadas += valor

        elif tipo == "Saída":
            saidas_previstas += valor

            if status == "Realizado":
                saidas_realizadas += valor

    saldo_previsto = entradas_previstas - saidas_previstas
    saldo_realizado = entradas_realizadas - saidas_realizadas

    return {
        "entradas_previstas": round(entradas_previstas, 2),
        "saidas_previstas": round(saidas_previstas, 2),
        "saldo_previsto": round(saldo_previsto, 2),
        "entradas_realizadas": round(entradas_realizadas, 2),
        "saidas_realizadas": round(saidas_realizadas, 2),
        "saldo_realizado": round(saldo_realizado, 2)
    }


def agrupar_fluxo_por_dia(movimentacoes):
    fluxo = {}

    for item in movimentacoes:
        data = item["data_vencimento"]
        valor = float(item["valor"] or 0)

        if data not in fluxo:
            fluxo[data] = {
                "data": data,
                "entradas": 0,
                "saidas": 0,
                "saldo": 0
            }

        status = item.get("status_original", item.get("status", "Pendente")) if hasattr(item, "get") else item["status"]

        # Fluxo diário ignora documentos cancelados.
        if status == "Cancelado":
            continue

        if item["tipo"] == "Entrada":
            fluxo[data]["entradas"] += valor
        else:
            fluxo[data]["saidas"] += valor

        fluxo[data]["saldo"] = fluxo[data]["entradas"] - fluxo[data]["saidas"]

    return [
        {
            "data": item["data"],
            "entradas": round(item["entradas"], 2),
            "saidas": round(item["saidas"], 2),
            "saldo": round(item["saldo"], 2)
        }
        for item in fluxo.values()
    ]



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
@perfil_permitido("pcp", "producao", "qualidade")
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

    # Base técnica do rendimento: sempre Galinha Cortada.
    # Isso evita distorção quando o filtro estiver em "Todos" ou quando houver Galinha Inteira no período.
    cursor.execute(q(f"""
    SELECT COALESCE(SUM(p.quantidade), 0) as kg
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(p.unidade) = 'kg'
      AND COALESCE(o.sku, 'Galinha Cortada') = 'Galinha Cortada'
      {status_condicao_alias}
    """), (data_inicio, data_fim) + parametros_status)

    kg_produzidos_rendimento = cursor.fetchone()["kg"] or 0

    cursor.execute(q(f"""
    SELECT COALESCE(SUM(peso_vivo), 0) as peso_vivo
    FROM ordens_producao
    WHERE data BETWEEN ? AND ?
      AND COALESCE(sku, 'Galinha Cortada') = 'Galinha Cortada'
      {status_condicao_op}
    """), (data_inicio, data_fim) + parametros_status)

    peso_entrada_rendimento = cursor.fetchone()["peso_vivo"] or 0
    rendimento_aplicavel = sku_filtro != "Galinha Inteira"

    # Mix de produção do período: respeita data e status, mas ignora o filtro de SKU.
    cursor.execute(q(f"""
    SELECT
        COALESCE(o.sku, 'Galinha Cortada') as sku,
        COALESCE(SUM(p.quantidade), 0) as unidades_produzidas
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND p.setor = 'Expedição'
      AND LOWER(p.unidade) IN ('unidades', 'unidade', 'aves', 'ave')
      {status_condicao_alias}
    GROUP BY COALESCE(o.sku, 'Galinha Cortada')
    ORDER BY unidades_produzidas DESC
    """), (data_inicio, data_fim) + parametros_status)

    mix_unidades_raw = cursor.fetchall()

    cursor.execute(q(f"""
    SELECT
        COALESCE(o.sku, 'Galinha Cortada') as sku,
        COALESCE(SUM(p.quantidade), 0) as kg_produzidos
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(p.unidade) = 'kg'
      {status_condicao_alias}
    GROUP BY COALESCE(o.sku, 'Galinha Cortada')
    """), (data_inicio, data_fim) + parametros_status)

    mix_kg_raw = cursor.fetchall()
    kg_por_sku_mix = {
        item["sku"]: float(item["kg_produzidos"] or 0)
        for item in mix_kg_raw
    }

    total_unidades_mix = sum(float(item["unidades_produzidas"] or 0) for item in mix_unidades_raw)
    total_kg_mix = sum(kg_por_sku_mix.values())
    mix_producao_periodo = []

    for item in mix_unidades_raw:
        sku_mix = item["sku"] or "Não informado"
        unidades_mix = float(item["unidades_produzidas"] or 0)
        representatividade = (unidades_mix / total_unidades_mix * 100) if total_unidades_mix > 0 else 0
        mix_producao_periodo.append({
            "sku": sku_mix,
            "unidades_produzidas": round(unidades_mix, 2),
            "representatividade": round(representatividade, 2),
            "kg_produzidos": round(kg_por_sku_mix.get(sku_mix, 0), 2)
        })

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
    SELECT d.motivo, COALESCE(SUM(d.quantidade), 0) as quantidade
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      {status_condicao_alias}
      {sku_condicao_alias}
    GROUP BY d.motivo
    ORDER BY quantidade DESC
    """), (data_inicio, data_fim) + parametros_filtros)

    descartes_por_motivo_raw = cursor.fetchall()
    descartes_por_motivo = []

    if mortes_antes_pendura > 0:
        percentual_morte_gaiola = 0

        if total_problemas_aves > 0:
            percentual_morte_gaiola = (mortes_antes_pendura / total_problemas_aves) * 100

        descartes_por_motivo.append({
            "motivo": "Morte na gaiola / antes da pendura",
            "quantidade": round(mortes_antes_pendura, 2),
            "percentual": round(percentual_morte_gaiola, 2)
        })

    for item in descartes_por_motivo_raw:
        motivo = item["motivo"] or "Não informado"
        quantidade = item["quantidade"] or 0
        percentual = 0

        if total_problemas_aves > 0:
            percentual = (quantidade / total_problemas_aves) * 100

        descartes_por_motivo.append({
            "motivo": motivo,
            "quantidade": round(quantidade, 2),
            "percentual": round(percentual, 2)
        })

    descartes_por_motivo = sorted(
        descartes_por_motivo,
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
    if rendimento_aplicavel and peso_entrada_rendimento > 0:
        rendimento = (kg_produzidos_rendimento / peso_entrada_rendimento) * 100

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
        peso_entrada_rendimento=round(peso_entrada_rendimento, 2),
        kg_produzidos_rendimento=round(kg_produzidos_rendimento, 2),
        rendimento_aplicavel=rendimento_aplicavel,
        unidades_produzidas=round(unidades_produzidas, 2),
        mix_producao_periodo=mix_producao_periodo,
        total_unidades_mix=round(total_unidades_mix, 2),
        total_kg_mix=round(total_kg_mix, 2),
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
        descartes_por_motivo=descartes_por_motivo,
        descartes_por_setor=descartes_por_setor,
        produtividade_setores=produtividade_setores,
        produtividade_setores_hora=produtividade_setores_hora
    )









@app.route("/expedicao")
@perfil_permitido("pcp")
def expedicao():
    criar_tabelas_expedicao()

    hoje = datetime.now()
    primeiro_dia_mes = hoje.replace(day=1).strftime("%Y-%m-%d")
    data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
    data_fim = request.args.get("data_fim") or hoje.strftime("%Y-%m-%d")
    status = request.args.get("status") or "Todos"

    expedicoes = buscar_expedicoes(data_inicio, data_fim, status)
    resumo = calcular_resumo_expedicao(expedicoes)

    return render_template(
        "expedicao.html",
        expedicoes=expedicoes,
        resumo=resumo,
        data_inicio=data_inicio,
        data_fim=data_fim,
        status=status,
        status_opcoes=["Todos", "Aberto", "Concluído", "Cancelado"]
    )



def gerar_numero_romaneio(data_romaneio):
    """
    Gera número sequencial diário do romaneio.
    Formato: ROM-AAAAMMDD-001

    Sprint 1.1:
    - Numeração simples e isolada.
    - Não baixa estoque.
    - Não gera venda.
    - Não interfere em DRE, Financeiro ou Almoxarifado.
    """
    criar_tabelas_expedicao()

    data_base = (data_romaneio or datetime.now().strftime("%Y-%m-%d")).strip()
    prefixo = "ROM-" + data_base.replace("-", "")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT COUNT(*) as total
    FROM expedicoes
    WHERE numero_romaneio LIKE ?
    """), (f"{prefixo}-%",))

    resultado = cursor.fetchone()
    conn.close()

    total = int(resultado["total"] or 0)
    sequencial = total + 1

    return f"{prefixo}-{sequencial:03d}"


def salvar_romaneio_expedicao(form):
    """
    Salva apenas o cabeçalho do romaneio.

    Sprint 1.1:
    - Cria o romaneio em aberto.
    - Tipo fixo: TRANSFERENCIA.
    - Sem itens.
    - Sem baixa de estoque.
    """
    criar_tabelas_expedicao()

    data_romaneio = (form.get("data") or "").strip()
    destino = (form.get("destino") or "").strip()
    responsavel = (form.get("responsavel") or "").strip()
    observacoes = (form.get("observacoes") or "").strip()

    if not data_romaneio:
        raise ValueError("Informe a data do romaneio.")

    if not destino:
        raise ValueError("Informe o destino do romaneio.")

    numero_romaneio = gerar_numero_romaneio(data_romaneio)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO expedicoes (
        numero_romaneio,
        data,
        tipo_movimentacao,
        destino,
        responsavel,
        observacoes,
        status
    ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """), (
        numero_romaneio,
        data_romaneio,
        "TRANSFERENCIA",
        destino,
        responsavel,
        observacoes,
        "Aberto"
    ))

    conn.commit()
    conn.close()

    return numero_romaneio


@app.route("/expedicao/novo", methods=["GET", "POST"])
@perfil_permitido("pcp")
def novo_romaneio_expedicao():
    criar_tabelas_expedicao()

    hoje = datetime.now().strftime("%Y-%m-%d")

    if request.method == "POST":
        try:
            numero_romaneio = salvar_romaneio_expedicao(request.form)
            flash(f"Romaneio {numero_romaneio} criado com sucesso.")
            return redirect(url_for("expedicao"))
        except Exception as erro:
            flash(f"Erro ao criar romaneio: {erro}")

    return render_template(
        "novo_romaneio.html",
        hoje=hoje
    )




def buscar_expedicao_por_id(expedicao_id):
    criar_tabelas_expedicao()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM expedicoes
    WHERE id = ?
    """), (expedicao_id,))

    expedicao = cursor.fetchone()
    conn.close()

    return expedicao


def buscar_itens_expedicao(expedicao_id):
    criar_tabelas_expedicao()

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    SELECT *
    FROM expedicao_itens
    WHERE expedicao_id = ?
    ORDER BY id ASC
    """), (expedicao_id,))

    itens = cursor.fetchall()
    conn.close()

    return itens


def calcular_resumo_itens_expedicao(itens):
    total_itens = len(itens)
    total_unidades = sum(float(item["quantidade_unidades"] or 0) for item in itens)
    total_kg = sum(float(item["quantidade_kg"] or 0) for item in itens)

    return {
        "total_itens": total_itens,
        "total_unidades": round(total_unidades, 2),
        "total_kg": round(total_kg, 2)
    }


def salvar_item_expedicao(expedicao_id, form):
    """
    Salva item manual do romaneio.

    Sprint 1.2:
    - Itens manuais.
    - Sem baixa de estoque.
    - Sem vínculo obrigatório com OP.
    - Sem impacto na DRE, Financeiro ou Almoxarifado.
    """
    criar_tabelas_expedicao()

    expedicao = buscar_expedicao_por_id(expedicao_id)

    if not expedicao:
        raise ValueError("Romaneio não encontrado.")

    if expedicao["status"] != "Aberto":
        raise ValueError("Só é possível adicionar itens em romaneios abertos.")

    sku = (form.get("sku") or "").strip()
    quantidade_unidades = float(form.get("quantidade_unidades") or 0)
    quantidade_kg = float(form.get("quantidade_kg") or 0)

    if sku not in ["Galinha Cortada", "Galinha Inteira"]:
        raise ValueError("Selecione um SKU válido.")

    if quantidade_unidades < 0 or quantidade_kg < 0:
        raise ValueError("As quantidades não podem ser negativas.")

    if quantidade_unidades <= 0 and quantidade_kg <= 0:
        raise ValueError("Informe pelo menos uma quantidade para o item.")

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q("""
    INSERT INTO expedicao_itens (
        expedicao_id,
        op_id,
        sku,
        quantidade_unidades,
        quantidade_kg
    ) VALUES (?, ?, ?, ?, ?)
    """), (
        expedicao_id,
        None,
        sku,
        quantidade_unidades,
        quantidade_kg
    ))

    conn.commit()
    conn.close()


@app.route("/expedicao/<int:expedicao_id>", methods=["GET", "POST"])
@perfil_permitido("pcp")
def detalhe_romaneio_expedicao(expedicao_id):
    criar_tabelas_expedicao()

    expedicao = buscar_expedicao_por_id(expedicao_id)

    if not expedicao:
        flash("Romaneio não encontrado.")
        return redirect(url_for("expedicao"))

    if request.method == "POST":
        try:
            salvar_item_expedicao(expedicao_id, request.form)
            flash("Item adicionado ao romaneio com sucesso.")
            return redirect(url_for("detalhe_romaneio_expedicao", expedicao_id=expedicao_id))
        except Exception as erro:
            flash(f"Erro ao adicionar item: {erro}")

    itens = buscar_itens_expedicao(expedicao_id)
    resumo_itens = calcular_resumo_itens_expedicao(itens)

    return render_template(
        "romaneio_detalhe.html",
        expedicao=expedicao,
        itens=itens,
        resumo_itens=resumo_itens,
        skus=["Galinha Cortada", "Galinha Inteira"]
    )

@app.route("/dre-gerencial/exportar-excel")
@perfil_permitido("pcp")
def exportar_dre_gerencial_excel():
    criar_banco()
    criar_tabelas_custos()
    criar_tabela_vendas()

    competencia = request.args.get("competencia") or datetime.now().strftime("%Y-%m")
    dados = buscar_dados_dre_gerencial(competencia)
    arquivo = gerar_excel_dre_gerencial(competencia, dados)

    nome_arquivo = f"DRE_Gerencial_{competencia}.xlsx"

    return send_file(
        arquivo,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
        linhas_custos_executivas=dados.get("linhas_custos_executivas", dados["linhas_custos"]),
        despesas_grafico=dados.get("despesas_grafico", {}),
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
            receita = float(request.form["receita"])

            if receita < 0:
                raise ValueError("A receita não pode ser negativa.")

            form_edicao = request.form.copy()

            try:
                quantidade_unidades_atual = float(venda["quantidade_unidades"] or 0)
            except Exception:
                quantidade_unidades_atual = 0

            try:
                quantidade_kg_atual = float(venda["quantidade_kg"] or 0)
            except Exception:
                quantidade_kg_atual = 0

            if sku == "Galinha Cortada":
                if not form_edicao.get("quantidade_unidades") and quantidade_unidades_atual > 0:
                    form_edicao["quantidade_unidades"] = str(quantidade_unidades_atual)

                if not form_edicao.get("quantidade_kg") and quantidade_kg_atual > 0:
                    form_edicao["quantidade_kg"] = str(quantidade_kg_atual)

            quantidades = preparar_quantidades_venda(
                sku,
                form_edicao,
                quantidade_atual=float(venda["quantidade"] or 0),
                unidade_atual=venda["unidade"]
            )

            venda_duplicada = buscar_venda_diaria_por_data_sku(
                request.form["data"],
                sku,
                ignorar_id=venda_id
            )

            if venda_duplicada:
                raise ValueError(
                    "Já existe outra venda lançada para esta data e SKU. "
                    "Ajuste o lançamento existente ou escolha outra data/SKU."
                )

            conn = conectar()
            cursor = conn.cursor()
            cursor.execute(q("""
            UPDATE vendas_diarias
            SET data = ?,
                sku = ?,
                quantidade = ?,
                unidade = ?,
                quantidade_unidades = ?,
                quantidade_kg = ?,
                receita = ?,
                observacoes = ?
            WHERE id = ?
            """), (
                request.form["data"],
                sku,
                quantidades["quantidade"],
                quantidades["unidade"],
                quantidades["quantidade_unidades"],
                quantidades["quantidade_kg"],
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




@app.route("/financeiro", methods=["GET", "POST"])
@perfil_permitido("pcp")
def financeiro():
    criar_tabela_movimentacoes_financeiras()

    agora = datetime.now()
    hoje = agora.strftime("%Y-%m-%d")
    primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

    data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
    data_fim = request.args.get("data_fim") or hoje
    tipo_filtro = request.args.get("tipo") or "Todos"
    status_filtro = request.args.get("status") or "Todos"

    if request.method == "POST":
        try:
            salvar_movimentacao_financeira(request.form)
            flash("Movimentação financeira lançada com sucesso.")
            return redirect(url_for("financeiro"))
        except Exception as erro:
            flash(f"Erro ao salvar movimentação: {erro}")

    movimentacoes = buscar_movimentacoes_financeiras(
        data_inicio,
        data_fim,
        tipo_filtro,
        status_filtro
    )

    resumo = calcular_resumo_financeiro(movimentacoes)
    fluxo_diario = agrupar_fluxo_por_dia(movimentacoes)

    return render_template(
        "financeiro.html",
        hoje=hoje,
        data_inicio=data_inicio,
        data_fim=data_fim,
        tipo_filtro=tipo_filtro,
        status_filtro=status_filtro,
        movimentacoes=movimentacoes,
        resumo=resumo,
        fluxo_diario=fluxo_diario,
        categorias_entrada=CATEGORIAS_FINANCEIRAS_ENTRADA,
        categorias_saida=CATEGORIAS_FINANCEIRAS_SAIDA,
        formas_pagamento=FORMAS_PAGAMENTO_FINANCEIRO,
        status_opcoes=STATUS_FINANCEIRO_FILTRO
    )


@app.route("/financeiro/editar/<int:movimentacao_id>", methods=["GET", "POST"])
@perfil_permitido("pcp")
def editar_movimentacao_financeira(movimentacao_id):
    movimentacao = buscar_movimentacao_financeira_por_id(movimentacao_id)

    if not movimentacao:
        flash("Movimentação financeira não encontrada.")
        return redirect(url_for("financeiro"))

    if request.method == "POST":
        try:
            atualizar_movimentacao_financeira(movimentacao_id, request.form)
            flash("Movimentação financeira atualizada com sucesso.")
            return redirect(url_for("financeiro"))
        except Exception as erro:
            flash(f"Erro ao atualizar movimentação: {erro}")

    return render_template(
        "financeiro_editar.html",
        movimentacao=movimentacao,
        categorias_entrada=CATEGORIAS_FINANCEIRAS_ENTRADA,
        categorias_saida=CATEGORIAS_FINANCEIRAS_SAIDA,
        formas_pagamento=FORMAS_PAGAMENTO_FINANCEIRO,
        status_opcoes=STATUS_FINANCEIRO
    )


@app.route("/financeiro/excluir/<int:movimentacao_id>", methods=["POST"])
@perfil_permitido("pcp")
def excluir_movimentacao_financeira_rota(movimentacao_id):
    excluir_movimentacao_financeira(movimentacao_id)
    flash("Movimentação financeira excluída com sucesso.")
    return redirect(url_for("financeiro"))


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



# ============================================================
# RELATÓRIO DE RENDIMENTO
# ============================================================

@app.route("/relatorio-rendimento")
@perfil_permitido("pcp")
def relatorio_rendimento():
    criar_banco()

    agora = datetime.now()
    hoje = agora.strftime("%Y-%m-%d")
    primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

    data_inicio = request.args.get("data_inicio") or primeiro_dia_mes
    data_fim = request.args.get("data_fim") or hoje
    sku_filtro = request.args.get("sku") or "Todos"
    fornecedor_filtro = request.args.get("fornecedor") or "Todos"

    meta_rendimento = 63.0

    condicoes = [
        "o.data BETWEEN ? AND ?",
        "COALESCE(o.status, 'Aberta') = 'Encerrada'"
    ]
    parametros = [data_inicio, data_fim]

    if sku_filtro != "Todos":
        condicoes.append("COALESCE(o.sku, 'Galinha Cortada') = ?")
        parametros.append(sku_filtro)

    if fornecedor_filtro != "Todos":
        condicoes.append("o.fornecedor = ?")
        parametros.append(fornecedor_filtro)

    where_sql = " AND ".join(condicoes)

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        o.data,
        o.fornecedor,
        COALESCE(SUM(o.peso_vivo), 0) as peso_vivo,
        COALESCE(SUM(prod.kg_produzidos), 0) as kg_produzidos
    FROM ordens_producao o
    LEFT JOIN (
        SELECT
            op_id,
            COALESCE(SUM(quantidade), 0) as kg_produzidos
        FROM apontamentos_producao
        WHERE LOWER(unidade) = 'kg'
        GROUP BY op_id
    ) prod ON prod.op_id = o.id
    WHERE {where_sql}
    GROUP BY o.data, o.fornecedor
    ORDER BY o.data ASC, o.fornecedor ASC
    """), tuple(parametros))

    registros = cursor.fetchall()
    conn.close()

    datas = sorted({item["data"] for item in registros})
    fornecedores_grafico = sorted({item["fornecedor"] for item in registros})

    dados_por_chave = {}

    total_kg_produzidos = 0
    total_peso_vivo = 0
    tabela_linhas = []

    for item in registros:
        data = item["data"]
        fornecedor = item["fornecedor"]
        kg_produzidos = float(item["kg_produzidos"] or 0)
        peso_vivo = float(item["peso_vivo"] or 0)
        rendimento = (kg_produzidos / peso_vivo * 100) if peso_vivo > 0 else 0
        desvio_meta = rendimento - meta_rendimento

        total_kg_produzidos += kg_produzidos
        total_peso_vivo += peso_vivo

        linha = {
            "data": data,
            "fornecedor": fornecedor,
            "kg_produzidos": round(kg_produzidos, 2),
            "peso_vivo": round(peso_vivo, 2),
            "rendimento": round(rendimento, 2),
            "desvio_meta": round(desvio_meta, 2)
        }

        dados_por_chave[(data, fornecedor)] = linha
        tabela_linhas.append(linha)

    rendimento_medio = (
        total_kg_produzidos / total_peso_vivo * 100
        if total_peso_vivo > 0
        else 0
    )

    cores = [
        "#2563eb",
        "#16a34a",
        "#f97316",
        "#8b5cf6",
        "#0891b2",
        "#dc2626",
        "#64748b"
    ]

    datasets = []

    for indice, fornecedor in enumerate(fornecedores_grafico):
        dados_linha = []
        detalhes_linha = []

        for data in datas:
            linha = dados_por_chave.get((data, fornecedor))

            if linha:
                dados_linha.append(linha["rendimento"])
                detalhes_linha.append({
                    "kg_produzidos": linha["kg_produzidos"],
                    "peso_vivo": linha["peso_vivo"]
                })
            else:
                dados_linha.append(None)
                detalhes_linha.append(None)

        cor = cores[indice % len(cores)]

        datasets.append({
            "label": fornecedor,
            "data": dados_linha,
            "detalhes": detalhes_linha,
            "borderColor": cor,
            "backgroundColor": cor,
            "tension": 0.25,
            "pointRadius": 4,
            "pointHoverRadius": 6,
            "spanGaps": False
        })

    if datas:
        datasets.append({
            "label": f"Meta {formatar_percentual_br(meta_rendimento)}",
            "data": [meta_rendimento for _ in datas],
            "borderColor": "#111827",
            "backgroundColor": "#111827",
            "borderDash": [8, 6],
            "pointRadius": 0,
            "pointHoverRadius": 0,
            "tension": 0,
            "ehMeta": True
        })

    return render_template(
        "relatorio_rendimento.html",
        data_inicio=data_inicio,
        data_fim=data_fim,
        sku_filtro=sku_filtro,
        fornecedor_filtro=fornecedor_filtro,
        fornecedores=buscar_fornecedores(),
        skus=["Galinha Inteira", "Galinha Cortada"],
        datas=datas,
        datasets=datasets,
        tabela_linhas=tabela_linhas,
        rendimento_medio=round(rendimento_medio, 2),
        meta_rendimento=meta_rendimento,
        total_kg_produzidos=round(total_kg_produzidos, 2),
        total_peso_vivo=round(total_peso_vivo, 2)
    )


# ============================================================
# RELATÓRIO DE VIABILIDADE
# Etapa segura: tela inicial sem cálculo e sem consulta ao banco.
# ============================================================

@app.route("/relatorio-viabilidade")
@perfil_permitido("pcp")
def relatorio_viabilidade():
    return render_template("relatorio_viabilidade.html")


# ============================================================
# IMPORTAÇÃO OFICIAL DE MAIO/2026
# Rota temporária para carregar OPs + descartes via Excel.
# ============================================================

MOTIVOS_DESCARTE_IMPORTACAO_MAIO = [
    "Hematomas",
    "Contaminação no processo",
    "Aspecto repugnante",
    "Doença",
    "Cozimento",
    "Caquexia",
    "Fratura",
    "Carcaça incompleta",
    "Outra",
]


def normalizar_cabecalho_importacao(valor):
    if valor is None:
        return ""
    texto = str(valor).strip().lower()
    mapa = str.maketrans("áàâãéêíóôõúç", "aaaaeeiooouc")
    return texto.translate(mapa).replace("_", " ")


def valor_excel_para_data_texto(valor):
    if not valor:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%Y-%m-%d")
    texto = str(valor).strip()
    for formato in ["%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"]:
        try:
            return datetime.strptime(texto, formato).strftime("%Y-%m-%d")
        except Exception:
            pass
    raise ValueError(f"Data inválida: {valor}")


def numero_importacao(valor, padrao=0):
    if valor is None or str(valor).strip() == "":
        return padrao
    if isinstance(valor, str):
        valor = valor.replace("R$", "").replace(".", "").replace(",", ".").strip()
    return float(valor)


def inteiro_importacao(valor, padrao=0):
    return int(round(numero_importacao(valor, padrao)))


def texto_importacao(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def mapa_colunas_por_cabecalho(ws):
    cabecalhos = {}
    for idx, celula in enumerate(ws[1], start=1):
        cabecalhos[normalizar_cabecalho_importacao(celula.value)] = idx
    return cabecalhos


def localizar_coluna(cabecalhos, nomes_possiveis):
    for nome in nomes_possiveis:
        chave = normalizar_cabecalho_importacao(nome)
        if chave in cabecalhos:
            return cabecalhos[chave]
    return None


def ler_planilha_importacao_maio(arquivo_excel):
    wb = load_workbook(arquivo_excel, data_only=True)
    erros = []
    avisos = []
    ops = []
    descartes = []

    if "OPs" not in wb.sheetnames:
        return {"erros": ["A planilha precisa ter uma aba chamada OPs."], "avisos": [], "ops": [], "descartes": []}

    ws_ops = wb["OPs"]
    cab = mapa_colunas_por_cabecalho(ws_ops)
    col = {
        "data": localizar_coluna(cab, ["data"]),
        "sku": localizar_coluna(cab, ["sku"]),
        "fornecedor": localizar_coluna(cab, ["fornecedor"]),
        "gta": localizar_coluna(cab, ["gta"]),
        "nota_fiscal": localizar_coluna(cab, ["nota fiscal", "nf", "nota_fiscal"]),
        "quantidade_aves": localizar_coluna(cab, ["quantidade de aves", "aves", "quantidade_aves"]),
        "mortes_antes_pendura": localizar_coluna(cab, ["mortes antes da pendura", "mortes_antes_pendura"]),
        "peso_vivo": localizar_coluna(cab, ["peso vivo", "peso_vivo"]),
        "unidades_produzidas": localizar_coluna(cab, ["unidades produzidas", "unidades_produzidas"]),
        "kg_produzidos": localizar_coluna(cab, ["kg produzidos", "kg_produzidos"]),
        "observacoes": localizar_coluna(cab, ["observações", "observacoes", "obs"]),
    }

    for chave in ["data", "sku", "fornecedor", "quantidade_aves", "mortes_antes_pendura", "peso_vivo", "unidades_produzidas", "kg_produzidos"]:
        if not col.get(chave):
            erros.append(f"Aba OPs: coluna obrigatória ausente: {chave}.")

    if erros:
        return {"erros": erros, "avisos": avisos, "ops": ops, "descartes": descartes}

    for linha in range(2, ws_ops.max_row + 1):
        if not ws_ops.cell(linha, col["data"]).value:
            continue
        try:
            op = {
                "linha": linha,
                "data": valor_excel_para_data_texto(ws_ops.cell(linha, col["data"]).value),
                "sku": texto_importacao(ws_ops.cell(linha, col["sku"]).value) or "Galinha Cortada",
                "fornecedor": texto_importacao(ws_ops.cell(linha, col["fornecedor"]).value),
                "gta": texto_importacao(ws_ops.cell(linha, col["gta"]).value) if col.get("gta") else "",
                "nota_fiscal": texto_importacao(ws_ops.cell(linha, col["nota_fiscal"]).value) if col.get("nota_fiscal") else "",
                "quantidade_aves": inteiro_importacao(ws_ops.cell(linha, col["quantidade_aves"]).value),
                "mortes_antes_pendura": inteiro_importacao(ws_ops.cell(linha, col["mortes_antes_pendura"]).value),
                "peso_vivo": numero_importacao(ws_ops.cell(linha, col["peso_vivo"]).value),
                "unidades_produzidas": numero_importacao(ws_ops.cell(linha, col["unidades_produzidas"]).value),
                "kg_produzidos": numero_importacao(ws_ops.cell(linha, col["kg_produzidos"]).value),
                "observacoes": texto_importacao(ws_ops.cell(linha, col["observacoes"]).value) if col.get("observacoes") else "",
            }
            if not op["fornecedor"]:
                erros.append(f"Aba OPs linha {linha}: fornecedor vazio.")
            if op["quantidade_aves"] <= 0:
                erros.append(f"Aba OPs linha {linha}: quantidade de aves precisa ser maior que zero.")
            if op["peso_vivo"] <= 0:
                erros.append(f"Aba OPs linha {linha}: peso vivo precisa ser maior que zero.")
            if op["unidades_produzidas"] <= 0:
                erros.append(f"Aba OPs linha {linha}: unidades produzidas precisa ser maior que zero.")
            if op["kg_produzidos"] <= 0:
                erros.append(f"Aba OPs linha {linha}: kg produzidos está vazio ou zerado.")
            ops.append(op)
        except Exception as erro:
            erros.append(f"Aba OPs linha {linha}: {erro}")

    if "Descartes" in wb.sheetnames:
        ws_desc = wb["Descartes"]
        cab_desc = mapa_colunas_por_cabecalho(ws_desc)
        col_data = localizar_coluna(cab_desc, ["data"])
        if not col_data:
            erros.append("Aba Descartes: coluna Data ausente.")
        else:
            col_motivos = []
            for motivo in MOTIVOS_DESCARTE_IMPORTACAO_MAIO:
                c = localizar_coluna(cab_desc, [motivo])
                if c:
                    col_motivos.append((motivo, c))
            if not col_motivos:
                avisos.append("Aba Descartes existe, mas nenhum motivo conhecido foi encontrado.")
            for linha in range(2, ws_desc.max_row + 1):
                data_raw = ws_desc.cell(linha, col_data).value
                if not data_raw:
                    continue
                try:
                    data = valor_excel_para_data_texto(data_raw)
                    for motivo, c in col_motivos:
                        qtd = numero_importacao(ws_desc.cell(linha, c).value)
                        if qtd > 0:
                            descartes.append({
                                "linha": linha,
                                "data": data,
                                "setor": "Não informado",
                                "categoria": "Condenação / Descarte",
                                "motivo": motivo,
                                "quantidade": qtd,
                                "unidade": "aves",
                                "observacoes": "Importado da planilha oficial de maio/2026. Setor não informado na origem.",
                            })
                except Exception as erro:
                    erros.append(f"Aba Descartes linha {linha}: {erro}")
    else:
        avisos.append("A planilha não possui aba Descartes. Apenas OPs serão importadas.")

    if not ops:
        erros.append("Nenhuma OP válida encontrada para importação.")

    return {"erros": erros, "avisos": avisos, "ops": ops, "descartes": descartes}


def resumir_importacao_maio(dados):
    ops = dados.get("ops", [])
    descartes = dados.get("descartes", [])
    total_descartes = sum(item["quantidade"] for item in descartes)
    motivos = {}
    for item in descartes:
        motivos[item["motivo"]] = motivos.get(item["motivo"], 0) + item["quantidade"]
    return {
        "total_ops": len(ops),
        "total_aves": round(sum(op["quantidade_aves"] for op in ops), 2),
        "total_mortes": round(sum(op["mortes_antes_pendura"] for op in ops), 2),
        "total_peso_vivo": round(sum(op["peso_vivo"] for op in ops), 2),
        "total_unidades": round(sum(op["unidades_produzidas"] for op in ops), 2),
        "total_kg": round(sum(op["kg_produzidos"] for op in ops), 2),
        "total_descartes": round(total_descartes, 2),
        "motivos": [
            {"motivo": m, "quantidade": round(q, 2), "percentual": round((q / total_descartes * 100), 2) if total_descartes > 0 else 0}
            for m, q in sorted(motivos.items(), key=lambda par: par[1], reverse=True)
        ],
    }


def obter_id_inserido(cursor):
    if DATABASE_URL:
        cursor.execute("SELECT LASTVAL() as id")
        return cursor.fetchone()["id"]
    return cursor.lastrowid


def excluir_historico_maio_2026(cursor):
    cursor.execute(q("""
    SELECT id FROM ordens_producao
    WHERE data BETWEEN ? AND ?
      AND observacoes LIKE ?
    """), ("2026-05-01", "2026-05-31", "%Importação oficial Maio/2026%"))
    ids = [item["id"] for item in cursor.fetchall()]
    if not ids:
        return 0
    placeholders = ",".join(["?"] * len(ids))
    for tabela in ["apontamentos_setor", "apontamentos_producao", "apontamentos_mao_obra", "apontamentos_paradas", "apontamentos_descartes", "apontamentos_tempos_setor"]:
        cursor.execute(q(f"DELETE FROM {tabela} WHERE op_id IN ({placeholders})"), tuple(ids))
    cursor.execute(q(f"DELETE FROM ordens_producao WHERE id IN ({placeholders})"), tuple(ids))
    return len(ids)


def importar_dados_oficiais_maio(dados, substituir=True):
    criar_banco()
    criar_tabela_tempos_setor()
    if dados.get("erros"):
        raise ValueError("A planilha possui erros de validação e não pode ser importada.")
    conn = conectar()
    cursor = conn.cursor()
    try:
        removidas = excluir_historico_maio_2026(cursor) if substituir else 0
        op_por_data = {}
        ops_importadas = 0
        descartes_importados = 0
        for op in dados["ops"]:
            peso_medio = op["peso_vivo"] / op["quantidade_aves"] if op["quantidade_aves"] else 0
            obs = (op.get("observacoes") or "").strip()
            obs = (obs + " | " if obs else "") + "Importação oficial Maio/2026"
            cursor.execute(q("""
            INSERT INTO ordens_producao (
                data, sku, fornecedor, gta, nota_fiscal, quantidade_aves,
                mortes_antes_pendura, peso_vivo, peso_medio, observacoes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """), (op["data"], op["sku"], op["fornecedor"], op["gta"], op["nota_fiscal"], op["quantidade_aves"], op["mortes_antes_pendura"], op["peso_vivo"], peso_medio, obs, "Encerrada"))
            op_id = obter_id_inserido(cursor)
            op_por_data[op["data"]] = op_id
            ops_importadas += 1
            cursor.execute(q("""
            INSERT INTO apontamentos_producao (op_id, data, setor, quantidade, unidade, observacoes)
            VALUES (?, ?, ?, ?, ?, ?)
            """), (op_id, op["data"], "Expedição", op["unidades_produzidas"], "unidades", "Produção final importada da planilha oficial de maio/2026."))
            cursor.execute(q("""
            INSERT INTO apontamentos_producao (op_id, data, setor, quantidade, unidade, observacoes)
            VALUES (?, ?, ?, ?, ?, ?)
            """), (op_id, op["data"], "Expedição", op["kg_produzidos"], "kg", "Kg final produzido importado da planilha oficial de maio/2026."))
        for descarte in dados["descartes"]:
            op_id = op_por_data.get(descarte["data"])
            if not op_id:
                continue
            cursor.execute(q("""
            INSERT INTO apontamentos_descartes (op_id, data, setor, categoria, motivo, quantidade, unidade, observacoes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """), (op_id, descarte["data"], descarte["setor"], descarte["categoria"], descarte["motivo"], descarte["quantidade"], descarte["unidade"], descarte["observacoes"]))
            descartes_importados += 1
        conn.commit()
        conn.close()
        return {"removidas": removidas, "ops_importadas": ops_importadas, "descartes_importados": descartes_importados}
    except Exception:
        conn.rollback()
        conn.close()
        raise


@app.route("/importar-maio", methods=["GET", "POST"])
@perfil_permitido("pcp")
def importar_maio():
    resultado = None
    resumo = None
    erros = []
    avisos = []
    importado = False
    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        acao = request.form.get("acao", "validar")
        substituir = request.form.get("substituir") == "sim"
        if not arquivo or not arquivo.filename:
            erros.append("Selecione a planilha de maio em Excel.")
        else:
            try:
                dados = ler_planilha_importacao_maio(arquivo)
                erros = dados.get("erros", [])
                avisos = dados.get("avisos", [])
                resumo = resumir_importacao_maio(dados)
                if acao == "importar" and not erros:
                    if not substituir:
                        erros.append("Marque a confirmação de substituição segura dos dados oficiais de Maio/2026 importados anteriormente.")
                    else:
                        resultado = importar_dados_oficiais_maio(dados, substituir=True)
                        importado = True
                        flash("Importação oficial de Maio/2026 concluída com sucesso.")
            except Exception as erro:
                erros.append(str(erro))
    return render_template("importar_maio.html", resumo=resumo, erros=erros, avisos=avisos, resultado=resultado, importado=importado)


if __name__ == "__main__":
    criar_banco()
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
