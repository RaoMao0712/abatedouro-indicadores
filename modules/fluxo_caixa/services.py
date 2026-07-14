"""Servicos do Fluxo de Caixa.

O modulo usa exclusivamente movimentacoes_financeiras. A leitura prevista usa
data_vencimento; a leitura realizada usa data_realizacao.
"""

from datetime import datetime

from database import conectar, q
from modules.movimentacoes.services import criar_tabela_movimentacoes_financeiras


STATUS_FLUXO_CAIXA = ["Todos", "Pendente", "Recebido", "Pago", "Cancelado"]
TIPOS_FLUXO_CAIXA = ["Todos", "Entrada", "Saida"]
STATUS_REALIZADOS_SQL = ("Pago", "Recebido", "Realizado")


def _hoje():
    return datetime.now()


def normalizar_filtros(args):
    agora = _hoje()
    hoje = agora.strftime("%Y-%m-%d")
    primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

    data_inicio = args.get("data_inicio") or primeiro_dia_mes
    data_fim = args.get("data_fim") or hoje
    status = args.get("status") or "Todos"
    categoria = args.get("categoria") or "Todas"
    tipo = args.get("tipo") or "Todos"

    if status not in STATUS_FLUXO_CAIXA:
        status = "Todos"

    if tipo not in TIPOS_FLUXO_CAIXA:
        tipo = "Todos"

    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "status_filtro": status,
        "categoria_filtro": categoria,
        "tipo_filtro": tipo,
    }


def _status_fluxo(item):
    status = (item.get("status") if hasattr(item, "get") else item["status"]) or "Pendente"
    tipo = (item.get("tipo") if hasattr(item, "get") else item["tipo"]) or ""

    if status == "Cancelado":
        return "Cancelado"

    if status in ["Pago", "Recebido"]:
        return status

    if status == "Realizado":
        return "Recebido" if tipo == "Entrada" else "Pago"

    return "Pendente"


def _status_realizado_fluxo(item):
    status = _status_fluxo(item)
    tipo = (item.get("tipo") if hasattr(item, "get") else item["tipo"]) or ""
    return (tipo == "Entrada" and status == "Recebido") or (tipo == "Saida" and status == "Pago")


def _tipo_fluxo(item):
    tipo = (item.get("tipo") if hasattr(item, "get") else item["tipo"]) or ""
    if tipo == "Entrada":
        return "Entrada"
    return "Saida"


def _classe_status(status):
    return (
        status.lower()
        .replace(" ", "-")
        .replace("i", "i")
    )


def listar_categorias_fluxo_caixa():
    criar_tabela_movimentacoes_financeiras()

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT DISTINCT categoria
    FROM movimentacoes_financeiras
    WHERE categoria IS NOT NULL
      AND categoria <> ''
    ORDER BY categoria
    """))
    categorias = [item["categoria"] for item in cursor.fetchall()]
    conn.close()
    return categorias


def _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro):
    condicoes = []
    parametros = []

    if tipo_filtro == "Entrada":
        condicoes.append("tipo = ?")
        parametros.append("Entrada")
    elif tipo_filtro == "Saida":
        condicoes.append("COALESCE(tipo, '') <> ?")
        parametros.append("Entrada")

    if categoria_filtro and categoria_filtro != "Todas":
        condicoes.append("categoria = ?")
        parametros.append(categoria_filtro)

    return condicoes, parametros


def buscar_movimentacoes_fluxo_caixa(data_inicio, data_fim, tipo_filtro, categoria_filtro):
    criar_tabela_movimentacoes_financeiras()

    condicoes = ["data_vencimento BETWEEN ? AND ?"]
    parametros = [data_inicio, data_fim]
    filtros, parametros_filtros = _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro)
    condicoes.extend(filtros)
    parametros.extend(parametros_filtros)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes)}
    ORDER BY data_vencimento ASC, id ASC
    """), tuple(parametros))
    movimentacoes = cursor.fetchall()
    conn.close()

    return [preparar_movimentacao_fluxo(item) for item in movimentacoes]


