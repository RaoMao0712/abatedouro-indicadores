"""Fonte única, somente leitura, para o ciclo funcional de encerramento de OP."""

from datetime import datetime, timedelta
from decimal import Decimal
import json

from database import conectar, q


ABERTA_EM_PROCESSAMENTO = "ABERTA_EM_PROCESSAMENTO"
PRONTA_PARA_ENCERRAMENTO = "PRONTA_PARA_ENCERRAMENTO"
BLOQUEADA_PARA_ENCERRAMENTO = "BLOQUEADA_PARA_ENCERRAMENTO"
ENCERRADA = "ENCERRADA"
ESTADO_INCONSISTENTE = "ESTADO_INCONSISTENTE"
STATUS_INATIVOS = {"ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO"}


def _decimal(valor):
    return Decimal(str(valor or 0))


def _agrupar(cursor, sql, parametros=()):
    cursor.execute(q(sql), parametros)
    return {int(linha["op_id"]): dict(linha) for linha in cursor.fetchall()}


def _motivos_estado(snapshot):
    status = str(snapshot["status"] or "")
    caixas = int(snapshot["caixas"] or 0)
    pendentes = int(snapshot["caixas_pendentes"] or 0)
    operacionais = int(snapshot["caixas_operacionais"] or 0)
    eventos = int(snapshot["eventos_formacao"] or 0)
    eventos_duplicados = int(snapshot["eventos_duplicados"] or 0)
    saldo_pi = _decimal(snapshot["saldo_pi"])
    bandejas_pi = _decimal(snapshot["bandejas_pi"])
    bandejas_caixas = _decimal(snapshot["bandejas_caixas"])
    peso = _decimal(snapshot["peso_liquido"])
    legada = str(snapshot.get("estoque_classificacao") or "") == "LEGADA"
    usa_pi = snapshot.get("usa_pi", str(snapshot.get("sku") or "") != "Galinha Inteira")
    peso_obrigatorio = snapshot.get(
        "peso_obrigatorio", str(snapshot.get("sku") or "") != "Galinha Inteira",
    )
    saldo_aves = _decimal(snapshot["quantidade_aves"]) - (
        _decimal(snapshot["bandejas_primaria"])
        + _decimal(snapshot["descartes"])
        + _decimal(snapshot["condenacoes"])
        + _decimal(snapshot["mortes_antes_pendura"])
        + _decimal(snapshot["mortes_na_gaiola"])
    )
    divergencias = []

    if saldo_pi < 0:
        divergencias.append(f"Saldo de PI negativo ({saldo_pi.normalize()}).")
    if int(snapshot["caixas_mistas"] or 0):
        divergencias.append("Há caixa vinculada a mais de uma OP.")
    if int(snapshot["codigos_duplicados"] or 0):
        divergencias.append("Há código de caixa duplicado.")
    if not legada and usa_pi and caixas and bandejas_pi != bandejas_caixas:
        divergencias.append(
            f"PI consumido ({bandejas_pi.normalize()}) diverge das bandejas das caixas "
            f"({bandejas_caixas.normalize()})."
        )
    if status == "Encerrada" and not legada:
        if pendentes:
            divergencias.append(f"OP encerrada com {pendentes} caixa(s) em PENDENTE_OP.")
        if operacionais != caixas:
            divergencias.append(
                f"OP encerrada com {operacionais} de {caixas} caixa(s) operacionais."
            )
        if caixas and eventos != caixas:
            divergencias.append(
                f"Movimentos de formação de PA: esperado {caixas}, encontrado {eventos}."
            )
        if eventos_duplicados:
            divergencias.append("Há movimento de formação de PA duplicado.")
        if int(snapshot["auditorias_sucesso"] or 0) == 0 and caixas:
            divergencias.append("Encerramento sem auditoria oficial persistida.")
    elif status == "Aberta" and operacionais:
        divergencias.append(f"OP aberta com {operacionais} caixa(s) já operacionais.")
    if int(snapshot["sucessos_incoerentes"] or 0):
        divergencias.append("Tentativa registrada como sucesso sem estado final coerente.")
    if not legada and saldo_pi == 0 and caixas == 0 and _decimal(snapshot["bandejas_primaria"]) > 0:
        divergencias.append("PI zerado sem caixas formadas.")
    if not legada and peso_obrigatorio and caixas and peso <= 0:
        divergencias.append("Caixas formadas sem peso líquido positivo.")
    if not legada and caixas and abs(saldo_aves) > Decimal("0.0001"):
        divergencias.append(f"Balanço de aves divergente em {saldo_aves.normalize()} ave(s).")
    return list(dict.fromkeys(divergencias))


