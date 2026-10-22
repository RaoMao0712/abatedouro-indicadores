"""Fundacao transacional de palletizacao, sem autoridade sobre estoque."""

import json
from pathlib import Path

from database import DATABASE_URL, conectar, q, transaction
from .elegibilidade import avaliar_elegibilidade_expedicao


STATUS_BLOQUEADOS = {"ENCERRADO", "CANCELADO"}


def criar_estrutura_palletizacao():
    nome = (
        "20261018_p1_palletizacao.sql"
        if DATABASE_URL
        else "20261018_p1_palletizacao_sqlite.sql"
    )
    sql = (Path(__file__).resolve().parents[2] / "database" / nome).read_text(
        encoding="utf-8"
    )
    conn = conectar()
    try:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute(sql)
        else:
            conn.executescript(sql)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _id_inserido(cursor, sql, parametros):
    if DATABASE_URL:
        cursor.execute(q(sql + " RETURNING id"), parametros)
        return int(cursor.fetchone()["id"])
    cursor.execute(q(sql), parametros)
    return int(cursor.lastrowid)


def _serializar(dados):
    return json.dumps(dados or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _evento_por_chave(cursor, chave):
    cursor.execute(q("SELECT * FROM pallet_caixa_eventos WHERE idempotency_key=?"), (chave,))
    return cursor.fetchone()


def _validar_chave(chave):
    if not str(chave or "").strip():
        raise ValueError("idempotency_key e obrigatoria.")
    return str(chave).strip()


def _bloquear_idempotencia(cursor, chave):
    if DATABASE_URL:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (chave,))


def _bloqueio():
    return " FOR UPDATE" if DATABASE_URL else ""


def _obter_pallet(cursor, pallet_id, *, bloquear=False, operacional=False):
    cursor.execute(
        q("SELECT * FROM pallets WHERE id=?" + (_bloqueio() if bloquear else "")),
        (pallet_id,),
    )
    pallet = cursor.fetchone()
    if not pallet:
        raise ValueError("Pallet nao encontrado.")
    if operacional and pallet["status"] in STATUS_BLOQUEADOS:
        raise ValueError("Pallet encerrado ou cancelado nao aceita movimentacao.")
    return pallet


def _obter_caixa(cursor, caixa_id, *, bloquear=False):
    cursor.execute(
        q("SELECT * FROM pa_caixas WHERE id=?" + (_bloqueio() if bloquear else "")),
        (caixa_id,),
    )
    caixa = cursor.fetchone()
    if not caixa:
        raise ValueError("Caixa/posicao nao encontrada.")
    return caixa


