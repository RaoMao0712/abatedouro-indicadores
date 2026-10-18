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
    cursor.execute(q("SELECT * FROM pallets WHERE id=?"), (pallet_id,))
    pallet = cursor.fetchone()
    if not pallet:
        raise ValueError("Pallet nao encontrado.")
    resultado = dict(pallet)
    cursor.execute(q("""SELECT ca.*, cx.codigo_caixa, cx.sku,
                              cx.quantidade_bandejas, cx.peso_liquido,
                              cx.quantidade_pacotes, cx.quantidade_galinhas
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
    return resultado


def consultar_pallet(pallet_id):
    conn = conectar()
    try:
        return consultar_pallet_cursor(conn.cursor(), pallet_id)
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
