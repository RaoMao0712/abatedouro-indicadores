"""Servicos do Fluxo de Caixa.

O modulo usa exclusivamente movimentacoes_financeiras. A leitura prevista usa
data_vencimento; a leitura realizada usa data_realizacao.
"""

from datetime import datetime

from database import conectar, q
from modules.financeiro.services import listar_plano_contas
from modules.movimentacoes.services import criar_tabela_movimentacoes_financeiras


STATUS_FLUXO_CAIXA = ["Todos", "Pendente", "Recebido", "Pago", "Cancelado"]
TIPOS_FLUXO_CAIXA = ["Todos", "Entrada", "Saida"]
STATUS_REALIZADOS_SQL = ("Pago", "Recebido", "Realizado")
AGRUPAMENTOS_CATEGORIA_FLUXO = {
    "Manutencao": [
        "Manutencao de Equipamentos",
        "Manutencao de Veiculos",
        "Manutencao Predial",
    ],
}
SUBCATEGORIA_POR_CATEGORIA_AGRUPADA = {
    categoria_filha: categoria_filha
    for categorias in AGRUPAMENTOS_CATEGORIA_FLUXO.values()
    for categoria_filha in categorias
}
CATEGORIA_AGRUPADA_POR_FILHA = {
    categoria_filha: categoria_pai
    for categoria_pai, categorias in AGRUPAMENTOS_CATEGORIA_FLUXO.items()
    for categoria_filha in categorias
}


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
    subcategoria = args.get("subcategoria") or "Todas"
    tipo = args.get("tipo") or "Todos"

    if status not in STATUS_FLUXO_CAIXA:
        status = "Todos"

    if tipo not in TIPOS_FLUXO_CAIXA:
        tipo = "Todos"

    if categoria == "Todas":
        subcategoria = "Todas"

    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "status_filtro": status,
        "categoria_filtro": categoria,
        "subcategoria_filtro": subcategoria,
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

    categorias_plano = [
        conta["categoria"]
        for conta in listar_plano_contas()
        if conta.get("impacta_fluxo_caixa") and conta.get("categoria")
    ]

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT DISTINCT COALESCE(NULLIF(categoria_plano, ''), categoria) as categoria
    FROM movimentacoes_financeiras
    WHERE COALESCE(NULLIF(categoria_plano, ''), categoria) IS NOT NULL
      AND COALESCE(NULLIF(categoria_plano, ''), categoria) <> ''
      AND COALESCE(impacta_fluxo_caixa, 1) = 1
    ORDER BY categoria
    """))
    categorias_movimentadas = [item["categoria"] for item in cursor.fetchall()]
    conn.close()
    categorias = set()
    categorias_fragmentadas = set(CATEGORIA_AGRUPADA_POR_FILHA)
    for categoria in categorias_plano + categorias_movimentadas:
        if not categoria:
            continue
        categorias.add(CATEGORIA_AGRUPADA_POR_FILHA.get(categoria, categoria))
    return sorted(categoria for categoria in categorias if categoria not in categorias_fragmentadas)


def listar_subcategorias_fluxo_caixa(categoria_filtro):
    if not categoria_filtro or categoria_filtro == "Todas":
        return []

    criar_tabela_movimentacoes_financeiras()
    subcategorias_plano = [
        conta["subcategoria"]
        for conta in listar_plano_contas()
        if conta.get("impacta_fluxo_caixa")
        and conta.get("categoria") == categoria_filtro
        and conta.get("subcategoria")
    ]

    if categoria_filtro in AGRUPAMENTOS_CATEGORIA_FLUXO:
        subcategorias_plano.extend(AGRUPAMENTOS_CATEGORIA_FLUXO[categoria_filtro])

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT DISTINCT COALESCE(NULLIF(subcategoria, ''), '') as subcategoria
    FROM movimentacoes_financeiras
    WHERE (
        COALESCE(NULLIF(categoria_plano, ''), categoria) = ?
        OR categoria = ?
        OR categoria LIKE ?
      )
      AND COALESCE(NULLIF(subcategoria, ''), '') <> ''
      AND COALESCE(impacta_fluxo_caixa, 1) = 1
    ORDER BY subcategoria
    """), (categoria_filtro, categoria_filtro, f"{categoria_filtro} - %"))
    subcategorias_movimentadas = [item["subcategoria"] for item in cursor.fetchall()]
    conn.close()
    return sorted({item for item in subcategorias_plano + subcategorias_movimentadas if item})