def _registrar_evento(
    cursor,
    *,
    pallet_id,
    tipo_evento,
    usuario,
    idempotency_key,
    caixa_id=None,
    pallet_origem_id=None,
    pallet_destino_id=None,
    expedicao_id=None,
    evento_origem_id=None,
    justificativa=None,
    dados=None,
):
    return _id_inserido(
        cursor,
        """INSERT INTO pallet_caixa_eventos(
               pallet_id,caixa_id,tipo_evento,pallet_origem_id,pallet_destino_id,
               expedicao_id,evento_origem_id,usuario,justificativa,idempotency_key,dados_json
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pallet_id,
            caixa_id,
            tipo_evento,
            pallet_origem_id,
            pallet_destino_id,
            expedicao_id,
            evento_origem_id,
            usuario,
            justificativa,
            idempotency_key,
            _serializar(dados),
        ),
    )


def criar_pallet(
    *, usuario, idempotency_key, localizacao_atual_id=None, posicao_atual=None,
    observacao=None,
):
    """Cria pallet e PALLET_CRIADO atomicamente; retry devolve o mesmo pallet."""
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        existente = _evento_por_chave(cursor, chave)
        if existente:
            if existente["tipo_evento"] != "PALLET_CRIADO":
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return consultar_pallet_cursor(cursor, existente["pallet_id"])
        if localizacao_atual_id is not None:
            cursor.execute(q("SELECT 1 FROM locais_estoque WHERE id=?"), (localizacao_atual_id,))
            if not cursor.fetchone():
                raise ValueError("Localizacao nao encontrada.")
        if DATABASE_URL:
            pallet_id = _id_inserido(
                cursor,
                """INSERT INTO pallets(
                       localizacao_atual_id,posicao_atual,criado_por,observacao
                   ) VALUES(?,?,?,?)""",
                (localizacao_atual_id, posicao_atual, usuario, observacao),
            )
        else:
            cursor.execute("SELECT proximo FROM pallet_codigo_sequencia WHERE id=1")
            numero = int(cursor.fetchone()["proximo"])
            cursor.execute("UPDATE pallet_codigo_sequencia SET proximo=proximo+1 WHERE id=1")
            pallet_id = _id_inserido(
                cursor,
                """INSERT INTO pallets(
                       codigo,localizacao_atual_id,posicao_atual,criado_por,observacao
                   ) VALUES(?,?,?,?,?)""",
                (f"PALT-{numero:06d}", localizacao_atual_id, posicao_atual, usuario, observacao),
            )
        _registrar_evento(
            cursor, pallet_id=pallet_id, tipo_evento="PALLET_CRIADO",
            usuario=usuario, idempotency_key=chave,
            dados={"localizacao_atual_id": localizacao_atual_id, "posicao_atual": posicao_atual},
        )
        return consultar_pallet_cursor(cursor, pallet_id)


def consultar_pallet_cursor(cursor, pallet_id):
    cursor.execute(q("""SELECT p.*, le.nome AS localizacao_nome
                         FROM pallets p
                         LEFT JOIN locais_estoque le ON le.id=p.localizacao_atual_id
                         WHERE p.id=?"""), (pallet_id,))
    pallet = cursor.fetchone()
    if not pallet:
        raise ValueError("Pallet nao encontrado.")
    resultado = dict(pallet)
    cursor.execute(q("""SELECT ca.*, cx.codigo_caixa, cx.sku,
                              cx.quantidade_bandejas, cx.peso_liquido,
                              cx.quantidade_pacotes, cx.quantidade_galinhas,
                              cx.unidade_estoque, cx.apresentacao, cx.status,
                              cx.disponibilidade, cx.condicao,
                              cx.estoque_operacional, cx.local_estoque_id,
                              le.nome AS localizacao_nome
                       FROM pallet_caixas_atuais ca
                       JOIN pa_caixas cx ON cx.id=ca.caixa_id
                       LEFT JOIN locais_estoque le ON le.id=cx.local_estoque_id
                       WHERE ca.pallet_id=? ORDER BY ca.id"""), (pallet_id,))
    caixas = [dict(item) for item in cursor.fetchall()]
    resultado["caixas"] = caixas
    resultado["totais"] = {
        "caixas": len(caixas),
        "bandejas": sum(float(item.get("quantidade_bandejas") or 0) for item in caixas),
        "peso_liquido": sum(float(item.get("peso_liquido") or 0) for item in caixas),
        "pacotes": sum(int(item.get("quantidade_pacotes") or 0) for item in caixas),
        "aves": sum(int(item.get("quantidade_galinhas") or 0) for item in caixas),
    }
    cursor.execute(q("""SELECT comp.caixa_id, comp.op_id, comp.quantidade_bandejas
                       FROM pa_caixa_composicao comp
                       JOIN pallet_caixas_atuais ca ON ca.caixa_id=comp.caixa_id
                       WHERE ca.pallet_id=? ORDER BY comp.caixa_id, comp.id"""), (pallet_id,))
    resultado["composicao_op"] = [dict(item) for item in cursor.fetchall()]
    _enriquecer_pallet(resultado)
    return resultado


def consultar_pallet(pallet_id):
    conn = conectar()
    try:
        return consultar_pallet_cursor(conn.cursor(), pallet_id)
    finally:
        conn.close()


def _enriquecer_pallet(pallet):
    caixas = pallet.get("caixas", [])
    composicoes = pallet.get("composicao_op", [])
    por_caixa = {}
    for composicao in composicoes:
        por_caixa.setdefault(int(composicao["caixa_id"]), []).append(composicao)
    ops = {}
    for caixa in caixas:
        caixa_ops = por_caixa.get(int(caixa["caixa_id"]), [])
        caixa["ops"] = sorted({int(item["op_id"]) for item in caixa_ops})
        caixa["ops_texto"] = ", ".join(str(item) for item in caixa["ops"]) or "-"
        total_composicao = sum(float(item.get("quantidade_bandejas") or 0) for item in caixa_ops)
        for item in caixa_ops:
            op_id = int(item["op_id"])
            proporcao = (
                float(item.get("quantidade_bandejas") or 0) / total_composicao
                if total_composicao > 0
                else (1 / len(caixa_ops) if caixa_ops else 0)
            )
            grupo = ops.setdefault(op_id, {
                "op_id": op_id, "produto": caixa.get("sku"), "caixa_ids": set(),
                "peso": 0.0, "bandejas": 0.0, "pacotes": 0, "aves": 0,
            })
            if int(caixa["caixa_id"]) not in grupo["caixa_ids"]:
                grupo["caixa_ids"].add(int(caixa["caixa_id"]))
                grupo["peso"] += float(caixa.get("peso_liquido") or 0) * proporcao
                grupo["pacotes"] += round(int(caixa.get("quantidade_pacotes") or 0) * proporcao)
                grupo["aves"] += round(int(caixa.get("quantidade_galinhas") or 0) * proporcao)
            grupo["bandejas"] += float(item.get("quantidade_bandejas") or 0)
    pallet["ops"] = []
    for grupo in sorted(ops.values(), key=lambda item: item["op_id"]):
        grupo["quantidade_posicoes"] = len(grupo.pop("caixa_ids"))
        pallet["ops"].append(grupo)
    pallet["produtos"] = sorted({str(item.get("sku")) for item in caixas if item.get("sku")})
    pallet["produtos_texto"] = ", ".join(pallet["produtos"]) or "-"
    pallet["ops_texto"] = ", ".join(str(item["op_id"]) for item in pallet["ops"]) or "-"
    pallet["condicoes"] = sorted({str(item.get("condicao")) for item in caixas if item.get("condicao")})
    pallet["condicoes_texto"] = ", ".join(pallet["condicoes"]) or "-"
    pallet["payload_identificacao"] = pallet["codigo"]


def listar_locais_pallet():
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id,nome,tipo FROM locais_estoque WHERE ativo='Sim' ORDER BY nome")
        return [dict(item) for item in cursor.fetchall()]
    finally:
        conn.close()


def _pallet_atende_filtros(pallet, filtros):
    codigo = str(filtros.get("codigo") or "").strip().lower()
    status = str(filtros.get("status") or "").strip()
    produto = str(filtros.get("produto") or "").strip().lower()
    op = str(filtros.get("op") or "").strip()
    localizacao = str(filtros.get("localizacao") or "").strip()
    if codigo and codigo not in str(pallet["codigo"]).lower():
        return False
    if status and pallet["status"] != status:
        return False
    if produto and not any(produto in item.lower() for item in pallet["produtos"]):
        return False
    if op and op not in {str(item["op_id"]) for item in pallet["ops"]}:
        return False
    if localizacao and str(pallet.get("localizacao_atual_id") or "") != localizacao:
        return False
    return True


def listar_pallets(filtros=None):
    filtros = filtros or {}
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM pallets ORDER BY id DESC")
        pallets = [consultar_pallet_cursor(cursor, item["id"]) for item in cursor.fetchall()]
    finally:
        conn.close()
    return [item for item in pallets if _pallet_atende_filtros(item, filtros)]


def resumo_pallets():
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status,COUNT(*) AS total FROM pallets GROUP BY status")
        contagens = {item["status"]: int(item["total"]) for item in cursor.fetchall()}
    finally:
        conn.close()
    return {
        "total": sum(contagens.values()),
        "disponiveis": contagens.get("DISPONIVEL", 0),
        "reservados": contagens.get("RESERVADO", 0),
        "em_carregamento": contagens.get("PARCIALMENTE_CARREGADO", 0) + contagens.get("CARREGADO", 0),
        "encerrados": contagens.get("ENCERRADO", 0),
    }


def _resumo_disponibilidade(caixas):
    if not caixas:
        return "VAZIO"
    if any(item["restricoes"] for item in caixas):
        return "COM_RESTRICOES"
    if any(item["posicao_quantitativa_parcial"] for item in caixas):
        return "PARCIALMENTE_RESERVADO"
    reservadas = sum(1 for item in caixas if item["reserva_ativa"])
    if reservadas == len(caixas):
        return "RESERVADO"
    if reservadas:
        return "PARCIALMENTE_RESERVADO"
    return "DISPONIVEL"


def _enriquecer_estoque_pallet(pallet):
    _enriquecer_pallet(pallet)
    caixas = pallet["caixas"]
    for caixa in caixas:
        elegibilidade = avaliar_elegibilidade_expedicao(
            caixa, tipo_movimentacao="VENDA_DIRETA",
        )
        caixa["reserva_ativa"] = bool(
            caixa.get("reservado_expedicao_id")
            or int(caixa.get("quantidade_pacotes_reservados") or 0) > 0
            or caixa.get("romaneio_ativo_id")
        )
        caixa["posicao_quantitativa_parcial"] = bool(
            str(caixa.get("unidade_estoque") or "").upper() == "PACOTE"
            and 0 < int(caixa.get("quantidade_pacotes_reservados") or 0)
            < int(caixa.get("quantidade_pacotes") or 0)
        )
        caixa["restricoes"] = []
        if str(caixa.get("condicao") or "").upper() == "NAO_CONFORME":
            caixa["restricoes"].append("PNC")
        if not elegibilidade["elegivel"] and not caixa["reserva_ativa"]:
            caixa["restricoes"].append(elegibilidade["motivo_bloqueio"])
    pallet["totais"] = {
        "caixas": len(caixas),
        "bandejas": sum(float(item.get("quantidade_bandejas") or 0) for item in caixas),
        "peso_liquido": sum(float(item.get("peso_liquido") or 0) for item in caixas),
        "peso_bruto": sum(float(item.get("peso_bruto") or item.get("peso_liquido") or 0) for item in caixas),
        "pacotes": sum(int(item.get("quantidade_pacotes") or 0) for item in caixas),
        "aves": sum(int(item.get("quantidade_galinhas") or 0) for item in caixas),
    }
    alertas = []
    if len({str(item.get("status")) for item in caixas}) > 1:
        alertas.append("Status divergentes")
    if len(pallet["condicoes"]) > 1:
        alertas.append("MISTO POR CONDICAO")
    if len(pallet["produtos"]) > 1:
        alertas.append("MISTO POR PRODUTO")
    if len(pallet["ops"]) > 1:
        alertas.append("MISTO POR OP")
    if any(item["reserva_ativa"] for item in caixas):
        alertas.append("Reserva ativa")
    if any(item["posicao_quantitativa_parcial"] for item in caixas):
        alertas.append("Posicao quantitativa parcial")
    if any(item["restricoes"] for item in caixas):
        alertas.append("Conteudo com restricoes")
    pallet["alertas"] = alertas
    pallet["disponibilidade_agregada"] = _resumo_disponibilidade(caixas)
    for op in pallet["ops"]:
        itens = [item for item in caixas if op["op_id"] in item["ops"]]
        op["condicoes_texto"] = ", ".join(sorted({str(item.get("condicao")) for item in itens}))
        op["disponibilidade_agregada"] = _resumo_disponibilidade(itens)
        op["caixas"] = itens


def _pallet_estoque_atende_filtros(pallet, filtros):
    if not _pallet_atende_filtros(pallet, filtros):
        return False
    posicao = str(filtros.get("posicao") or "").strip().casefold()
    condicao = str(filtros.get("condicao") or "").strip().casefold()
    disponibilidade = str(filtros.get("disponibilidade") or "").strip()
    restricao = str(filtros.get("restricao") or "").strip()
    if posicao and posicao not in str(pallet.get("posicao_atual") or "").casefold():
        return False
    if condicao and condicao not in {item.casefold() for item in pallet["condicoes"]}:
        return False
    if disponibilidade and pallet["disponibilidade_agregada"] != disponibilidade:
        return False
    if restricao == "com" and not pallet["alertas"]:
        return False
    if restricao == "sem" and pallet["alertas"]:
        return False
    return True


def visao_estoque_por_pallet(filtros=None, filtros_sem_pallet=None):
    """Monta a leitura PALLET -> OP -> CAIXAS em consultas de quantidade constante."""
    filtros, filtros_sem_pallet = filtros or {}, filtros_sem_pallet or {}
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("""SELECT p.*,le.nome AS localizacao_nome
                          FROM pallets p LEFT JOIN locais_estoque le ON le.id=p.localizacao_atual_id
                          ORDER BY p.id DESC""")
        pallets = [dict(item) for item in cursor.fetchall()]
        por_id = {int(item["id"]): item for item in pallets}
        for pallet in pallets:
            pallet["caixas"], pallet["composicao_op"] = [], []
        cursor.execute("""SELECT ca.pallet_id,ca.caixa_id,cx.*,le.nome AS localizacao_nome
                          FROM pallet_caixas_atuais ca JOIN pa_caixas cx ON cx.id=ca.caixa_id
                          LEFT JOIN locais_estoque le ON le.id=cx.local_estoque_id
                          ORDER BY ca.pallet_id,ca.id""")
        por_caixa = {}
        for linha in cursor.fetchall():
            caixa = dict(linha)
            caixa["id"] = caixa["caixa_id"]
            caixa["romaneio_ativo_id"] = None
            por_caixa[int(caixa["caixa_id"])] = caixa
            por_id[int(caixa["pallet_id"])]["caixas"].append(caixa)
        cursor.execute("""SELECT comp.caixa_id,comp.op_id,comp.quantidade_bandejas
                          FROM pa_caixa_composicao comp JOIN pallet_caixas_atuais ca ON ca.caixa_id=comp.caixa_id
                          ORDER BY ca.pallet_id,comp.caixa_id,comp.id""")
        for linha in cursor.fetchall():
            item = dict(linha)
            caixa = por_caixa.get(int(item["caixa_id"]))
            if caixa:
                por_id[int(caixa["pallet_id"])]["composicao_op"].append(item)
        cursor.execute("""SELECT i.caixa_id,MIN(i.expedicao_id) AS expedicao_id
                          FROM expedicao_itens i JOIN expedicoes e ON e.id=i.expedicao_id
                          WHERE COALESCE(i.ativo,1)=1 AND e.status='Aberto' AND i.caixa_id IS NOT NULL
                          GROUP BY i.caixa_id""")
        for linha in cursor.fetchall():
            caixa = por_caixa.get(int(linha["caixa_id"]))
            if caixa:
                caixa["romaneio_ativo_id"] = linha["expedicao_id"]
        for pallet in pallets:
            _enriquecer_estoque_pallet(pallet)

        cursor.execute("""SELECT cx.*,le.nome AS localizacao_nome
                          FROM pa_caixas cx LEFT JOIN locais_estoque le ON le.id=cx.local_estoque_id
                          LEFT JOIN pallet_caixas_atuais ca ON ca.caixa_id=cx.id
                          WHERE ca.caixa_id IS NULL AND COALESCE(cx.estoque_operacional,0)=1
                          ORDER BY cx.codigo_caixa,cx.id""")
        sem_pallet = [dict(item) for item in cursor.fetchall()]
        ids_sem = [int(item["id"]) for item in sem_pallet]
        comps_sem = {}
        if ids_sem:
            marcadores = ",".join("?" for _ in ids_sem)
            cursor.execute(q(f"SELECT caixa_id,op_id FROM pa_caixa_composicao WHERE caixa_id IN ({marcadores})"), tuple(ids_sem))
            for item in cursor.fetchall():
                comps_sem.setdefault(int(item["caixa_id"]), set()).add(int(item["op_id"]))
        for caixa in sem_pallet:
            caixa["ops"] = sorted(comps_sem.get(int(caixa["id"]), set()))
            caixa["ops_texto"] = ", ".join(str(item) for item in caixa["ops"]) or "-"
    finally:
        conn.close()

    pallets_filtrados = [item for item in pallets if _pallet_estoque_atende_filtros(item, filtros)]
    def atende_sem(item):
        return (
            (not filtros_sem_pallet.get("op") or str(filtros_sem_pallet["op"]) in {str(op) for op in item["ops"]})
            and (not filtros_sem_pallet.get("produto") or str(filtros_sem_pallet["produto"]).casefold() in str(item.get("sku") or "").casefold())
            and (not filtros_sem_pallet.get("condicao") or str(filtros_sem_pallet["condicao"]).casefold() == str(item.get("condicao") or "").casefold())
            and (not filtros_sem_pallet.get("localizacao") or str(filtros_sem_pallet["localizacao"]) == str(item.get("local_estoque_id") or ""))
        )
    sem_pallet_filtrado = [item for item in sem_pallet if atende_sem(item)]
    ativos = [item for item in pallets if item["status"] not in STATUS_BLOQUEADOS]
    indicadores = {
        "pallets_ativos": len(ativos),
        "pallets_disponiveis": sum(item["disponibilidade_agregada"] == "DISPONIVEL" for item in ativos),
        "pallets_com_restricao": sum(item["disponibilidade_agregada"] == "COM_RESTRICOES" for item in ativos),
        "posicoes_palletizadas": sum(item["totais"]["caixas"] for item in ativos),
        "posicoes_sem_pallet": len(sem_pallet),
        "peso_palletizado": sum(item["totais"]["peso_liquido"] for item in ativos),
        "peso_sem_pallet": sum(float(item.get("peso_liquido") or 0) for item in sem_pallet),
    }
    return {"pallets": pallets_filtrados, "sem_pallet": sem_pallet_filtrado, "indicadores": indicadores}


def buscar_pallet_por_codigo(codigo):
    codigo = str(codigo or "").strip()
    if not codigo:
        return None
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT id FROM pallets WHERE LOWER(codigo)=LOWER(?)"), (codigo,))
        item = cursor.fetchone()
        return consultar_pallet_cursor(cursor, item["id"]) if item else None
    finally:
        conn.close()


def listar_eventos_pallet(pallet_id):
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""SELECT e.*, cx.codigo_caixa,
                                    po.codigo AS pallet_origem_codigo,
                                    pd.codigo AS pallet_destino_codigo
                             FROM pallet_caixa_eventos e
                             LEFT JOIN pa_caixas cx ON cx.id=e.caixa_id
                             LEFT JOIN pallets po ON po.id=e.pallet_origem_id
                             LEFT JOIN pallets pd ON pd.id=e.pallet_destino_id
                             WHERE e.pallet_id=? OR e.pallet_origem_id=?
                             ORDER BY e.criado_em DESC,e.id DESC"""),
                       (pallet_id, pallet_id))
        return [dict(item) for item in cursor.fetchall()]
    finally:
        conn.close()