def classificar_estado_funcional(snapshot):
    """Classifica um snapshot agregado; esta é a fonte única dos cinco estados."""
    motivos = _motivos_estado(snapshot)
    status = str(snapshot["status"] or "")
    saldo_pi = _decimal(snapshot["saldo_pi"])
    caixas = int(snapshot["caixas"] or 0)
    pendentes = int(snapshot["caixas_pendentes"] or 0)
    operacionais = int(snapshot["caixas_operacionais"] or 0)

    if motivos:
        estado = ESTADO_INCONSISTENTE
    elif status == "Encerrada":
        estado = ENCERRADA
    elif status != "Aberta":
        estado = BLOQUEADA_PARA_ENCERRAMENTO
        motivos = [f"Situação cadastral {status or 'não informada'} não permite encerramento."]
    elif saldo_pi > 0 or caixas == 0:
        estado = ABERTA_EM_PROCESSAMENTO
        motivos = ([f"Saldo de PI ainda é {saldo_pi.normalize()} bandeja(s)."]
                   if saldo_pi > 0 else ["Aguardando formação de caixas."])
    elif saldo_pi == 0 and pendentes == caixas and operacionais == 0:
        estado = PRONTA_PARA_ENCERRAMENTO
        motivos = []
    else:
        estado = BLOQUEADA_PARA_ENCERRAMENTO
        motivos = ["As caixas não estão integralmente concluídas em PENDENTE_OP."]
    return estado, motivos


