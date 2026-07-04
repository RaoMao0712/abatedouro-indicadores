"""Regras de cálculo e montagem de contexto do Dashboard."""

from datetime import datetime

from .repositories import buscar_dados_dashboard


JORNADA_PADRAO = 8.8
SETORES_PRODUTIVOS = [
    "Recepção e Pendura",
    "Escalda e Depenagem",
    "Evisceração",
    "Corte",
    "Embalagem",
]


def _normalizar_filtros(args):
    agora = datetime.now()
    hoje = agora.strftime("%Y-%m-%d")
    primeiro_dia_mes = agora.replace(day=1).strftime("%Y-%m-%d")

    data_inicio = args.get("data_inicio") or primeiro_dia_mes
    data_fim = args.get("data_fim") or hoje
    status_filtro = args.get("status") or "Encerrada"
    sku_filtro = args.get("sku") or "Todos"

    if status_filtro not in ["Aberta", "Encerrada"]:
        status_filtro = "Todas"

    if sku_filtro not in ["Galinha Cortada", "Galinha Inteira"]:
        sku_filtro = "Todos"

    return data_inicio, data_fim, status_filtro, sku_filtro


def montar_contexto_dashboard(args):
    data_inicio, data_fim, status_filtro, sku_filtro = _normalizar_filtros(args)
    dados = buscar_dados_dashboard(data_inicio, data_fim, status_filtro, sku_filtro)

    ordens_periodo = dados["ordens_periodo"]
    datas_periodo = sorted({op["data"] for op in ordens_periodo})
    dias_periodo = len(datas_periodo)
    horas_programadas = JORNADA_PADRAO * dias_periodo

    aves_recebidas = sum(op["quantidade_aves"] or 0 for op in ordens_periodo)
    mortes_antes_pendura_legado = sum(op["mortes_antes_pendura"] or 0 for op in ordens_periodo)
    peso_entrada = sum(op["peso_vivo"] or 0 for op in ordens_periodo)

    mortes_na_gaiola_descartes = dados["mortes_na_gaiola"]
    mortes_antes_pendura = mortes_antes_pendura_legado + mortes_na_gaiola_descartes
    descartes_aves_sem_morte_gaiola = max(0, dados["descartes_aves"] - mortes_na_gaiola_descartes)
    aves_abatidas = aves_recebidas - mortes_antes_pendura

    kg_produzidos = dados["kg_produzidos"]
    unidades_produzidas = dados["unidades_produzidas"]
    kg_produzidos_rendimento = dados["kg_produzidos_rendimento"]
    peso_entrada_rendimento = dados["peso_entrada_rendimento"]
    rendimento_aplicavel = sku_filtro != "Galinha Inteira"

    kg_por_sku_mix = {
        item["sku"]: float(item["kg_produzidos"] or 0)
        for item in dados["mix_kg_raw"]
    }
    total_unidades_mix = sum(float(item["unidades_produzidas"] or 0) for item in dados["mix_unidades_raw"])
    total_kg_mix = sum(kg_por_sku_mix.values())
    mix_producao_periodo = []

    for item in dados["mix_unidades_raw"]:
        sku_mix = item["sku"] or "Não informado"
        unidades_mix = float(item["unidades_produzidas"] or 0)
        representatividade = (unidades_mix / total_unidades_mix * 100) if total_unidades_mix > 0 else 0
        mix_producao_periodo.append({
            "sku": sku_mix,
            "unidades_produzidas": round(unidades_mix, 2),
            "representatividade": round(representatividade, 2),
            "kg_produzidos": round(kg_por_sku_mix.get(sku_mix, 0), 2),
        })

    total_problemas_aves = mortes_antes_pendura + descartes_aves_sem_morte_gaiola
    descartes_por_setor, descartes_aves_por_setor = _montar_descartes_por_setor(
        dados["descartes_por_setor_raw"], mortes_antes_pendura, total_problemas_aves
    )
    descartes_por_motivo = _montar_descartes_por_motivo(
        dados["descartes_por_motivo_raw"], mortes_antes_pendura, total_problemas_aves
    )

    horas_perdidas = _calcular_horas_perdidas(dados["paradas_produtivas"])
    horas_perdidas_por_setor = horas_perdidas["por_setor"]
    horas_perdidas_por_data_setor = horas_perdidas["por_data_setor"]
    horas_perdidas_total = horas_perdidas["total"]
    horas_uteis_total = max(0, horas_programadas - horas_perdidas_total)

    percentual_jornada_perdida = 0
    if horas_programadas > 0:
        percentual_jornada_perdida = (horas_perdidas_total / horas_programadas) * 100

    mao_obra = _calcular_mao_obra(
        dados["mao_obra_periodo"],
        ordens_periodo,
        horas_perdidas_por_data_setor,
    )
    hh_total = mao_obra["hh_total"]

    viabilidade = aves_recebidas - mortes_antes_pendura - descartes_aves_sem_morte_gaiola
    viabilidade_percentual = (viabilidade / aves_recebidas * 100) if aves_recebidas > 0 else 0

    rendimento = 0
    if rendimento_aplicavel and peso_entrada_rendimento > 0:
        rendimento = (kg_produzidos_rendimento / peso_entrada_rendimento) * 100

    meta_viabilidade = 99.5
    meta_rendimento = 63.0
    variacao_viabilidade = viabilidade_percentual - meta_viabilidade
    variacao_rendimento = rendimento - meta_rendimento

    produtividade_hh = (viabilidade / hh_total) if hh_total > 0 else 0
    aves_hora_fabrica = (viabilidade / horas_uteis_total) if horas_uteis_total > 0 else 0

    produtividade_setores_hora = _calcular_produtividade_setores_hora(
        aves_abatidas,
        horas_programadas,
        descartes_aves_por_setor,
        horas_perdidas_por_setor,
        mao_obra["hh_por_setor"],
        mao_obra["colaboradores_medio_por_setor"],
    )

    return {
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "status_filtro": status_filtro,
        "sku_filtro": sku_filtro,
        "mostrar_indicadores_kg": (sku_filtro == "Galinha Cortada"),
        "mostrar_indicadores_unidade": (sku_filtro == "Galinha Inteira"),
        "aves_recebidas": round(aves_recebidas, 2),
        "aves_abatidas": round(aves_abatidas, 2),
        "viabilidade": round(viabilidade, 2),
        "viabilidade_percentual": round(viabilidade_percentual, 2),
        "peso_entrada": round(peso_entrada, 2),
        "kg_produzidos": round(kg_produzidos, 2),
        "peso_entrada_rendimento": round(peso_entrada_rendimento, 2),
        "kg_produzidos_rendimento": round(kg_produzidos_rendimento, 2),
        "rendimento_aplicavel": rendimento_aplicavel,
        "unidades_produzidas": round(unidades_produzidas, 2),
        "mix_producao_periodo": mix_producao_periodo,
        "total_unidades_mix": round(total_unidades_mix, 2),
        "total_kg_mix": round(total_kg_mix, 2),
        "rendimento": round(rendimento, 2),
        "meta_viabilidade": round(meta_viabilidade, 2),
        "meta_rendimento": round(meta_rendimento, 2),
        "variacao_viabilidade": round(variacao_viabilidade, 2),
        "variacao_rendimento": round(variacao_rendimento, 2),
        "mortes_antes_pendura": round(mortes_antes_pendura, 2),
        "total_condenacoes": round(descartes_aves_sem_morte_gaiola, 2),
        "total_perdas": round(dados["descartes_kg"], 2),
        "total_problemas_aves": round(total_problemas_aves, 2),
        "jornada_padrao": round(JORNADA_PADRAO, 2),
        "dias_periodo": dias_periodo,
        "horas_programadas": round(horas_programadas, 2),
        "horas_perdidas_total": round(horas_perdidas_total, 2),
        "percentual_jornada_perdida": round(percentual_jornada_perdida, 2),
        "horas_uteis_total": round(horas_uteis_total, 2),
        "hh_total": round(hh_total, 2),
        "mao_obra_direta_media": round(mao_obra["mao_obra_direta_media"], 2),
        "produtividade_hh": round(produtividade_hh, 2),
        "aves_hora_fabrica": round(aves_hora_fabrica, 2),
        "descartes_por_motivo": descartes_por_motivo,
        "descartes_por_setor": descartes_por_setor,
        "produtividade_setores": dados["produtividade_setores"],
        "produtividade_setores_hora": produtividade_setores_hora,
    }


