"""Servicos de Financeiro e Movimentacoes."""

import calendar
import uuid
from datetime import datetime

from database import DATABASE_URL, conectar, q
from database.migrations import executar_alteracao_segura
from modules.financeiro.services import (
    categorias_entradas_financeiras,
    categorias_saidas_financeiras,
)


def tentar_alter_table(cursor, conn, comando):
    executar_alteracao_segura(cursor, conn, comando)


CATEGORIAS_FINANCEIRAS_ENTRADA = categorias_entradas_financeiras()
CATEGORIAS_FINANCEIRAS_SAIDA = categorias_saidas_financeiras()


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