def _carregar_snapshots(cursor, *, op_id=None, data_corte=None, limite=None,
                        incluir_abertas_anteriores=False):
    filtros, parametros = [], []
    if op_id is not None:
        filtros.append("id=?")
        parametros.append(int(op_id))
    if data_corte:
        filtros.append("(data>=? OR status='Aberta')" if incluir_abertas_anteriores else "data>=?")
        parametros.append(str(data_corte))
    where = " WHERE " + " AND ".join(filtros) if filtros else ""
    sql = ("SELECT id op_id,data,sku,status,quantidade_aves,mortes_antes_pendura,"
           "estoque_classificacao FROM ordens_producao" + where)
    sql += " ORDER BY id DESC"
    if limite:
        sql += " LIMIT ?"
        parametros.append(int(limite))
    cursor.execute(q(sql), tuple(parametros))
    ops = [dict(linha) for linha in cursor.fetchall()]
    if not ops:
        return []
    ids = [int(item["op_id"]) for item in ops]
    marcas = ",".join("?" for _ in ids)

    primaria = _agrupar(cursor, f"""SELECT op_id,COALESCE(SUM(quantidade_bandejas),0) bandejas_primaria
        FROM embalagem_primaria_apontamentos WHERE op_id IN ({marcas}) GROUP BY op_id""", ids)
    perdas = _agrupar(cursor, f"""SELECT op_id,
        COALESCE(SUM(CASE WHEN LOWER(COALESCE(categoria,'')) LIKE '%%conden%%'
                          THEN quantidade ELSE 0 END),0) condenacoes,
        COALESCE(SUM(CASE WHEN LOWER(COALESCE(categoria,'')) NOT LIKE '%%conden%%'
                           AND LOWER(TRIM(COALESCE(motivo,'')))<>'morte na gaiola'
                          THEN quantidade ELSE 0 END),0) descartes,
        COALESCE(SUM(CASE WHEN LOWER(TRIM(COALESCE(motivo,'')))='morte na gaiola'
                          THEN quantidade ELSE 0 END),0) mortes_na_gaiola
        FROM apontamentos_descartes WHERE op_id IN ({marcas})
          AND LOWER(unidade) IN ('aves','ave','unidade','unidades') GROUP BY op_id""", ids)
    pi = _agrupar(cursor, f"""SELECT op_id,
        COALESCE(SUM(CASE WHEN tipo LIKE 'ENTRADA%%' THEN quantidade_bandejas ELSE 0 END),0) entradas_pi,
        COALESCE(SUM(CASE WHEN tipo LIKE 'SAIDA%%' THEN quantidade_bandejas ELSE 0 END),0) bandejas_pi,
        COALESCE(SUM(CASE WHEN tipo LIKE 'ENTRADA%%' THEN quantidade_bandejas
                          WHEN tipo LIKE 'SAIDA%%' THEN -quantidade_bandejas
                          ELSE quantidade_bandejas END),0) saldo_pi
        FROM estoque_produto_intermediario WHERE op_id IN ({marcas}) GROUP BY op_id""", ids)
    caixas = _agrupar(cursor, f"""SELECT comp.op_id,
        COUNT(DISTINCT cx.id) caixas,
        COUNT(DISTINCT CASE WHEN COALESCE(cx.disponibilidade,'')='PENDENTE_OP'
             AND COALESCE(cx.estoque_operacional,0)=0 THEN cx.id END) caixas_pendentes,
        COUNT(DISTINCT CASE WHEN COALESCE(cx.estoque_operacional,0)=1 THEN cx.id END) caixas_operacionais,
        COALESCE(SUM(comp.quantidade_bandejas),0) bandejas_caixas,
        COALESCE(SUM(cx.peso_liquido*comp.quantidade_bandejas/NULLIF(
             (SELECT SUM(c2.quantidade_bandejas) FROM pa_caixa_composicao c2 WHERE c2.caixa_id=comp.caixa_id),0)),0) peso_liquido
        FROM pa_caixa_composicao comp JOIN pa_caixas cx ON cx.id=comp.caixa_id
        WHERE comp.op_id IN ({marcas}) AND UPPER(COALESCE(cx.status,''))
          NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO') GROUP BY comp.op_id""", ids)
    mistas = _agrupar(cursor, f"""SELECT c.op_id,COUNT(DISTINCT c.caixa_id) caixas_mistas
        FROM pa_caixa_composicao c WHERE c.op_id IN ({marcas}) AND EXISTS(
          SELECT 1 FROM pa_caixa_composicao c2 WHERE c2.caixa_id=c.caixa_id AND c2.op_id<>c.op_id)
        GROUP BY c.op_id""", ids)
    duplicados = _agrupar(cursor, f"""SELECT c.op_id,COUNT(DISTINCT cx.codigo_caixa) codigos_duplicados
        FROM pa_caixa_composicao c JOIN pa_caixas cx ON cx.id=c.caixa_id
        WHERE c.op_id IN ({marcas}) AND cx.codigo_caixa IN(
          SELECT codigo_caixa FROM pa_caixas GROUP BY codigo_caixa HAVING COUNT(*)>1)
        GROUP BY c.op_id""", ids)
    eventos = _agrupar(cursor, f"""SELECT c.op_id,
        COUNT(ev.id) eventos_formacao,
        COALESCE(SUM(CASE WHEN d.total>1 THEN 1 ELSE 0 END),0) eventos_duplicados
        FROM pa_caixa_composicao c
        JOIN pa_caixas cx ON cx.id=c.caixa_id
        LEFT JOIN estoque_eventos ev ON ev.caixa_id=c.caixa_id AND ev.acao='FORMACAO_ESTOQUE'
        LEFT JOIN (SELECT caixa_id,COUNT(*) total FROM estoque_eventos
                   WHERE acao='FORMACAO_ESTOQUE' GROUP BY caixa_id) d ON d.caixa_id=c.caixa_id
        WHERE c.op_id IN ({marcas}) AND UPPER(COALESCE(cx.status,''))
          NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO') GROUP BY c.op_id""", ids)
    auditorias = _agrupar(cursor, f"""SELECT op_id,COUNT(*) auditorias_sucesso
        FROM op_operacoes_auditoria WHERE op_id IN ({marcas}) AND tipo='ENCERRAMENTO_OP'
        GROUP BY op_id""", ids)
    tentativas = _agrupar(cursor, f"""SELECT t.op_id,
        MAX(t.criado_em) ultima_tentativa,
        MAX(CASE WHEN t.rn=1 AND t.resultado='REJEITADA' THEN t.motivo_rejeicao ELSE NULL END) ultima_falha,
        SUM(CASE WHEN t.resultado='SUCESSO' AND op.status<>'Encerrada' THEN 1 ELSE 0 END) sucessos_incoerentes
        FROM (SELECT base.*,ROW_NUMBER() OVER(PARTITION BY base.op_id ORDER BY base.id DESC) rn
              FROM op_encerramento_tentativas base WHERE base.op_id IN ({marcas})) t
        JOIN ordens_producao op ON op.id=t.op_id GROUP BY t.op_id""", ids)

    colecoes = (primaria, perdas, pi, caixas, mistas, duplicados, eventos, auditorias, tentativas)
    snapshots = []
    for op in ops:
        oid = int(op["op_id"])
        item = dict(op)
        for colecao in colecoes:
            item.update(colecao.get(oid, {}))
        for campo in ("bandejas_primaria", "descartes", "condenacoes", "mortes_na_gaiola",
                      "entradas_pi", "bandejas_pi", "saldo_pi",
                      "caixas", "caixas_pendentes", "caixas_operacionais", "bandejas_caixas",
                      "peso_liquido", "caixas_mistas", "codigos_duplicados", "eventos_formacao",
                      "eventos_duplicados", "auditorias_sucesso", "sucessos_incoerentes"):
            item.setdefault(campo, 0)
        item.setdefault("ultima_tentativa", None)
        item.setdefault("ultima_falha", None)
        item["estado_funcional"], item["motivos"] = classificar_estado_funcional(item)
        item["validacoes"] = "OK" if not item["motivos"] else "; ".join(item["motivos"])
        snapshots.append(item)
    return snapshots