def _montar_descartes_por_setor(descartes_raw, mortes_antes_pendura, total_problemas_aves):
    descartes_por_setor = []
    descartes_aves_por_setor = {}

    if mortes_antes_pendura > 0:
        percentual_transporte = (mortes_antes_pendura / total_problemas_aves * 100) if total_problemas_aves > 0 else 0
        descartes_por_setor.append({
            "setor": "Morte na gaiola",
            "quantidade": round(mortes_antes_pendura, 2),
            "percentual": round(percentual_transporte, 2),
        })

    for item in descartes_raw:
        quantidade = item["quantidade"] or 0
        descartes_aves_por_setor[item["setor"]] = quantidade
        percentual = (quantidade / total_problemas_aves * 100) if total_problemas_aves > 0 else 0
        descartes_por_setor.append({
            "setor": item["setor"],
            "quantidade": round(quantidade, 2),
            "percentual": round(percentual, 2),
        })

    return sorted(descartes_por_setor, key=lambda item: item["quantidade"], reverse=True), descartes_aves_por_setor


def _montar_descartes_por_motivo(descartes_raw, mortes_antes_pendura, total_problemas_aves):
    descartes_por_motivo = []

    if mortes_antes_pendura > 0:
        percentual_morte_gaiola = (mortes_antes_pendura / total_problemas_aves * 100) if total_problemas_aves > 0 else 0
        descartes_por_motivo.append({
            "motivo": "Morte na gaiola",
            "quantidade": round(mortes_antes_pendura, 2),
            "percentual": round(percentual_morte_gaiola, 2),
        })

    for item in descartes_raw:
        motivo = item["motivo"] or "Não informado"
        quantidade = item["quantidade"] or 0
        percentual = (quantidade / total_problemas_aves * 100) if total_problemas_aves > 0 else 0
        descartes_por_motivo.append({
            "motivo": motivo,
            "quantidade": round(quantidade, 2),
            "percentual": round(percentual, 2),
        })

    return sorted(descartes_por_motivo, key=lambda item: item["quantidade"], reverse=True)