def _normalizar_lista_ids(caixa_ids):
    try:
        ids = sorted({int(item) for item in caixa_ids})
    except (TypeError, ValueError):
        raise ValueError("Selecao de caixas/posicoes invalida.")
    if not ids or any(item <= 0 for item in ids):
        raise ValueError("Selecione ao menos uma caixa/posicao.")
    return ids


def _chave_item(chave_lote, caixa_id, total):
    return chave_lote if total == 1 else f"{chave_lote}:caixa:{caixa_id}"


def _compatibilidade_caixa(caixa):
    return (
        str(caixa.get("sku") or "").strip().casefold(),
        str(caixa.get("condicao") or "").strip().casefold(),
        str(caixa.get("unidade_estoque") or "CAIXA").strip().casefold(),
    )


def _descricao_compatibilidade(caixa):
    return (
        f"produto {caixa.get('sku') or 'nao informado'}, "
        f"condicao {caixa.get('condicao') or 'nao informada'} e "
        f"unidade {caixa.get('unidade_estoque') or 'CAIXA'}"
    )


def _validar_caixa_operacional(caixa):
    if int(caixa.get("estoque_operacional") or 0) != 1:
        raise ValueError(f"{caixa.get('codigo_caixa')}: posicao nao esta no estoque operacional.")
    status = str(caixa.get("status") or "").strip().upper()
    if status in {"ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO"}:
        raise ValueError(f"{caixa.get('codigo_caixa')}: posicao estornada ou cancelada.")
    if str(caixa.get("condicao") or "").strip().upper() != "CONFORME":
        raise ValueError(f"{caixa.get('codigo_caixa')}: condicao nao permite palletizacao.")


