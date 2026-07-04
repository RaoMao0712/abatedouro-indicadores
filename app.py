from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
from functools import wraps
import calendar
from io import BytesIO
import os
import uuid
import sqlite3
import threading
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from database import DATABASE_URL, DB_NAME, conectar, inicializar_schema_uma_vez, q
from database.migrations import executar_alteracao_segura
from modules.auth import register_auth_routes
from modules.auth.decorators import perfil_permitido
from modules.auth.services import nome_usuario_atual, usuario_eh_admin
from modules.dashboard.routes import register_dashboard_routes
from modules.custos.routes import register_custos_routes
from modules.dre.routes import register_dre_routes
from modules.relatorios.routes import register_relatorios_routes
from modules.expedicao.routes import register_expedicao_routes
from modules.movimentacoes.routes import register_movimentacoes_routes
from modules.producao.routes import register_producao_routes
from modules.qualidade.routes import register_qualidade_routes
from modules.almoxarifado.routes import register_almoxarifado_routes
from modules.expedicao.services import (
    criar_tabelas_expedicao,
    criar_tabelas_estoque_pi_pa,
    op_possui_caixa_pa,
    remover_movimentacoes_estoque_pi_por_op,
)
from modules.movimentacoes.services import criar_tabela_movimentacoes_financeiras
from modules.producao.services import buscar_op_por_id, gerar_producao_automatica_setores
from modules.almoxarifado.services import (
    buscar_insumos_almoxarifado,
    criar_tabelas_almoxarifado,
    criar_tabelas_estoque_almoxarifado,
)
from modules.custos.services import criar_tabelas_custos
from services import manutencao_service
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


ROTINAS_ESTRUTURAIS_EXECUTADAS = set()
ROTINAS_ESTRUTURAIS_LOCK = threading.RLock()


def executar_rotina_estrutural_uma_vez(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        destino_banco = DATABASE_URL or os.path.abspath(DB_NAME)
        chave = (func.__name__, destino_banco)

        with ROTINAS_ESTRUTURAIS_LOCK:
            if chave in ROTINAS_ESTRUTURAIS_EXECUTADAS:
                return None

            resultado = func(*args, **kwargs)
            ROTINAS_ESTRUTURAIS_EXECUTADAS.add(chave)
            return resultado

    return wrapper




def tentar_alter_table(cursor, conn, comando):
    executar_alteracao_segura(cursor, conn, comando)


@executar_rotina_estrutural_uma_vez
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
        tentar_alter_table(cursor, conn, "ALTER TABLE apontamentos_paradas ADD COLUMN manutencao_ordem_id INTEGER")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE apontamentos_paradas ADD COLUMN manutencao_aberta TEXT DEFAULT 'Nao'")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE apontamentos_paradas ADD COLUMN encerrada_por_manutencao TEXT DEFAULT 'Nao'")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE apontamentos_paradas ADD COLUMN data_fim TEXT")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE apontamentos_paradas ADD COLUMN equipamento TEXT")
        conn = conectar()
        cursor = conn.cursor()
        tentar_alter_table(cursor, conn, "ALTER TABLE apontamentos_paradas ADD COLUMN equipamento_id INTEGER")
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

        try:
            cursor.execute("ALTER TABLE apontamentos_paradas ADD COLUMN manutencao_ordem_id INTEGER")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE apontamentos_paradas ADD COLUMN manutencao_aberta TEXT DEFAULT 'Nao'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE apontamentos_paradas ADD COLUMN encerrada_por_manutencao TEXT DEFAULT 'Nao'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE apontamentos_paradas ADD COLUMN data_fim TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE apontamentos_paradas ADD COLUMN equipamento TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE apontamentos_paradas ADD COLUMN equipamento_id INTEGER")
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


register_auth_routes(app, criar_banco)
register_dashboard_routes(app)
register_custos_routes(app)
register_dre_routes(app, {
    "criar_tabela_vendas": lambda: criar_tabela_vendas(),
})
register_relatorios_routes(app)


@executar_rotina_estrutural_uma_vez
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



@app.route("/vendas", methods=["GET", "POST"])
@perfil_permitido("pcp")
def vendas():
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



@app.route("/vendas/<int:venda_id>/editar", methods=["GET", "POST"])
@perfil_permitido("pcp")
def editar_venda_diaria(venda_id):
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


@executar_rotina_estrutural_uma_vez
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

@executar_rotina_estrutural_uma_vez
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

