"""Fundacao transacional de palletizacao, sem autoridade sobre estoque."""

import json
from pathlib import Path

from database import DATABASE_URL, conectar, q, transaction


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
                              cx.disponibilidade, cx.condicao
                       FROM pallet_caixas_atuais ca
                       JOIN pa_caixas cx ON cx.id=ca.caixa_id
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


def adicionar_caixa(
    pallet_id, caixa_id, *, usuario, idempotency_key, justificativa=None, dados=None,
):
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        existente = _evento_por_chave(cursor, chave)
        if existente:
            if (existente["tipo_evento"] != "CAIXA_ADICIONADA" or
                    int(existente["pallet_id"]) != int(pallet_id) or
                    int(existente["caixa_id"]) != int(caixa_id)):
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return consultar_pallet_cursor(cursor, pallet_id)
        _obter_caixa(cursor, caixa_id, bloquear=True)
        _obter_pallet(cursor, pallet_id, bloquear=True, operacional=True)
        cursor.execute(q("SELECT pallet_id FROM pallet_caixas_atuais WHERE caixa_id=?"), (caixa_id,))
        if cursor.fetchone():
            raise ValueError("Caixa/posicao ja vinculada a um pallet.")
        evento_id = _registrar_evento(
            cursor, pallet_id=pallet_id, caixa_id=caixa_id,
            tipo_evento="CAIXA_ADICIONADA", pallet_destino_id=pallet_id,
            usuario=usuario, idempotency_key=chave, justificativa=justificativa, dados=dados,
        )
        _id_inserido(
            cursor,
            """INSERT INTO pallet_caixas_atuais(
                   pallet_id,caixa_id,adicionado_por,evento_origem_id
               ) VALUES(?,?,?,?)""",
            (pallet_id, caixa_id, usuario, evento_id),
        )
        return consultar_pallet_cursor(cursor, pallet_id)


def remover_caixa(
    pallet_id, caixa_id, *, usuario, idempotency_key, justificativa=None, dados=None,
):
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        existente = _evento_por_chave(cursor, chave)
        if existente:
            if (existente["tipo_evento"] != "CAIXA_REMOVIDA" or
                    int(existente["pallet_id"]) != int(pallet_id) or
                    int(existente["caixa_id"]) != int(caixa_id)):
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return consultar_pallet_cursor(cursor, pallet_id)
        _obter_caixa(cursor, caixa_id, bloquear=True)
        _obter_pallet(cursor, pallet_id, bloquear=True, operacional=True)
        cursor.execute(q("SELECT * FROM pallet_caixas_atuais WHERE caixa_id=?" + _bloqueio()), (caixa_id,))
        vinculo = cursor.fetchone()
        if not vinculo or int(vinculo["pallet_id"]) != int(pallet_id):
            raise ValueError("Caixa/posicao nao pertence ao pallet informado.")
        _registrar_evento(
            cursor, pallet_id=pallet_id, caixa_id=caixa_id,
            tipo_evento="CAIXA_REMOVIDA", pallet_origem_id=pallet_id,
            evento_origem_id=vinculo["evento_origem_id"], usuario=usuario,
            idempotency_key=chave, justificativa=justificativa, dados=dados,
        )
        cursor.execute(q("DELETE FROM pallet_caixas_atuais WHERE id=?"), (vinculo["id"],))
        return consultar_pallet_cursor(cursor, pallet_id)


def transferir_caixa(
    pallet_origem_id, pallet_destino_id, caixa_id, *, usuario, idempotency_key,
    justificativa=None, dados=None,
):
    if int(pallet_origem_id) == int(pallet_destino_id):
        raise ValueError("Pallet de origem e destino devem ser diferentes.")
    chave = _validar_chave(idempotency_key)
    with transaction() as conn:
        cursor = conn.cursor()
        _bloquear_idempotencia(cursor, chave)
        existente = _evento_por_chave(cursor, chave)
        if existente:
            if (existente["tipo_evento"] != "CAIXA_TRANSFERIDA" or
                    int(existente["pallet_origem_id"]) != int(pallet_origem_id) or
                    int(existente["pallet_destino_id"]) != int(pallet_destino_id) or
                    int(existente["caixa_id"]) != int(caixa_id)):
                raise ValueError("idempotency_key ja usada por outra operacao.")
            return consultar_pallet_cursor(cursor, pallet_destino_id)
        _obter_caixa(cursor, caixa_id, bloquear=True)
        for pallet_id in sorted((int(pallet_origem_id), int(pallet_destino_id))):
            _obter_pallet(cursor, pallet_id, bloquear=True, operacional=True)
        cursor.execute(q("SELECT * FROM pallet_caixas_atuais WHERE caixa_id=?" + _bloqueio()), (caixa_id,))
        vinculo = cursor.fetchone()
        if not vinculo or int(vinculo["pallet_id"]) != int(pallet_origem_id):
            raise ValueError("Caixa/posicao nao pertence ao pallet de origem.")
        evento_id = _registrar_evento(
            cursor, pallet_id=pallet_destino_id, caixa_id=caixa_id,
            tipo_evento="CAIXA_TRANSFERIDA", pallet_origem_id=pallet_origem_id,
            pallet_destino_id=pallet_destino_id, evento_origem_id=vinculo["evento_origem_id"],
            usuario=usuario, idempotency_key=chave, justificativa=justificativa, dados=dados,
        )
        cursor.execute(q("""UPDATE pallet_caixas_atuais
                            SET pallet_id=?,adicionado_em=CURRENT_TIMESTAMP,
                                adicionado_por=?,evento_origem_id=?,versao=versao+1
                            WHERE id=?"""),
                       (pallet_destino_id, usuario, evento_id, vinculo["id"]))
        return consultar_pallet_cursor(cursor, pallet_destino_id)
