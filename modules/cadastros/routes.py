"""Cadastros operacionais ainda preservados com endpoints legados."""

from datetime import datetime
from functools import wraps
import os
import threading

from flask import flash, redirect, render_template, request, url_for

from database import DATABASE_URL, DB_NAME, conectar, q
from database.migrations import executar_alteracao_segura
from modules.auth.decorators import perfil_permitido
from modules.almoxarifado.services import (
    buscar_insumos_almoxarifado,
    criar_tabelas_estoque_almoxarifado,
)



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



def register_cadastros_routes(app):
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
