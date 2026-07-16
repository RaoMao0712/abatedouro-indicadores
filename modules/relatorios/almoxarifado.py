"""Servicos compartilhados para relatorios oficiais de almoxarifado."""

from collections import defaultdict
from datetime import date
from io import BytesIO
from urllib.parse import urlencode

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from database import conectar, q


RELATORIOS_ALMOXARIFADO = {
    "entradas": {
        "catalogo_id": "almoxarifado-entradas",
        "titulo": "Entradas",
        "objetivo": "Consultar entradas oficiais de insumos por periodo, documento, fornecedor e lote.",
        "familia": "movimentacoes",
        "tipos": ["ENTRADA"],
    },
    "consumo": {
        "catalogo_id": "almoxarifado-consumo",
        "titulo": "Consumo",
        "objetivo": "Consultar saidas e consumos de insumos sem alterar a regra operacional de baixa.",
        "familia": "movimentacoes",
        "tipos": ["SAIDA", "SAIDA_OP"],
    },
    "estoque-atual": {
        "catalogo_id": "almoxarifado-estoque-atual",
        "titulo": "Estoque Atual",
        "objetivo": "Exibir o saldo oficial atual dos insumos calculado pelos lotes.",
        "familia": "saldo",
    },
    "estoque-por-produto": {
        "catalogo_id": "almoxarifado-estoque-produto",
        "titulo": "Estoque por Produto",
        "objetivo": "Detalhar a distribuicao do saldo por produto, categoria e lotes.",
        "familia": "saldo",
    },
}


def hoje_iso():
    return date.today().isoformat()


def primeiro_dia_mes():
    hoje = date.today()
    return hoje.replace(day=1).isoformat()


def valor_float(valor, casas=4):
    try:
        return round(float(valor or 0), casas)
    except (TypeError, ValueError):
        return 0.0


def executar_lista(sql, parametros=()):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q(sql), tuple(parametros))
    linhas = cursor.fetchall()
    conn.close()
    return [dict(linha) for linha in linhas]


def normalizar_filtros(args, config):
    tipo = args.get("tipo") or "Todos"
    tipos_validos = ["Todos", "ENTRADA", "SAIDA", "SAIDA_OP", "ESTORNO_OP", "AJUSTE"]
    if tipo not in tipos_validos:
        tipo = "Todos"

    return {
        "data_inicio": args.get("data_inicio") or primeiro_dia_mes(),
        "data_fim": args.get("data_fim") or hoje_iso(),
        "categoria": args.get("categoria") or "Todas",
        "insumo": args.get("insumo") or "",
        "tipo": tipo,
        "fornecedor": args.get("fornecedor") or "",
        "numero_nf": args.get("numero_nf") or "",
        "lote": args.get("lote") or "",
        "op_id": args.get("op_id") or "",
        "status_lote": args.get("status_lote") or "Todos",
        "somente_com_saldo": args.get("somente_com_saldo") or ("Sim" if config["familia"] == "saldo" else "Nao"),
        "por_pagina": 300,
    }


def montar_condicoes_movimentacoes(config, filtros):
    condicoes = ["m.data_movimentacao BETWEEN ? AND ?"]
    parametros = [filtros["data_inicio"], filtros["data_fim"]]

    tipos_config = config.get("tipos")
    if filtros["tipo"] != "Todos":
        condicoes.append("m.tipo = ?")
        parametros.append(filtros["tipo"])
    elif tipos_config:
        placeholders = ", ".join(["?"] * len(tipos_config))
        condicoes.append(f"m.tipo IN ({placeholders})")
        parametros.extend(tipos_config)

    if filtros["categoria"] != "Todas":
        condicoes.append("i.categoria = ?")
        parametros.append(filtros["categoria"])
    if filtros["insumo"]:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{filtros['insumo'].lower()}%")
    if filtros["fornecedor"]:
        condicoes.append("LOWER(COALESCE(m.fornecedor, '')) LIKE ?")
        parametros.append(f"%{filtros['fornecedor'].lower()}%")
    if filtros["numero_nf"]:
        condicoes.append("LOWER(COALESCE(m.numero_nf, '')) LIKE ?")
        parametros.append(f"%{filtros['numero_nf'].lower()}%")
    if filtros["lote"]:
        condicoes.append("LOWER(COALESCE(m.lote, '')) LIKE ?")
        parametros.append(f"%{filtros['lote'].lower()}%")
    if filtros["op_id"]:
        try:
            condicoes.append("m.op_id = ?")
            parametros.append(int(filtros["op_id"]))
        except ValueError:
            condicoes.append("1 = 0")

    return " AND ".join(condicoes), parametros