def _caixas_do_pallet_cursor(cursor, pallet_id, *, excluir_ids=()):
    parametros = [pallet_id]
    exclusao = ""
    if excluir_ids:
        marcadores = ",".join("?" for _ in excluir_ids)
        exclusao = f" AND cx.id NOT IN ({marcadores})"
        parametros.extend(excluir_ids)
    cursor.execute(q(f"""SELECT cx.*
                            FROM pallet_caixas_atuais ca
                            JOIN pa_caixas cx ON cx.id=ca.caixa_id
                            WHERE ca.pallet_id=?{exclusao}
                            ORDER BY cx.id"""), tuple(parametros))
    return [dict(item) for item in cursor.fetchall()]


def _validar_compatibilidade(destino, existentes, novas):
    todas = list(existentes) + list(novas)
    if not todas:
        return
    referencia = _compatibilidade_caixa(todas[0])
    incompativeis = [item for item in todas[1:] if _compatibilidade_caixa(item) != referencia]
    if incompativeis:
        primeira = incompativeis[0]
        raise ValueError(
            f"Pallet {destino['codigo']} exige conteudo homogeneo; "
            f"{primeira.get('codigo_caixa')} possui {_descricao_compatibilidade(primeira)}, "
            f"incompativel com {_descricao_compatibilidade(todas[0])}."
        )