def obter_estado_funcional_op(op_id):
    conn = conectar()
    try:
        itens = _carregar_snapshots(conn.cursor(), op_id=op_id)
        if not itens:
            raise ValueError("OP não encontrada.")
        return itens[0]
    finally:
        conn.close()


def montar_paineis_encerramento(args):
    """Retorna duas listas paginadas com número fixo de consultas, sem N+1."""
    pagina_prontas = max(1, int(args.get("pagina_prontas", 1) or 1))
    pagina_inconsistentes = max(1, int(args.get("pagina_inconsistentes", 1) or 1))
    por_pagina = min(50, max(5, int(args.get("por_pagina_encerramento", 20) or 20)))
    corte = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    conn = conectar()
    try:
        itens = _carregar_snapshots(
            conn.cursor(), data_corte=corte, limite=1000, incluir_abertas_anteriores=True,
        )
    finally:
        conn.close()
    prontas = [i for i in itens if i["estado_funcional"] == PRONTA_PARA_ENCERRAMENTO]
    inconsistentes = [i for i in itens if i["estado_funcional"] == ESTADO_INCONSISTENTE]

    def paginar(lista, pagina):
        total = len(lista)
        inicio = (pagina - 1) * por_pagina
        return {"itens": lista[inicio:inicio + por_pagina], "pagina": pagina,
                "por_pagina": por_pagina, "total": total,
                "tem_anterior": pagina > 1, "tem_proxima": inicio + por_pagina < total}
    return {"ops_prontas_encerramento": paginar(prontas, pagina_prontas),
            "estados_inconsistentes_producao": paginar(inconsistentes, pagina_inconsistentes)}