def montar_condicoes_saldo(filtros):
    condicoes = ["1 = 1"]
    parametros = []

    if filtros["categoria"] != "Todas":
        condicoes.append("i.categoria = ?")
        parametros.append(filtros["categoria"])
    if filtros["insumo"]:
        condicoes.append("LOWER(i.descricao) LIKE ?")
        parametros.append(f"%{filtros['insumo'].lower()}%")
    if filtros["fornecedor"]:
        condicoes.append("LOWER(COALESCE(l.fornecedor, '')) LIKE ?")
        parametros.append(f"%{filtros['fornecedor'].lower()}%")
    if filtros["numero_nf"]:
        condicoes.append("LOWER(COALESCE(l.numero_nf, '')) LIKE ?")
        parametros.append(f"%{filtros['numero_nf'].lower()}%")
    if filtros["lote"]:
        condicoes.append("LOWER(COALESCE(l.lote, '')) LIKE ?")
        parametros.append(f"%{filtros['lote'].lower()}%")
    if filtros["status_lote"] != "Todos":
        condicoes.append("COALESCE(l.status, 'Aberto') = ?")
        parametros.append(filtros["status_lote"])
    if filtros["somente_com_saldo"] == "Sim":
        condicoes.append("COALESCE(l.quantidade_atual, 0) > 0")

    return " AND ".join(condicoes), parametros


def buscar_movimentacoes(config, filtros):
    where_sql, parametros = montar_condicoes_movimentacoes(config, filtros)
    return executar_lista(f"""
        SELECT
            m.id,
            m.data_movimentacao,
            m.tipo,
            i.descricao AS insumo,
            i.categoria,
            i.unidade,
            m.quantidade,
            m.valor_unitario,
            m.valor_total,
            m.fornecedor,
            m.numero_nf,
            m.lote,
            m.origem,
            m.op_id,
            m.observacoes,
            m.criado_em
        FROM almoxarifado_movimentacoes m
        JOIN almoxarifado_insumos i ON i.id = m.insumo_id
        WHERE {where_sql}
        ORDER BY m.data_movimentacao DESC, m.id DESC
        LIMIT ?
    """, parametros + [filtros["por_pagina"]])


def buscar_saldos(filtros):
    where_sql, parametros = montar_condicoes_saldo(filtros)
    return executar_lista(f"""
        SELECT
            i.id AS insumo_id,
            i.descricao AS insumo,
            i.categoria,
            i.unidade,
            i.ativo,
            COUNT(l.id) AS lotes,
            COALESCE(SUM(l.quantidade_atual), 0) AS saldo_atual,
            COALESCE(SUM(l.quantidade_atual * l.valor_unitario), 0) AS valor_estoque,
            MIN(l.data_entrada) AS primeira_entrada,
            MAX(l.data_entrada) AS ultima_entrada
        FROM almoxarifado_insumos i
        LEFT JOIN almoxarifado_lotes l ON l.insumo_id = i.id
        WHERE {where_sql}
        GROUP BY i.id, i.descricao, i.categoria, i.unidade, i.ativo
        ORDER BY i.categoria ASC, i.descricao ASC
        LIMIT ?
    """, parametros + [filtros["por_pagina"]])