def listar_caixas_disponiveis_palletizacao(filtros=None):
    """Lista posições vinculáveis sem reutilizar ou alterar elegibilidade de expedição."""
    filtros = filtros or {}
    condicoes = [
        "COALESCE(cx.estoque_operacional,0)=1",
        "UPPER(COALESCE(cx.status,'')) NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')",
        "UPPER(COALESCE(cx.condicao,''))='CONFORME'",
        "ca.caixa_id IS NULL",
    ]
    parametros = []
    if str(filtros.get("op") or "").strip():
        try:
            op_id = int(filtros["op"])
        except (TypeError, ValueError):
            return []
        condicoes.append("EXISTS(SELECT 1 FROM pa_caixa_composicao fop WHERE fop.caixa_id=cx.id AND fop.op_id=?)")
        parametros.append(op_id)
    if str(filtros.get("produto") or "").strip():
        condicoes.append("LOWER(COALESCE(cx.sku,'')) LIKE LOWER(?)")
        parametros.append(f"%{str(filtros['produto']).strip()}%")
    if str(filtros.get("codigo") or "").strip():
        condicoes.append("LOWER(COALESCE(cx.codigo_caixa,'')) LIKE LOWER(?)")
        parametros.append(f"%{str(filtros['codigo']).strip()}%")
    if str(filtros.get("localizacao") or "").strip():
        condicoes.append("CAST(cx.local_estoque_id AS TEXT)=?")
        parametros.append(str(filtros["localizacao"]).strip())
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(f"""SELECT cx.*,le.nome AS localizacao_nome
                                FROM pa_caixas cx
                                LEFT JOIN pallet_caixas_atuais ca ON ca.caixa_id=cx.id
                                LEFT JOIN locais_estoque le ON le.id=cx.local_estoque_id
                                WHERE {' AND '.join(condicoes)}
                                ORDER BY cx.codigo_caixa,cx.id"""), tuple(parametros))
        caixas = [dict(item) for item in cursor.fetchall()]
        if not caixas:
            return []
        ids = [item["id"] for item in caixas]
        marcadores = ",".join("?" for _ in ids)
        cursor.execute(q(f"""SELECT caixa_id,op_id,quantidade_bandejas
                                FROM pa_caixa_composicao
                                WHERE caixa_id IN ({marcadores})
                                ORDER BY caixa_id,op_id"""), tuple(ids))
        por_caixa = {}
        for item in cursor.fetchall():
            por_caixa.setdefault(int(item["caixa_id"]), []).append(dict(item))
        for caixa in caixas:
            composicoes = por_caixa.get(int(caixa["id"]), [])
            caixa["ops"] = sorted({int(item["op_id"]) for item in composicoes})
            caixa["ops_texto"] = ", ".join(str(item) for item in caixa["ops"]) or "-"
        return caixas
    finally:
        conn.close()


