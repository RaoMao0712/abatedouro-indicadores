"""Livro canônico de movimentação operacional da Expedição.

``estoque_eventos`` é a fonte oficial. ``pa_movimentacoes`` participa somente
como fallback explícito para documentos históricos sem evento canônico
equivalente; as duas fontes nunca são somadas para a mesma caixa/romaneio.
"""

from database import conectar, q


ACOES_SAIDA_CANONICAS = ("CONFIRMACAO_ROMANEIO", "VENDA_DIRETA")
TIPOS_TRANSFERENCIA = ("TRANSFERENCIA", "TRANSFERENCIA_AUTORIZADA")


def cte_movimentacoes_expedicao(nome="movimentos_expedicao"):
    """Retorna CTE normalizada, canônica primeiro e legado apenas como fallback."""
    return f"""
    {nome} AS (
        SELECT
            ev.id AS id,
            ev.caixa_id,
            ev.expedicao_id,
            CASE
                WHEN ev.acao = 'VENDA_DIRETA' THEN 'VENDA_DIRETA'
                WHEN e.tipo_movimentacao IN ('TRANSFERENCIA','TRANSFERENCIA_AUTORIZADA')
                    THEN 'TRANSFERENCIA'
                ELSE ev.acao
            END AS tipo,
            (
                SELECT MIN(i.local_anterior_id)
                FROM expedicao_itens i
                WHERE i.expedicao_id = ev.expedicao_id AND i.caixa_id = ev.caixa_id
            ) AS local_origem_id,
            e.destino_local_id AS local_destino_id,
            ev.usuario,
            ev.criado_em,
            'estoque_eventos' AS fonte
        FROM estoque_eventos ev
        INNER JOIN expedicoes e ON e.id = ev.expedicao_id
        WHERE ev.caixa_id IS NOT NULL
          AND ev.acao IN ('CONFIRMACAO_ROMANEIO','VENDA_DIRETA')

        UNION ALL

        SELECT
            legado.id,
            legado.caixa_id,
            legado.expedicao_id,
            legado.tipo,
            legado.local_origem_id,
            legado.local_destino_id,
            legado.usuario,
            legado.criado_em,
            'pa_movimentacoes_fallback' AS fonte
        FROM pa_movimentacoes legado
        WHERE NOT EXISTS (
            SELECT 1
            FROM estoque_eventos ev
            WHERE ev.caixa_id = legado.caixa_id
              AND (
                    ev.expedicao_id = legado.expedicao_id
                    OR (ev.expedicao_id IS NULL AND legado.expedicao_id IS NULL)
              )
              AND ev.acao IN ('CONFIRMACAO_ROMANEIO','VENDA_DIRETA')
        )
    )
    """


def cte_eventos_sucessores(nome="eventos_sucessores"):
    """Eventos que bloqueiam reversões, com fallback legado sem duplicidade."""
    return f"""
    {nome} AS (
        SELECT ev.caixa_id, ev.expedicao_id, ev.id, ev.acao AS tipo,
               ev.criado_em, 'estoque_eventos' AS fonte
        FROM estoque_eventos ev
        WHERE ev.acao NOT IN ('FORMACAO_ESTOQUE','ESTORNO_CAIXA_EMBALAGEM')

        UNION ALL

        SELECT legado.caixa_id, legado.expedicao_id, legado.id, legado.tipo,
               legado.criado_em, 'pa_movimentacoes_fallback' AS fonte
        FROM pa_movimentacoes legado
        WHERE NOT EXISTS (
            SELECT 1 FROM estoque_eventos ev
            WHERE ev.caixa_id = legado.caixa_id
              AND (
                    ev.expedicao_id = legado.expedicao_id
                    OR (ev.expedicao_id IS NULL AND legado.expedicao_id IS NULL)
              )
              AND ev.acao IN ('CONFIRMACAO_ROMANEIO','VENDA_DIRETA')
        )
    )
    """


def buscar_eventos_sucessores_cursor(cursor, caixa_ids):
    """Consulta compatível com bases antigas e fixtures de schema reduzido."""
    ids = sorted({int(caixa_id) for caixa_id in caixa_ids})
    if not ids:
        return []
    marcadores = ",".join("?" for _ in ids)

    def colunas(tabela):
        cursor.execute(f"SELECT * FROM {tabela} WHERE 1=0")
        return {getattr(item, "name", None) or item[0] for item in cursor.description}

    colunas_eventos = colunas("estoque_eventos")
    expedicao_evento = "expedicao_id" if "expedicao_id" in colunas_eventos else "NULL"
    criado_evento = "criado_em" if "criado_em" in colunas_eventos else "NULL"
    cursor.execute(q(f"""
    SELECT caixa_id,{expedicao_evento} AS expedicao_id,id,acao AS tipo,
           {criado_evento} AS criado_em
    FROM estoque_eventos
    WHERE caixa_id IN ({marcadores})
      AND acao NOT IN ('FORMACAO_ESTOQUE','ESTORNO_CAIXA_EMBALAGEM')
    ORDER BY caixa_id,id
    """), ids)
    eventos = [dict(item) for item in cursor.fetchall()]
    for item in eventos:
        item["fonte"] = "estoque_eventos"

    colunas_legado = colunas("pa_movimentacoes")
    expedicao_legado = "expedicao_id" if "expedicao_id" in colunas_legado else "NULL"
    criado_legado = "criado_em" if "criado_em" in colunas_legado else "NULL"
    cursor.execute(q(f"""
    SELECT caixa_id,{expedicao_legado} AS expedicao_id,id,tipo,
           {criado_legado} AS criado_em
    FROM pa_movimentacoes
    WHERE caixa_id IN ({marcadores})
    ORDER BY caixa_id,id
    """), ids)
    chaves_canonicas = {
        (int(item["caixa_id"]), item["expedicao_id"])
        for item in eventos if item["tipo"] in ACOES_SAIDA_CANONICAS
    }
    for linha in cursor.fetchall():
        item = dict(linha)
        if (int(item["caixa_id"]), item["expedicao_id"]) in chaves_canonicas:
            continue
        item["fonte"] = "pa_movimentacoes_fallback"
        eventos.append(item)
    return sorted(eventos, key=lambda item: (
        int(item["caixa_id"]), str(item["criado_em"] or ""), int(item["id"])
    ))