@app.route("/fornecedores", methods=["GET", "POST"])
@perfil_permitido("pcp")
def fornecedores():
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


@app.route("/cadastros/equipamentos", methods=["GET", "POST"])
@perfil_permitido("pcp", "producao")
def cadastro_equipamentos_manutencao():
    if request.method == "POST":
        try:
            manutencao_service.salvar_equipamento_manutencao(request.form)
            flash("Equipamento cadastrado com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("cadastro_equipamentos_manutencao"))

    return render_template(
        "cadastro_equipamentos.html",
        **manutencao_service.preparar_contexto_cadastro_equipamentos(request.args)
    )


@app.route("/cadastros/equipamentos/<int:equipamento_id>/editar", methods=["POST"])
@perfil_permitido("pcp", "producao")
def editar_equipamento_manutencao(equipamento_id):
    try:
        manutencao_service.atualizar_equipamento_manutencao(equipamento_id, request.form)
        flash("Equipamento atualizado com sucesso.")
    except Exception as erro:
        flash(str(erro))

    return redirect(url_for("cadastro_equipamentos_manutencao", busca=request.form.get("busca", "")))


@app.route("/cadastros/equipamentos/<int:equipamento_id>/excluir", methods=["POST"])
@perfil_permitido("pcp", "producao")
def excluir_equipamento_manutencao(equipamento_id):
    try:
        manutencao_service.excluir_equipamento_manutencao(equipamento_id)
        flash("Equipamento removido com sucesso.")
    except Exception as erro:
        flash(str(erro))

    return redirect(url_for("cadastro_equipamentos_manutencao", busca=request.form.get("busca", "")))


@app.route("/manutencao", methods=["GET", "POST"])
@perfil_permitido("pcp", "producao")
def manutencao():
    if request.method == "POST":
        try:
            manutencao_service.salvar_ordem_manutencao(request.form)
            flash("Ordem de manutencao aberta com sucesso.")
        except Exception as erro:
            flash(str(erro))

        return redirect(url_for("manutencao"))

    return render_template(
        "manutencao.html",
        **manutencao_service.preparar_contexto_manutencao(request.args)
    )


@app.route("/manutencao/ordem/<int:ordem_id>/atualizar", methods=["POST"])
@perfil_permitido("pcp", "producao")
def atualizar_ordem_manutencao_rota(ordem_id):
    try:
        manutencao_service.atualizar_ordem_manutencao(ordem_id, request.form)
        flash("Ordem de manutencao atualizada com sucesso.")
    except Exception as erro:
        flash(str(erro))

    return redirect(url_for("manutencao"))


@app.route("/manutencao/ordem/<int:ordem_id>/recursos", methods=["POST"])
@perfil_permitido("pcp", "producao")
def salvar_recursos_ordem_manutencao_rota(ordem_id):
    try:
        manutencao_service.salvar_recursos_ordem_manutencao(ordem_id, request.form)
        flash("Lista de materiais e terceiros atualizada com sucesso.")
    except Exception as erro:
        flash(str(erro))

    return redirect(url_for(
        "manutencao",
        status=request.form.get("status_filtro", "Todos"),
        equipamento_id=request.form.get("equipamento_filtro", ""),
    ))


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
        "mortes_antes_pendura": localizar_coluna(cab, ["mortes na gaiola", "mortes_antes_pendura"]),
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


register_producao_routes(app, {
    "op_possui_caixa_pa": op_possui_caixa_pa,
    "remover_movimentacoes_estoque_pi_por_op": remover_movimentacoes_estoque_pi_por_op,
})

register_qualidade_routes(app, {
    "criar_banco": criar_banco,
})

register_almoxarifado_routes(app)

register_expedicao_routes(app, {
    "criar_banco": criar_banco,
})

register_movimentacoes_routes(app)

def inicializar_schema_aplicacao():
    inicializar_schema_uma_vez([
        criar_banco,
        criar_tabela_tempos_setor,
        criar_tabelas_custos,
        criar_tabela_vendas,
        criar_tabelas_expedicao,
        criar_tabelas_estoque_pi_pa,
        criar_tabelas_almoxarifado,
        criar_tabelas_estoque_almoxarifado,
        criar_tabelas_receitas_sku,
        criar_tabela_movimentacoes_financeiras,
        criar_tabela_fornecedores,
        manutencao_service.criar_tabelas_manutencao,
    ])


inicializar_schema_aplicacao()


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