def resumo_organizacao_op(op_id):
    """Fotografia derivada das posições PA da OP e de seus vínculos logísticos."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT id,sku,status FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP nao encontrada.")
        cursor.execute(q("""SELECT DISTINCT cx.*,ca.pallet_id,p.codigo AS pallet_codigo,
                                    p.status AS pallet_status,p.posicao_atual,
                                    le.nome AS pallet_localizacao
                               FROM pa_caixa_composicao comp
                               JOIN pa_caixas cx ON cx.id=comp.caixa_id
                               LEFT JOIN pallet_caixas_atuais ca ON ca.caixa_id=cx.id
                               LEFT JOIN pallets p ON p.id=ca.pallet_id
                               LEFT JOIN locais_estoque le ON le.id=p.localizacao_atual_id
                              WHERE comp.op_id=?
                                AND UPPER(COALESCE(cx.status,'')) NOT IN
                                    ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')
                              ORDER BY cx.id"""), (op_id,))
        caixas = [dict(item) for item in cursor.fetchall()]
        por_pallet = {}
        sem_pallet = []
        for caixa in caixas:
            if caixa.get("pallet_id") is None:
                sem_pallet.append(caixa)
                continue
            grupo = por_pallet.setdefault(int(caixa["pallet_id"]), {
                "id": int(caixa["pallet_id"]), "codigo": caixa["pallet_codigo"],
                "status": caixa["pallet_status"], "posicao": caixa.get("posicao_atual"),
                "localizacao": caixa.get("pallet_localizacao"), "caixas": [],
            })
            grupo["caixas"].append(caixa)
        def totais(itens):
            return {
                "posicoes": len(itens),
                "peso": sum(float(item.get("peso_liquido") or 0) for item in itens),
                "bandejas": sum(float(item.get("quantidade_bandejas") or 0) for item in itens),
                "pacotes": sum(int(item.get("quantidade_pacotes") or 0) for item in itens),
                "aves": sum(int(item.get("quantidade_galinhas") or 0) for item in itens),
            }
        pallets = list(por_pallet.values())
        for pallet in pallets:
            pallet["totais"] = totais(pallet["caixas"])
        total = len(caixas)
        organizadas = total - len(sem_pallet)
        return {
            "op": dict(op), "caixas": caixas, "sem_pallet": sem_pallet,
            "pallets": pallets, "totais": totais(caixas),
            "organizadas": organizadas, "nao_organizadas": len(sem_pallet),
            "percentual": round((organizadas * 100 / total), 1) if total else 100.0,
            "completa": not sem_pallet,
        }
    finally:
        conn.close()


def validar_organizacao_para_encerramento(op_id, *, justificativa=None, usuario=None,
                                           idempotency_key=None):
    """Não interfere no preflight produtivo; apenas audita a exceção logística."""
    resumo = resumo_organizacao_op(op_id)
    if resumo["completa"]:
        return resumo
    motivo = str(justificativa or "").strip()
    if len(motivo) < 5:
        raise ValueError(
            f"A OP possui {resumo['nao_organizadas']} caixa(s)/posicao(oes) sem pallet. "
            "Informe uma justificativa explicita para prosseguir."
        )
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        cursor.execute(q("SELECT * FROM op_palletizacao_excecoes WHERE idempotency_key=?"), (chave,))
        existente = cursor.fetchone()
        if existente:
            if int(existente["op_id"]) != int(op_id):
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return resumo
        cursor.execute(q("""INSERT INTO op_palletizacao_excecoes(
            op_id,justificativa,usuario,idempotency_key,caixas_sem_pallet
        ) VALUES(?,?,?,?,?)"""), (
            op_id, motivo, usuario or "Usuario nao identificado", chave,
            resumo["nao_organizadas"],
        ))
    resumo["excecao_registrada"] = True
    return resumo


def listar_pallets_destino(pallet_origem_id):
    return [
        item for item in listar_pallets()
        if int(item["id"]) != int(pallet_origem_id) and item["status"] not in STATUS_BLOQUEADOS
    ]


def adicionar_caixa(
    pallet_id, caixa_id, *, usuario, idempotency_key, justificativa=None, dados=None,
):
    return adicionar_caixas(
        pallet_id, [caixa_id], usuario=usuario, idempotency_key=idempotency_key,
        justificativa=justificativa, dados=dados,
    )


def adicionar_caixas(
    pallet_id, caixa_ids, *, usuario, idempotency_key, justificativa=None, dados=None,
):
    ids = _normalizar_lista_ids(caixa_ids)
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        chaves = [_chave_item(chave, caixa_id, len(ids)) for caixa_id in ids]
        existentes = [_evento_por_chave(cursor, item) for item in chaves]
        if any(existentes):
            if not all(existentes) or any(
                item["tipo_evento"] != "CAIXA_ADICIONADA"
                or int(item["pallet_id"]) != int(pallet_id)
                or int(item["caixa_id"]) != caixa_id
                for item, caixa_id in zip(existentes, ids)
            ):
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return consultar_pallet_cursor(cursor, pallet_id)
        destino = dict(_obter_pallet(cursor, pallet_id, bloquear=True, operacional=True))
        caixas = []
        for caixa_id in ids:
            caixa = dict(_obter_caixa(cursor, caixa_id, bloquear=True))
            _validar_caixa_operacional(caixa)
            cursor.execute(q("SELECT pallet_id FROM pallet_caixas_atuais WHERE caixa_id=?" + _bloqueio()), (caixa_id,))
            vinculo = cursor.fetchone()
            if vinculo:
                raise ValueError(f"{caixa.get('codigo_caixa')}: caixa/posicao ja vinculada a um pallet.")
            caixas.append(caixa)
        _validar_compatibilidade(destino, _caixas_do_pallet_cursor(cursor, pallet_id), caixas)
        for caixa, chave_item in zip(caixas, chaves):
            evento_id = _registrar_evento(
                cursor, pallet_id=pallet_id, caixa_id=caixa["id"],
                tipo_evento="CAIXA_ADICIONADA", pallet_destino_id=pallet_id,
                usuario=usuario, idempotency_key=chave_item,
                justificativa=justificativa, dados={**(dados or {}), "lote": chave},
            )
            _id_inserido(
                cursor,
                """INSERT INTO pallet_caixas_atuais(
                       pallet_id,caixa_id,adicionado_por,evento_origem_id
                   ) VALUES(?,?,?,?)""",
                (pallet_id, caixa["id"], usuario, evento_id),
            )
        return consultar_pallet_cursor(cursor, pallet_id)


def remover_caixa(
    pallet_id, caixa_id, *, usuario, idempotency_key, justificativa=None, dados=None,
):
    return remover_caixas(
        pallet_id, [caixa_id], usuario=usuario, idempotency_key=idempotency_key,
        justificativa=justificativa, dados=dados,
    )


def remover_caixas(
    pallet_id, caixa_ids, *, usuario, idempotency_key, justificativa=None, dados=None,
):
    ids = _normalizar_lista_ids(caixa_ids)
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        chaves = [_chave_item(chave, caixa_id, len(ids)) for caixa_id in ids]
        existentes = [_evento_por_chave(cursor, item) for item in chaves]
        if any(existentes):
            if not all(existentes) or any(
                item["tipo_evento"] != "CAIXA_REMOVIDA"
                or int(item["pallet_id"]) != int(pallet_id)
                or int(item["caixa_id"]) != caixa_id
                for item, caixa_id in zip(existentes, ids)
            ):
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return consultar_pallet_cursor(cursor, pallet_id)
        _obter_pallet(cursor, pallet_id, bloquear=True, operacional=True)
        vinculos = []
        for caixa_id in ids:
            caixa = dict(_obter_caixa(cursor, caixa_id, bloquear=True))
            cursor.execute(q("SELECT * FROM pallet_caixas_atuais WHERE caixa_id=?" + _bloqueio()), (caixa_id,))
            vinculo = cursor.fetchone()
            if not vinculo or int(vinculo["pallet_id"]) != int(pallet_id):
                raise ValueError(f"{caixa.get('codigo_caixa')}: caixa/posicao nao pertence ao pallet informado.")
            vinculos.append((caixa, dict(vinculo)))
        for (caixa, vinculo), chave_item in zip(vinculos, chaves):
            _registrar_evento(
                cursor, pallet_id=pallet_id, caixa_id=caixa["id"],
                tipo_evento="CAIXA_REMOVIDA", pallet_origem_id=pallet_id,
                evento_origem_id=vinculo["evento_origem_id"], usuario=usuario,
                idempotency_key=chave_item, justificativa=justificativa,
                dados={**(dados or {}), "lote": chave},
            )
            cursor.execute(q("DELETE FROM pallet_caixas_atuais WHERE id=?"), (vinculo["id"],))
        return consultar_pallet_cursor(cursor, pallet_id)


def transferir_caixa(
    pallet_origem_id, pallet_destino_id, caixa_id, *, usuario, idempotency_key,
    justificativa=None, dados=None,
):
    return transferir_caixas(
        pallet_origem_id, pallet_destino_id, [caixa_id], usuario=usuario,
        idempotency_key=idempotency_key, justificativa=justificativa, dados=dados,
    )


def transferir_caixas(
    pallet_origem_id, pallet_destino_id, caixa_ids, *, usuario, idempotency_key,
    justificativa=None, dados=None,
):
    if int(pallet_origem_id) == int(pallet_destino_id):
        raise ValueError("Pallet de origem e destino devem ser diferentes.")
    ids = _normalizar_lista_ids(caixa_ids)
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        chaves = [_chave_item(chave, caixa_id, len(ids)) for caixa_id in ids]
        existentes = [_evento_por_chave(cursor, item) for item in chaves]
        if any(existentes):
            if not all(existentes) or any(
                item["tipo_evento"] != "CAIXA_TRANSFERIDA"
                or int(item["pallet_origem_id"]) != int(pallet_origem_id)
                or int(item["pallet_destino_id"]) != int(pallet_destino_id)
                or int(item["caixa_id"]) != caixa_id
                for item, caixa_id in zip(existentes, ids)
            ):
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return consultar_pallet_cursor(cursor, pallet_destino_id)
        pallets = {}
        for pallet_id in sorted((int(pallet_origem_id), int(pallet_destino_id))):
            pallets[pallet_id] = dict(_obter_pallet(cursor, pallet_id, bloquear=True, operacional=True))
        caixas, vinculos = [], []
        for caixa_id in ids:
            caixa = dict(_obter_caixa(cursor, caixa_id, bloquear=True))
            _validar_caixa_operacional(caixa)
            cursor.execute(q("SELECT * FROM pallet_caixas_atuais WHERE caixa_id=?" + _bloqueio()), (caixa_id,))
            vinculo = cursor.fetchone()
            if not vinculo or int(vinculo["pallet_id"]) != int(pallet_origem_id):
                raise ValueError(f"{caixa.get('codigo_caixa')}: caixa/posicao nao pertence ao pallet de origem.")
            caixas.append(caixa)
            vinculos.append(dict(vinculo))
        destino = pallets[int(pallet_destino_id)]
        _validar_compatibilidade(destino, _caixas_do_pallet_cursor(cursor, pallet_destino_id), caixas)
        for caixa, vinculo, chave_item in zip(caixas, vinculos, chaves):
            evento_id = _registrar_evento(
                cursor, pallet_id=pallet_destino_id, caixa_id=caixa["id"],
                tipo_evento="CAIXA_TRANSFERIDA", pallet_origem_id=pallet_origem_id,
                pallet_destino_id=pallet_destino_id, evento_origem_id=vinculo["evento_origem_id"],
                usuario=usuario, idempotency_key=chave_item, justificativa=justificativa,
                dados={**(dados or {}), "lote": chave},
            )
            cursor.execute(q("""UPDATE pallet_caixas_atuais
                                SET pallet_id=?,adicionado_em=CURRENT_TIMESTAMP,
                                    adicionado_por=?,evento_origem_id=?,versao=versao+1
                                WHERE id=?"""),
                           (pallet_destino_id, usuario, evento_id, vinculo["id"]))
        return consultar_pallet_cursor(cursor, pallet_destino_id)