def buscar_lotes(filtros):
    where_sql, parametros = montar_condicoes_saldo(filtros)
    return executar_lista(f"""
        SELECT
            l.id,
            i.descricao AS insumo,
            i.categoria,
            i.unidade,
            l.data_entrada,
            l.lote,
            l.fornecedor,
            l.numero_nf,
            l.quantidade_inicial,
            l.quantidade_atual,
            l.valor_unitario,
            l.valor_total,
            l.status,
            l.criado_em
        FROM almoxarifado_lotes l
        JOIN almoxarifado_insumos i ON i.id = l.insumo_id
        WHERE {where_sql}
        ORDER BY l.data_entrada ASC, l.id ASC
        LIMIT ?
    """, parametros + [filtros["por_pagina"]])


def agrupar_por_tipo(movimentacoes):
    grupos = defaultdict(lambda: {"grupo": "", "eventos": 0, "quantidade": 0.0, "valor_total": 0.0})
    for item in movimentacoes:
        chave = item["tipo"] or "Sem tipo"
        grupos[chave]["grupo"] = chave
        grupos[chave]["eventos"] += 1
        grupos[chave]["quantidade"] += valor_float(item["quantidade"])
        grupos[chave]["valor_total"] += valor_float(item["valor_total"], 2)
    return sorted(grupos.values(), key=lambda item: item["valor_total"], reverse=True)


def agrupar_por_categoria(linhas):
    grupos = defaultdict(lambda: {"grupo": "", "itens": 0, "lotes": 0, "saldo_atual": 0.0, "valor_estoque": 0.0})
    for item in linhas:
        chave = item.get("categoria") or "Sem categoria"
        grupos[chave]["grupo"] = chave
        grupos[chave]["itens"] += 1
        grupos[chave]["lotes"] += int(item.get("lotes") or 0)
        grupos[chave]["saldo_atual"] += valor_float(item.get("saldo_atual"))
        grupos[chave]["valor_estoque"] += valor_float(item.get("valor_estoque"), 2)
    return sorted(grupos.values(), key=lambda item: item["valor_estoque"], reverse=True)


def resumo_movimentacoes(linhas):
    return [
        {"rotulo": "Eventos", "valor": len(linhas), "tipo": "inteiro", "unidade": "movimentacoes"},
        {"rotulo": "Quantidade", "valor": round(sum(valor_float(i.get("quantidade")) for i in linhas), 4), "tipo": "decimal", "unidade": "unidades conforme cadastro"},
        {"rotulo": "Valor total", "valor": round(sum(valor_float(i.get("valor_total"), 2) for i in linhas), 2), "tipo": "moeda", "unidade": "R$"},
        {"rotulo": "Com OP", "valor": sum(1 for i in linhas if i.get("op_id")), "tipo": "inteiro", "unidade": "eventos"},
    ]


def resumo_saldos(saldos):
    return [
        {"rotulo": "Itens com saldo", "valor": sum(1 for i in saldos if valor_float(i.get("saldo_atual")) > 0), "tipo": "inteiro", "unidade": "insumos"},
        {"rotulo": "Lotes", "valor": sum(int(i.get("lotes") or 0) for i in saldos), "tipo": "inteiro", "unidade": "lotes"},
        {"rotulo": "Saldo total", "valor": round(sum(valor_float(i.get("saldo_atual")) for i in saldos), 4), "tipo": "decimal", "unidade": "unidades conforme cadastro"},
        {"rotulo": "Valor em estoque", "valor": round(sum(valor_float(i.get("valor_estoque"), 2) for i in saldos), 2), "tipo": "moeda", "unidade": "R$"},
    ]


def buscar_opcoes_filtro():
    categorias = [item["valor"] for item in executar_lista("""
        SELECT DISTINCT categoria AS valor
        FROM almoxarifado_insumos
        WHERE COALESCE(categoria, '') <> ''
        ORDER BY valor
    """)]
    status_lotes = [item["valor"] for item in executar_lista("""
        SELECT DISTINCT COALESCE(status, 'Aberto') AS valor
        FROM almoxarifado_lotes
        WHERE COALESCE(status, '') <> ''
        ORDER BY valor
    """)]
    return {
        "categorias": categorias,
        "tipos": ["ENTRADA", "SAIDA", "SAIDA_OP", "ESTORNO_OP", "AJUSTE"],
        "status_lotes": status_lotes,
    }


