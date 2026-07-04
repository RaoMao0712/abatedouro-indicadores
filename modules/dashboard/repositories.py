"""Consultas agregadas do Dashboard."""

from database import conectar, q


def _filtros(status_filtro, sku_filtro):
    status_condicao_op = ""
    status_condicao_alias = ""
    parametros_status = ()

    if status_filtro in ["Aberta", "Encerrada"]:
        status_condicao_op = " AND COALESCE(status, 'Aberta') = ?"
        status_condicao_alias = " AND COALESCE(o.status, 'Aberta') = ?"
        parametros_status = (status_filtro,)

    sku_condicao_op = ""
    sku_condicao_alias = ""
    parametros_sku = ()

    if sku_filtro in ["Galinha Cortada", "Galinha Inteira"]:
        sku_condicao_op = " AND COALESCE(sku, 'Galinha Cortada') = ?"
        sku_condicao_alias = " AND COALESCE(o.sku, 'Galinha Cortada') = ?"
        parametros_sku = (sku_filtro,)

    return {
        "status_condicao_op": status_condicao_op,
        "status_condicao_alias": status_condicao_alias,
        "sku_condicao_op": sku_condicao_op,
        "sku_condicao_alias": sku_condicao_alias,
        "parametros_status": parametros_status,
        "parametros_filtros": parametros_status + parametros_sku,
    }


def buscar_dados_dashboard(data_inicio, data_fim, status_filtro, sku_filtro):
    filtros = _filtros(status_filtro, sku_filtro)
    status_condicao_op = filtros["status_condicao_op"]
    status_condicao_alias = filtros["status_condicao_alias"]
    sku_condicao_op = filtros["sku_condicao_op"]
    sku_condicao_alias = filtros["sku_condicao_alias"]
    parametros_status = filtros["parametros_status"]
    parametros_filtros = filtros["parametros_filtros"]

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute(q(f"""
    SELECT id, data, quantidade_aves, mortes_antes_pendura, peso_vivo
    FROM ordens_producao
    WHERE data BETWEEN ? AND ?
    {status_condicao_op}
    {sku_condicao_op}
    """), (data_inicio, data_fim) + parametros_filtros)
    ordens_periodo = cursor.fetchall()

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
    SELECT COALESCE(SUM(d.quantidade), 0) as mortes_na_gaiola
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      AND LOWER(TRIM(d.motivo)) = 'morte na gaiola'
      {status_condicao_alias}
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)
    mortes_na_gaiola = cursor.fetchone()["mortes_na_gaiola"] or 0

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

    cursor.execute(q(f"""
    SELECT COALESCE(o.sku, 'Galinha Cortada') as sku,
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
    SELECT COALESCE(o.sku, 'Galinha Cortada') as sku,
           COALESCE(SUM(p.quantidade), 0) as kg_produzidos
    FROM apontamentos_producao p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(p.unidade) = 'kg'
      {status_condicao_alias}
    GROUP BY COALESCE(o.sku, 'Galinha Cortada')
    """), (data_inicio, data_fim) + parametros_status)
    mix_kg_raw = cursor.fetchall()

    cursor.execute(q(f"""
    SELECT d.setor, COALESCE(SUM(d.quantidade), 0) as quantidade
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      AND LOWER(TRIM(d.motivo)) <> 'morte na gaiola'
      {status_condicao_alias}
    GROUP BY d.setor
    ORDER BY quantidade DESC
    """), (data_inicio, data_fim) + parametros_status)
    descartes_por_setor_raw = cursor.fetchall()

    cursor.execute(q(f"""
    SELECT d.motivo, COALESCE(SUM(d.quantidade), 0) as quantidade
    FROM apontamentos_descartes d
    JOIN ordens_producao o ON o.id = d.op_id
    WHERE o.data BETWEEN ? AND ?
      AND LOWER(d.unidade) IN ('aves', 'ave', 'unidade', 'unidades')
      AND LOWER(TRIM(d.motivo)) <> 'morte na gaiola'
      {status_condicao_alias}
      {sku_condicao_alias}
    GROUP BY d.motivo
    ORDER BY quantidade DESC
    """), (data_inicio, data_fim) + parametros_filtros)
    descartes_por_motivo_raw = cursor.fetchall()

    cursor.execute(q(f"""
    SELECT p.id, p.evento_id, p.op_id, o.data as data_op, p.data as data_apontamento,
           p.setor, p.motivo, p.horas_paradas, p.observacoes
    FROM apontamentos_paradas p
    JOIN ordens_producao o ON o.id = p.op_id
    WHERE o.data BETWEEN ? AND ?
      AND p.setor <> 'Expedição'
      {status_condicao_alias}
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)
    paradas_produtivas = cursor.fetchall()

    cursor.execute(q(f"""
    SELECT o.id as op_id, o.data as data_op, m.setor, m.colaborador
    FROM apontamentos_mao_obra m
    JOIN ordens_producao o ON o.id = m.op_id
    WHERE o.data BETWEEN ? AND ?
      AND m.setor <> 'Expedição'
      {status_condicao_alias}
      {sku_condicao_alias}
    """), (data_inicio, data_fim) + parametros_filtros)
    mao_obra_periodo = cursor.fetchall()

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

    conn.close()

    return {
        "ordens_periodo": ordens_periodo,
        "descartes_aves": descartes_aves,
        "mortes_na_gaiola": mortes_na_gaiola,
        "descartes_kg": descartes_kg,
        "kg_produzidos": kg_produzidos,
        "unidades_produzidas": unidades_produzidas,
        "kg_produzidos_rendimento": kg_produzidos_rendimento,
        "peso_entrada_rendimento": peso_entrada_rendimento,
        "mix_unidades_raw": mix_unidades_raw,
        "mix_kg_raw": mix_kg_raw,
        "descartes_por_setor_raw": descartes_por_setor_raw,
        "descartes_por_motivo_raw": descartes_por_motivo_raw,
        "paradas_produtivas": paradas_produtivas,
        "mao_obra_periodo": mao_obra_periodo,
        "produtividade_setores": produtividade_setores,
    }