def reconciliar_movimentacoes_expedicao(*, somente_divergencias=True):
    """Compara documento, posição física e livros sem realizar qualquer escrita."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""
        SELECT
            i.id AS item_id,i.expedicao_id,i.caixa_id,COALESCE(i.ativo,1) AS item_ativo,
            e.numero_romaneio,e.status AS status_documento,e.tipo_movimentacao,
            cx.codigo_caixa,cx.status AS status_caixa,cx.disponibilidade AS estado_atual,
            COALESCE(i.unidade_estoque,cx.unidade_estoque,'CAIXA') AS unidade_estoque,
            (
                SELECT ev.acao FROM estoque_eventos ev
                WHERE ev.caixa_id=i.caixa_id
                ORDER BY ev.id DESC LIMIT 1
            ) AS ultima_acao,
            (
                SELECT ev.expedicao_id FROM estoque_eventos ev
                WHERE ev.caixa_id=i.caixa_id
                ORDER BY ev.id DESC LIMIT 1
            ) AS ultima_expedicao_id,
            EXISTS(
                SELECT 1 FROM estoque_eventos ev
                WHERE ev.expedicao_id=e.id AND ev.caixa_id=i.caixa_id
                  AND ev.acao = CASE
                    WHEN e.status='Aberto' THEN 'RESERVA'
                    WHEN e.status='Cancelado' THEN 'CANCELAMENTO_ROMANEIO'
                    WHEN e.status='Estornado' THEN 'ESTORNO_ROMANEIO'
                    WHEN e.tipo_movimentacao='VENDA_DIRETA' THEN 'VENDA_DIRETA'
                    ELSE 'CONFIRMACAO_ROMANEIO' END
            ) AS evento_encontrado,
            EXISTS(
                SELECT 1 FROM pa_movimentacoes mov
                WHERE mov.expedicao_id=e.id AND mov.caixa_id=i.caixa_id
            ) AS presente_legado
        FROM expedicao_itens i
        INNER JOIN expedicoes e ON e.id=i.expedicao_id
        LEFT JOIN pa_caixas cx ON cx.id=i.caixa_id
        WHERE i.caixa_id IS NOT NULL
          AND e.tipo_movimentacao IN ('TRANSFERENCIA','TRANSFERENCIA_AUTORIZADA','VENDA_DIRETA')
        ORDER BY e.id,i.id
        """))
        resultado = []
        for linha in cursor.fetchall():
            item = dict(linha)
            status = item["status_documento"]
            tipo = item["tipo_movimentacao"]
            evento_esperado = {
                "Aberto": "RESERVA",
                "Cancelado": "CANCELAMENTO_ROMANEIO",
                "Estornado": "ESTORNO_ROMANEIO",
            }.get(status) or ("VENDA_DIRETA" if tipo == "VENDA_DIRETA" else "CONFIRMACAO_ROMANEIO")
            fisico_esperado = None
            if status == "Aberto" and item["item_ativo"]:
                fisico_esperado = "RESERVADO"
            elif (
                status == "Concluído"
                and item["item_ativo"]
                and str(item["unidade_estoque"] or "").upper() != "PACOTE"
                and item["ultima_expedicao_id"] == item["expedicao_id"]
                and item["ultima_acao"] == evento_esperado
            ):
                fisico_esperado = "EXPEDIDO" if tipo == "VENDA_DIRETA" else "TRANSFERIDO"

            divergencias = []
            if item["item_ativo"] and not item["evento_encontrado"]:
                divergencias.append(
                    "SOMENTE_LIVRO_LEGADO" if item["presente_legado"] else "EVENTO_CANONICO_AUSENTE"
                )
            if fisico_esperado and str(item["estado_atual"] or "").upper() != fisico_esperado:
                divergencias.append("ESTADO_FISICO_DIVERGENTE")
            item.update({
                "evento_esperado": evento_esperado,
                "evento_encontrado": evento_esperado if item["evento_encontrado"] else None,
                "estado_esperado": fisico_esperado,
                "divergencia": ",".join(divergencias) or None,
            })
            if divergencias or not somente_divergencias:
                resultado.append(item)
        return resultado
    finally:
        conn.close()