def auditar_integridade_encerramento(*, op_id=None, data_corte=None):
    """Executa exclusivamente SELECTs e devolve achados reproduzíveis."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        snapshots = _carregar_snapshots(cursor, op_id=op_id, data_corte=data_corte)
        filtro_orfa = ""
        parametros = []
        if data_corte:
            filtro_orfa = " AND COALESCE(cx.data_fabricacao,'')>=?"
            parametros.append(str(data_corte))
        orfas = []
        if op_id is None:
            cursor.execute(q("""SELECT cx.id,cx.codigo_caixa FROM pa_caixas cx
                WHERE UPPER(COALESCE(cx.status,'')) NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')
                  AND NOT EXISTS(SELECT 1 FROM pa_caixa_composicao c WHERE c.caixa_id=cx.id)""" + filtro_orfa), parametros)
            orfas = [dict(linha) for linha in cursor.fetchall()]
        filtros_tentativa = ["resultado='EM_PROCESSAMENTO'", "concluido_em IS NULL"]
        parametros_tentativa = []
        if op_id is not None:
            filtros_tentativa.append("op_id=?")
            parametros_tentativa.append(int(op_id))
        cursor.execute(q("SELECT op_id,correlation_id,criado_em FROM op_encerramento_tentativas WHERE "
                         + " AND ".join(filtros_tentativa)), parametros_tentativa)
        tentativas_abertas = [dict(linha) for linha in cursor.fetchall()]
    finally:
        conn.close()
    achados = []
    for item in snapshots:
        if item["estado_funcional"] == ESTADO_INCONSISTENTE:
            for motivo in item["motivos"]:
                achados.append({"criticidade": "CRITICA", "op_id": item["op_id"],
                                "estado": item["estado_funcional"], "motivo": motivo})
        elif item["estado_funcional"] == PRONTA_PARA_ENCERRAMENTO:
            achados.append({"criticidade": "ATENCAO", "op_id": item["op_id"],
                            "estado": item["estado_funcional"],
                            "motivo": "OP aberta com PI zero e caixas em PENDENTE_OP."})
    for caixa in orfas:
        achados.append({"criticidade": "CRITICA", "op_id": None,
                        "estado": ESTADO_INCONSISTENTE,
                        "motivo": f"Caixa sem OP: {caixa['codigo_caixa']} (id {caixa['id']})."})
    limite_abandono = datetime.now() - timedelta(minutes=5)
    for tentativa in tentativas_abertas:
        try:
            criada = datetime.fromisoformat(str(tentativa["criado_em"]).replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            criada = datetime.min
        if criada <= limite_abandono:
            achados.append({"criticidade": "CRITICA", "op_id": tentativa["op_id"],
                            "estado": ESTADO_INCONSISTENTE,
                            "motivo": ("Tentativa de encerramento sem resultado final. Identificador: "
                                       f"{tentativa['correlation_id']}.")})
    criticos = sum(1 for item in achados if item["criticidade"] == "CRITICA")
    return {"gerado_em": datetime.now().isoformat(timespec="seconds"),
            "somente_leitura": True, "filtros": {"op_id": op_id, "data_corte": data_corte},
            "ops_analisadas": len(snapshots), "criticos": criticos,
            "atencoes": len(achados) - criticos, "achados": achados}


def serializar_auditoria(resultado):
    return json.dumps(resultado, ensure_ascii=False, indent=2, default=str)