def categoria_fluxo_sql(categoria_filtro):
    return AGRUPAMENTOS_CATEGORIA_FLUXO.get(categoria_filtro, [categoria_filtro])


def _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro, subcategoria_filtro="Todas"):
    condicoes = []
    parametros = []

    if tipo_filtro == "Entrada":
        condicoes.append("tipo = ?")
        parametros.append("Entrada")
    elif tipo_filtro == "Saida":
        condicoes.append("COALESCE(tipo, '') <> ?")
        parametros.append("Entrada")

    if categoria_filtro and categoria_filtro != "Todas":
        categorias_consulta = categoria_fluxo_sql(categoria_filtro)
        condicoes_categoria = []
        for categoria_consulta in categorias_consulta:
            condicoes_categoria.append("""(
                COALESCE(NULLIF(categoria_plano, ''), categoria) = ?
                OR categoria = ?
                OR categoria LIKE ?
            )""")
            parametros.extend([categoria_consulta, categoria_consulta, f"{categoria_consulta} - %"])
        condicoes.append("(" + " OR ".join(condicoes_categoria) + ")")

        if subcategoria_filtro and subcategoria_filtro != "Todas":
            condicoes.append("""(
                COALESCE(NULLIF(subcategoria, ''), '') = ?
                OR categoria = ?
                OR COALESCE(NULLIF(categoria_plano, ''), categoria) = ?
            )""")
            parametros.extend([subcategoria_filtro, f"{categoria_filtro} - {subcategoria_filtro}", subcategoria_filtro])

    return condicoes, parametros


def buscar_movimentacoes_fluxo_caixa(data_inicio, data_fim, tipo_filtro, categoria_filtro, subcategoria_filtro="Todas"):
    criar_tabela_movimentacoes_financeiras()

    condicoes = [
        "data_vencimento BETWEEN ? AND ?",
        "COALESCE(impacta_fluxo_caixa, 1) = 1",
    ]
    parametros = [data_inicio, data_fim]
    filtros, parametros_filtros = _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro, subcategoria_filtro)
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


def buscar_movimentacoes_realizadas_fluxo_caixa(data_inicio, data_fim, tipo_filtro, categoria_filtro, subcategoria_filtro="Todas"):
    criar_tabela_movimentacoes_financeiras()

    condicoes = [
        "data_realizacao BETWEEN ? AND ?",
        "COALESCE(data_realizacao, '') <> ?",
        "COALESCE(status, 'Pendente') IN (?, ?, ?)",
        "COALESCE(impacta_fluxo_caixa, 1) = 1",
    ]
    parametros = [data_inicio, data_fim, "", *STATUS_REALIZADOS_SQL]
    filtros, parametros_filtros = _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro, subcategoria_filtro)
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