def montar_contexto_relatorio_almoxarifado(slug, args):
    config = RELATORIOS_ALMOXARIFADO[slug]
    filtros = normalizar_filtros(args, config)
    limitacoes = []
    agrupamentos = []
    detalhes = []
    lotes = []

    if config["familia"] == "movimentacoes":
        detalhes = buscar_movimentacoes(config, filtros)
        agrupamentos = agrupar_por_tipo(detalhes)
        resumo = resumo_movimentacoes(detalhes)
        if slug == "consumo":
            limitacoes.append("Consumo considera SAIDA e SAIDA_OP; ESTORNO_OP nao entra como consumo.")
        if not detalhes:
            limitacoes.append("Nenhuma movimentacao encontrada para os filtros selecionados.")
    else:
        detalhes = buscar_saldos(filtros)
        lotes = buscar_lotes(filtros)
        resumo = resumo_saldos(detalhes)
        agrupamentos = agrupar_por_categoria(detalhes)
        if not detalhes:
            limitacoes.append("Nenhum saldo encontrado para os filtros selecionados.")
        limitacoes.append("Saldo oficial: soma de almoxarifado_lotes.quantidade_atual.")

    if slug in ["estoque-atual", "estoque-por-produto"]:
        limitacoes.append("Valor em estoque usa quantidade atual do lote x valor unitario historico; nao e CMV nem custo medio.")

    return {
        "slug": slug,
        "config": config,
        "filtros": filtros,
        "opcoes": buscar_opcoes_filtro(),
        "resumo": resumo,
        "agrupamentos": agrupamentos,
        "detalhes": detalhes,
        "lotes": lotes,
        "limitacoes": limitacoes,
        "query_string": urlencode({k: v for k, v in filtros.items() if v not in ["", "Todos", "Todas", "Nao"]}),
    }


def gerar_excel_relatorio_almoxarifado(contexto):
    wb = Workbook()
    ws = wb.active
    ws.title = "Relatorio"
    ws.append([contexto["config"]["titulo"]])
    ws.append([contexto["config"]["objetivo"]])
    ws.append([])
    ws.append(["Filtros"])
    for chave, valor in contexto["filtros"].items():
        ws.append([chave, valor])
    ws.append([])
    ws.append(["Indicador", "Valor", "Unidade"])
    for item in contexto["resumo"]:
        ws.append([item["rotulo"], item["valor"], item["unidade"]])
    ws.append([])

    if contexto["agrupamentos"]:
        ws.append(["Agrupamentos"])
        chaves = list(contexto["agrupamentos"][0].keys())
        ws.append(chaves)
        for item in contexto["agrupamentos"]:
            ws.append([item.get(chave, "") for chave in chaves])
        ws.append([])

    ws.append(["Detalhes"])
    if contexto["config"]["familia"] == "movimentacoes":
        colunas = ["id", "data_movimentacao", "tipo", "insumo", "categoria", "unidade", "quantidade", "valor_unitario", "valor_total", "fornecedor", "numero_nf", "lote", "origem", "op_id", "observacoes", "criado_em"]
        ws.append(colunas)
        for item in contexto["detalhes"]:
            ws.append([item.get(coluna, "") for coluna in colunas])
    else:
        colunas = ["insumo_id", "insumo", "categoria", "unidade", "ativo", "lotes", "saldo_atual", "valor_estoque", "primeira_entrada", "ultima_entrada"]
        ws.append(colunas)
        for item in contexto["detalhes"]:
            ws.append([item.get(coluna, "") for coluna in colunas])
        ws.append([])
        ws.append(["Lotes"])
        colunas_lote = ["id", "insumo", "categoria", "unidade", "data_entrada", "lote", "fornecedor", "numero_nf", "quantidade_inicial", "quantidade_atual", "valor_unitario", "valor_total", "status", "criado_em"]
        ws.append(colunas_lote)
        for item in contexto["lotes"]:
            ws.append([item.get(coluna, "") for coluna in colunas_lote])

    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3B4D")
    for coluna in range(1, 18):
        ws.column_dimensions[get_column_letter(coluna)].width = 18
    arquivo = BytesIO()
    wb.save(arquivo)
    arquivo.seek(0)
    return arquivo