def buscar_movimentacoes_realizadas_fluxo_caixa(data_inicio, data_fim, tipo_filtro, categoria_filtro):
    criar_tabela_movimentacoes_financeiras()

    condicoes = [
        "data_realizacao BETWEEN ? AND ?",
        "COALESCE(data_realizacao, '') <> ?",
        "COALESCE(status, 'Pendente') IN (?, ?, ?)",
    ]
    parametros = [data_inicio, data_fim, "", *STATUS_REALIZADOS_SQL]
    filtros, parametros_filtros = _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro)
    condicoes.extend(filtros)
    parametros.extend(parametros_filtros)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes)}
    ORDER BY data_realizacao ASC, id ASC
    """), tuple(parametros))
    movimentacoes = cursor.fetchall()
    conn.close()

    return [
        item for item in [preparar_movimentacao_fluxo(item) for item in movimentacoes]
        if item["realizado"]
    ]


def _somar_impacto(movimentacoes):
    saldo = 0
    for item in movimentacoes:
        if item["status_fluxo"] == "Cancelado":
            continue
        saldo += float(item["valor"] or 0) * item["sinal"]

    return round(saldo, 2)


def buscar_saldos_iniciais(data_inicio, tipo_filtro="Todos", categoria_filtro="Todas"):
    criar_tabela_movimentacoes_financeiras()

    filtros, parametros_filtros = _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro)

    condicoes_previsto = [
        "data_vencimento < ?",
        "COALESCE(status, 'Pendente') <> ?",
    ] + filtros
    parametros_previsto = [data_inicio, "Cancelado"] + parametros_filtros

    condicoes_realizado = [
        "data_realizacao < ?",
        "COALESCE(data_realizacao, '') <> ?",
        "COALESCE(status, 'Pendente') <> ?",
    ] + filtros
    parametros_realizado = [data_inicio, "", "Cancelado"] + parametros_filtros

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT
        COALESCE(SUM(CASE
            WHEN tipo = ? THEN valor
            ELSE -valor
        END), 0) AS saldo
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes_previsto)}
    """), ("Entrada", *parametros_previsto))
    saldo_previsto = float(cursor.fetchone()["saldo"] or 0)

    cursor.execute(q(f"""
    SELECT
        COALESCE(SUM(CASE
            WHEN tipo = ? THEN valor
            ELSE -valor
        END), 0) AS saldo
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes_realizado)}
      AND COALESCE(status, 'Pendente') IN (?, ?, ?)
    """), ("Entrada", *parametros_realizado, *STATUS_REALIZADOS_SQL))
    saldo_realizado = float(cursor.fetchone()["saldo"] or 0)
    conn.close()

    return {
        "saldo_inicial_previsto": round(saldo_previsto, 2),
        "saldo_inicial_realizado": round(saldo_realizado, 2),
        "memoria_previsto": [],
        "memoria_realizado": [],
    }


def buscar_saldo_inicial(data_inicio):
    return buscar_saldos_iniciais(data_inicio)["saldo_inicial_realizado"]


def preparar_movimentacao_fluxo(item):
    item_dict = dict(item)
    tipo = _tipo_fluxo(item_dict)
    status_fluxo = _status_fluxo(item_dict)
    valor = float(item_dict.get("valor") or 0)

    item_dict["tipo"] = tipo
    item_dict["valor"] = valor
    item_dict["status_fluxo"] = status_fluxo
    item_dict["status_classe"] = _classe_status(status_fluxo)
    item_dict["realizado"] = _status_realizado_fluxo(item_dict)
    item_dict["sinal"] = 1 if tipo == "Entrada" else -1
    item_dict["valor_assinado"] = valor * item_dict["sinal"]

    return item_dict


def filtrar_por_status(movimentacoes, status_filtro):
    if status_filtro == "Todos":
        return [
            item for item in movimentacoes
            if item["status_fluxo"] != "Cancelado"
        ]

    return [
        item for item in movimentacoes
        if item["status_fluxo"] == status_filtro
    ]


def calcular_resumo_fluxo_caixa(movimentacoes_previstas, movimentacoes_realizadas, saldos_iniciais):
    entradas_previstas = 0
    saidas_previstas = 0
    entradas_realizadas = 0
    saidas_realizadas = 0

    for item in movimentacoes_previstas:
        if item["status_fluxo"] == "Cancelado":
            continue

        valor = float(item["valor"] or 0)

        if item["tipo"] == "Entrada":
            entradas_previstas += valor
        elif item["tipo"] == "Saida":
            saidas_previstas += valor

    for item in movimentacoes_realizadas:
        if item["status_fluxo"] == "Cancelado":
            continue

        valor = float(item["valor"] or 0)

        if item["tipo"] == "Entrada":
            entradas_realizadas += valor
        elif item["tipo"] == "Saida":
            saidas_realizadas += valor

    saldo_inicial_previsto = saldos_iniciais["saldo_inicial_previsto"]
    saldo_inicial_realizado = saldos_iniciais["saldo_inicial_realizado"]
    saldo_previsto = saldo_inicial_previsto + entradas_previstas - saidas_previstas
    saldo_realizado = saldo_inicial_realizado + entradas_realizadas - saidas_realizadas

    return {
        "saldo_inicial": round(saldo_inicial_realizado, 2),
        "saldo_inicial_previsto": round(saldo_inicial_previsto, 2),
        "saldo_inicial_realizado": round(saldo_inicial_realizado, 2),
        "entradas_previstas": round(entradas_previstas, 2),
        "saidas_previstas": round(saidas_previstas, 2),
        "saldo_previsto": round(saldo_previsto, 2),
        "entradas_realizadas": round(entradas_realizadas, 2),
        "saidas_realizadas": round(saidas_realizadas, 2),
        "saldo_realizado": round(saldo_realizado, 2),
    }