def _calcular_horas_perdidas(paradas_produtivas):
    horas_perdidas_por_setor = {setor: 0 for setor in SETORES_PRODUTIVOS}
    horas_perdidas_por_data_setor = {}
    eventos_parada_unicos = {}

    for parada in paradas_produtivas:
        setor = parada["setor"]
        if setor not in SETORES_PRODUTIVOS:
            continue

        horas = float(parada["horas_paradas"] or 0)
        data_base = parada["data_op"] or parada["data_apontamento"]
        horas_perdidas_por_setor[setor] += horas
        chave_data_setor = (data_base, setor)
        horas_perdidas_por_data_setor[chave_data_setor] = horas_perdidas_por_data_setor.get(chave_data_setor, 0) + horas

        if parada["evento_id"]:
            chave_evento = parada["evento_id"]
        else:
            chave_evento = (
                parada["op_id"],
                data_base,
                parada["motivo"],
                round(horas, 4),
                parada["observacoes"] or "",
            )

        eventos_parada_unicos[chave_evento] = horas

    return {
        "por_setor": horas_perdidas_por_setor,
        "por_data_setor": horas_perdidas_por_data_setor,
        "total": sum(eventos_parada_unicos.values()),
    }


def _calcular_mao_obra(mao_obra_periodo, ordens_periodo, horas_perdidas_por_data_setor):
    colaboradores_por_op_setor = {}

    for item in mao_obra_periodo:
        setor = item["setor"]
        if setor not in SETORES_PRODUTIVOS:
            continue

        nome = (item["colaborador"] or "").strip().lower()
        if not nome:
            continue

        chave = (item["op_id"], setor)
        colaboradores_por_op_setor.setdefault(chave, set()).add(nome)

    hh_total = 0
    hh_por_setor = {setor: 0 for setor in SETORES_PRODUTIVOS}
    colaboradores_medio_por_setor = {setor: 0 for setor in SETORES_PRODUTIVOS}
    contagens_por_setor = {setor: [] for setor in SETORES_PRODUTIVOS}
    mao_obra_direta_por_op = {}
    data_por_op = {op["id"]: op["data"] for op in ordens_periodo}

    for (op_id, setor), colaboradores in colaboradores_por_op_setor.items():
        data_op = data_por_op.get(op_id)
        horas_perdidas_setor_dia = horas_perdidas_por_data_setor.get((data_op, setor), 0)
        horas_uteis_setor_dia = max(0, JORNADA_PADRAO - horas_perdidas_setor_dia)
        quantidade_colaboradores = len(colaboradores)
        hh = quantidade_colaboradores * horas_uteis_setor_dia

        hh_por_setor[setor] += hh
        hh_total += hh
        contagens_por_setor[setor].append(quantidade_colaboradores)
        mao_obra_direta_por_op[op_id] = mao_obra_direta_por_op.get(op_id, 0) + quantidade_colaboradores

    for setor in SETORES_PRODUTIVOS:
        contagens = contagens_por_setor.get(setor, [])
        if contagens:
            colaboradores_medio_por_setor[setor] = sum(contagens) / len(contagens)

    mao_obra_direta_media = 0
    if mao_obra_direta_por_op:
        mao_obra_direta_media = sum(mao_obra_direta_por_op.values()) / len(mao_obra_direta_por_op)

    return {
        "hh_total": hh_total,
        "hh_por_setor": hh_por_setor,
        "colaboradores_medio_por_setor": colaboradores_medio_por_setor,
        "mao_obra_direta_media": mao_obra_direta_media,
    }


def _calcular_produtividade_setores_hora(
    aves_abatidas,
    horas_programadas,
    descartes_aves_por_setor,
    horas_perdidas_por_setor,
    hh_por_setor,
    colaboradores_medio_por_setor,
):
    produtividade_setores_hora = []
    entrada_setor = aves_abatidas

    for setor in SETORES_PRODUTIVOS:
        descartes_setor = descartes_aves_por_setor.get(setor, 0)
        saida_liquida = max(0, entrada_setor - descartes_setor)
        horas_perdidas_setor = horas_perdidas_por_setor.get(setor, 0)
        horas_uteis_setor = max(0, horas_programadas - horas_perdidas_setor)
        hh_setor = hh_por_setor.get(setor, 0)
        aves_hora_setor = (saida_liquida / horas_uteis_setor) if horas_uteis_setor > 0 else 0
        produtividade_hh_setor = (saida_liquida / hh_setor) if hh_setor > 0 else 0

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
            "produtividade_hh": round(produtividade_hh_setor, 2),
        })

        entrada_setor = saida_liquida

    return produtividade_setores_hora
