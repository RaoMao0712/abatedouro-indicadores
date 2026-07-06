from flask import Flask
from werkzeug.security import generate_password_hash
from functools import wraps
import os
import sqlite3
import threading
from database import DATABASE_URL, DB_NAME, conectar, inicializar_schema_uma_vez, q
from database.migrations import executar_alteracao_segura
from modules.auth import register_auth_routes
from modules.usuarios import register_usuarios_routes
from modules.manutencao import register_manutencao_routes
from modules.cadastros import register_cadastros_routes
from modules.cadastros.services import criar_tabela_vendas, criar_tabelas_receitas_sku, criar_tabela_fornecedores
from modules.importacao_oficial import register_importacao_routes
from modules.dashboard.routes import register_dashboard_routes
from modules.custos.routes import register_custos_routes
from modules.dre.routes import register_dre_routes
from modules.fluxo_caixa.routes import register_fluxo_caixa_routes
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
from modules.almoxarifado.services import (
    criar_tabelas_almoxarifado,
    criar_tabelas_estoque_almoxarifado,
)
from modules.custos.services import criar_tabelas_custos
from modules.manutencao import services as manutencao_service

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
register_usuarios_routes(app, criar_banco)
register_cadastros_routes(app)
register_dashboard_routes(app)
register_custos_routes(app)
register_dre_routes(app, {
    "criar_tabela_vendas": lambda: criar_tabela_vendas(),
})
register_relatorios_routes(app)
register_fluxo_caixa_routes(app)


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

# ============================================================
# IMPORTAÇÃO OFICIAL DE MAIO/2026
# Rota temporária para carregar OPs + descartes via Excel.
# ============================================================

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
register_manutencao_routes(app)
register_importacao_routes(app, {
    "criar_banco": criar_banco,
    "criar_tabela_tempos_setor": criar_tabela_tempos_setor,
})

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