def montar_linha_tempo(movimentacoes_previstas, movimentacoes_realizadas, saldos_iniciais):
    por_data = {}
    saldo_previsto = saldos_iniciais["saldo_inicial_previsto"]
    saldo_realizado = saldos_iniciais["saldo_inicial_realizado"]

    for item in movimentacoes_previstas:
        if item["status_fluxo"] == "Cancelado":
            continue

        data = item.get("data_vencimento")
        if data not in por_data:
            por_data[data] = {
                "data": data,
                "entradas_previstas": 0,
                "saidas_previstas": 0,
                "entradas_realizadas": 0,
                "saidas_realizadas": 0,
                "saldo_previsto": 0,
                "saldo_realizado": 0,
            }

        valor = float(item["valor"] or 0)
        if item["tipo"] == "Entrada":
            por_data[data]["entradas_previstas"] += valor
        elif item["tipo"] == "Saida":
            por_data[data]["saidas_previstas"] += valor

    for item in movimentacoes_realizadas:
        if item["status_fluxo"] == "Cancelado":
            continue

        data = item.get("data_realizacao")
        if not data:
            continue
        if data not in por_data:
            por_data[data] = {
                "data": data,
                "entradas_previstas": 0,
                "saidas_previstas": 0,
                "entradas_realizadas": 0,
                "saidas_realizadas": 0,
                "saldo_previsto": 0,
                "saldo_realizado": 0,
            }

        valor = float(item["valor"] or 0)
        if item["tipo"] == "Entrada":
            por_data[data]["entradas_realizadas"] += valor
        elif item["tipo"] == "Saida":
            por_data[data]["saidas_realizadas"] += valor

    linha_tempo = []
    for data in sorted(por_data):
        item = por_data[data]
        saldo_previsto += item["entradas_previstas"] - item["saidas_previstas"]
        saldo_realizado += item["entradas_realizadas"] - item["saidas_realizadas"]
        item["saldo_previsto"] = round(saldo_previsto, 2)
        item["saldo_realizado"] = round(saldo_realizado, 2)
        for chave in [
            "entradas_previstas",
            "saidas_previstas",
            "entradas_realizadas",
            "saidas_realizadas",
        ]:
            item[chave] = round(item[chave], 2)
        linha_tempo.append(item)

    return linha_tempo


def montar_contexto_fluxo_caixa(args):
    filtros = normalizar_filtros(args)
    saldos_iniciais = buscar_saldos_iniciais(
        filtros["data_inicio"],
        filtros["tipo_filtro"],
        filtros["categoria_filtro"],
    )
    movimentacoes_periodo_previstas = buscar_movimentacoes_fluxo_caixa(
        filtros["data_inicio"],
        filtros["data_fim"],
        filtros["tipo_filtro"],
        filtros["categoria_filtro"],
    )
    movimentacoes_periodo_realizadas = buscar_movimentacoes_realizadas_fluxo_caixa(
        filtros["data_inicio"],
        filtros["data_fim"],
        filtros["tipo_filtro"],
        filtros["categoria_filtro"],
    )
    movimentacoes = filtrar_por_status(movimentacoes_periodo_previstas, filtros["status_filtro"])
    movimentacoes_realizadas = filtrar_por_status(movimentacoes_periodo_realizadas, filtros["status_filtro"])

    return {
        **filtros,
        "status_opcoes": STATUS_FLUXO_CAIXA,
        "tipo_opcoes": TIPOS_FLUXO_CAIXA,
        "categorias": listar_categorias_fluxo_caixa(),
        "resumo": calcular_resumo_fluxo_caixa(movimentacoes, movimentacoes_realizadas, saldos_iniciais),
        "linha_tempo": montar_linha_tempo(movimentacoes, movimentacoes_realizadas, saldos_iniciais),
        "movimentacoes": movimentacoes,
        "conta_disponivel": False,
    }