def buscar_saldos_iniciais(data_inicio, tipo_filtro="Todos", categoria_filtro="Todas", subcategoria_filtro="Todas"):
    criar_tabela_movimentacoes_financeiras()

    filtros, parametros_filtros = _montar_filtros_movimentacoes(tipo_filtro, categoria_filtro, subcategoria_filtro)

    condicoes_previsto = [
        "data_vencimento < ?",
        "COALESCE(status, 'Pendente') <> ?",
        "COALESCE(impacta_fluxo_caixa, 1) = 1",
    ] + filtros
    parametros_previsto = [data_inicio, "Cancelado"] + parametros_filtros

    condicoes_realizado = [
        "data_realizacao < ?",
        "COALESCE(data_realizacao, '') <> ?",
        "COALESCE(status, 'Pendente') <> ?",
        "COALESCE(impacta_fluxo_caixa, 1) = 1",
    ] + filtros
    parametros_realizado = [data_inicio, "", "Cancelado"] + parametros_filtros

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes_previsto)}
    ORDER BY data_vencimento ASC, id ASC
    """), tuple(parametros_previsto))
    movimentacoes_previstas = [
        preparar_movimentacao_fluxo(item)
        for item in cursor.fetchall()
    ]

    cursor.execute(q(f"""
    SELECT *
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes_realizado)}
      AND COALESCE(status, 'Pendente') IN (?, ?, ?)
    ORDER BY data_realizacao ASC, id ASC
    """), tuple(parametros_realizado + list(STATUS_REALIZADOS_SQL)))
    movimentacoes_realizadas = [
        item for item in [preparar_movimentacao_fluxo(item) for item in cursor.fetchall()]
        if item["realizado"]
    ]
    conn.close()

    return {
        "saldo_inicial_previsto": _somar_impacto(movimentacoes_previstas),
        "saldo_inicial_realizado": _somar_impacto(movimentacoes_realizadas),
        "memoria_previsto": movimentacoes_previstas,
        "memoria_realizado": movimentacoes_realizadas,
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
    categoria_base = item_dict.get("categoria_plano") or item_dict.get("categoria") or ""
    item_dict["categoria_fluxo"] = CATEGORIA_AGRUPADA_POR_FILHA.get(categoria_base, categoria_base)
    item_dict["subcategoria_fluxo"] = (
        item_dict.get("subcategoria")
        or SUBCATEGORIA_POR_CATEGORIA_AGRUPADA.get(categoria_base, "")
    )

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


def montar_resumo_gerencial_fluxo_caixa(args):
    filtros = normalizar_filtros(args)
    filtros_sql, parametros_filtros = _montar_filtros_movimentacoes(
        filtros["tipo_filtro"],
        filtros["categoria_filtro"],
        filtros["subcategoria_filtro"],
    )
    condicoes_base = [
        "COALESCE(data_realizacao, '') <> ?",
        "COALESCE(status, 'Pendente') IN (?, ?, ?)",
        "COALESCE(impacta_fluxo_caixa, 1) = 1",
    ]
    parametros_base = ["", *STATUS_REALIZADOS_SQL]
    condicoes_base.extend(filtros_sql)
    parametros_base.extend(parametros_filtros)

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(f"""
    SELECT
        COALESCE(SUM(CASE WHEN tipo = 'Entrada' THEN valor ELSE 0 END), 0) AS entradas_realizadas,
        COALESCE(SUM(CASE WHEN tipo <> 'Entrada' THEN valor ELSE 0 END), 0) AS saidas_realizadas,
        COUNT(*) AS quantidade
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes_base)}
      AND data_realizacao BETWEEN ? AND ?
    """), tuple(parametros_base + [filtros["data_inicio"], filtros["data_fim"]]))
    periodo = cursor.fetchone()

    cursor.execute(q(f"""
    SELECT
        COALESCE(SUM(CASE WHEN tipo = 'Entrada' THEN valor ELSE -valor END), 0) AS saldo_inicial_realizado
    FROM movimentacoes_financeiras
    WHERE {" AND ".join(condicoes_base)}
      AND data_realizacao < ?
    """), tuple(parametros_base + [filtros["data_inicio"]]))
    inicial = cursor.fetchone()
    conn.close()

    entradas = float(periodo["entradas_realizadas"] or 0)
    saidas = float(periodo["saidas_realizadas"] or 0)
    saldo_inicial = float(inicial["saldo_inicial_realizado"] or 0)
    return {
        "resumo": {
            "entradas_realizadas": round(entradas, 2),
            "saidas_realizadas": round(saidas, 2),
            "saldo_realizado": round(saldo_inicial + entradas - saidas, 2),
        },
        "tem_dados": bool(periodo["quantidade"] or saldo_inicial),
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
        filtros["subcategoria_filtro"],
    )
    movimentacoes_periodo_previstas = buscar_movimentacoes_fluxo_caixa(
        filtros["data_inicio"],
        filtros["data_fim"],
        filtros["tipo_filtro"],
        filtros["categoria_filtro"],
        filtros["subcategoria_filtro"],
    )
    movimentacoes_periodo_realizadas = buscar_movimentacoes_realizadas_fluxo_caixa(
        filtros["data_inicio"],
        filtros["data_fim"],
        filtros["tipo_filtro"],
        filtros["categoria_filtro"],
        filtros["subcategoria_filtro"],
    )
    movimentacoes = filtrar_por_status(movimentacoes_periodo_previstas, filtros["status_filtro"])
    movimentacoes_realizadas = filtrar_por_status(movimentacoes_periodo_realizadas, filtros["status_filtro"])

    return {
        **filtros,
        "status_opcoes": STATUS_FLUXO_CAIXA,
        "tipo_opcoes": TIPOS_FLUXO_CAIXA,
        "categorias": listar_categorias_fluxo_caixa(),
        "subcategorias": listar_subcategorias_fluxo_caixa(filtros["categoria_filtro"]),
        "resumo": calcular_resumo_fluxo_caixa(movimentacoes, movimentacoes_realizadas, saldos_iniciais),
        "linha_tempo": montar_linha_tempo(movimentacoes, movimentacoes_realizadas, saldos_iniciais),
        "movimentacoes": movimentacoes,
        "conta_disponivel": False,
    }
