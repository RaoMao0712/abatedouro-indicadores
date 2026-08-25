"""Reconciliação documental estrita do único PNC legado autorizado na P1.1.1."""

from datetime import datetime
import json

from database import DATABASE_URL, conectar, q, transaction


NUMERO_ALVO = "PNC-LEG-2026_07_30_AGUARDANDO_LIBERACAO"
ACAO_RECONCILIACAO = "RECONCILIACAO_ESTADO_LEGADO_P1_1_1"
ACAO_ROLLBACK = "ROLLBACK_RECONCILIACAO_ESTADO_LEGADO_P1_1_1"
ORIGEM = "comando-administrativo-p1.1.1"


def _agora():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _tabela_existe(cursor, nome):
    if DATABASE_URL:
        cursor.execute("SELECT to_regclass(%s) AS nome", (nome,))
        return cursor.fetchone()["nome"] is not None
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (nome,))
    return cursor.fetchone() is not None


def _eventos(cursor, registro_id):
    cursor.execute(q("""SELECT id,acao,status_anterior,status_novo,criado_em,detalhes
        FROM pa_nao_conforme_eventos WHERE pa_nao_conforme_id=? ORDER BY id"""),
        (registro_id,))
    return [dict(item) for item in cursor.fetchall()]


def _diagnosticar_cursor(cursor, *, bloquear=False):
    sufixo = " FOR UPDATE" if bloquear and DATABASE_URL else ""
    cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE numero=?" + sufixo), (NUMERO_ALVO,))
    registro = cursor.fetchone()
    if not registro:
        return {"alvo": NUMERO_ALVO, "apto": False, "erros": ["registro alvo inexistente"]}
    registro = dict(registro)
    cursor.execute(q("""SELECT * FROM pa_nao_conforme_solicitacoes
        WHERE pa_nao_conforme_id=? AND status='APROVADA' ORDER BY id"""), (registro["id"],))
    aprovadas = [dict(item) for item in cursor.fetchall()]
    eventos = _eventos(cursor, registro["id"])
    reconciliacoes = [item for item in eventos if item["acao"] == ACAO_RECONCILIACAO]
    rollbacks = [item for item in eventos if item["acao"] == ACAO_ROLLBACK]
    incompatíveis = [item for item in eventos if (
        "DESCARTE" in str(item["acao"] or "").upper()
        or "REPROCESS" in str(item["acao"] or "").upper()
        or str(item["acao"] or "").upper() == "RETRABALHO"
    )]
    relacionados = {}
    for tabela in ("pnc_reprocessamentos", "pnc_romaneios_descarte"):
        if _tabela_existe(cursor, tabela):
            cursor.execute(q(f"SELECT COUNT(*) AS total FROM {tabela} WHERE pa_nao_conforme_id=?"),
                           (registro["id"],))
            relacionados[tabela] = int(cursor.fetchone()["total"] or 0)
        else:
            relacionados[tabela] = 0

    erros = []
    ja_aplicada = registro["status"] == "LIBERADO" and len(reconciliacoes) == 1 and not rollbacks
    if not ja_aplicada:
        if registro["status"] != "BLOQUEADO":
            erros.append(f"estado atual divergente: {registro['status']}")
        if len(aprovadas) != 1:
            erros.append(f"quantidade de solicitações aprovadas divergente: {len(aprovadas)}")
        if int(registro["saldo_bloqueado_g"] or 0) != 0:
            erros.append("saldo bloqueado não está zerado")
        if int(registro["saldo_pendente_g"] or 0) != 0:
            erros.append("saldo pendente não está zerado")
        if int(registro["caixas_bloqueadas"] or 0) != 0 or int(registro["bandejas_bloqueadas"] or 0) != 0:
            erros.append("controles físicos bloqueados não estão zerados")
        total_posicao = sum(int(registro[nome] or 0) for nome in (
            "saldo_operacional_g", "saldo_reservado_operacional_g", "saldo_destinado_g"
        ))
        if total_posicao != int(registro["saldo_inicial_g"] or 0):
            erros.append("posição operacional não reconcilia com o saldo inicial")
        if registro.get("decisao") not in (None, "", "LIBERAR"):
            erros.append(f"destinação documental incompatível: {registro['decisao']}")
        if incompatíveis or any(relacionados.values()):
            erros.append("há descarte, reprocessamento ou destinação incompatível")
        if any(item["status_novo"] == "LIBERADO" for item in eventos):
            erros.append("já existe histórico anterior de transição para LIBERADO")
        if reconciliacoes:
            erros.append("já existe evento de reconciliação sem estado LIBERADO íntegro")

    solicitacao = aprovadas[0] if len(aprovadas) == 1 else None
    aprovacao = None
    if solicitacao:
        if not (
            int(solicitacao["peso_g"] or 0) == int(registro["saldo_inicial_g"] or 0)
            and int(solicitacao["caixas"] or 0) == int(registro["caixas_iniciais"] or 0)
            and int(solicitacao["bandejas"] or 0) == int(registro["bandejas_iniciais"] or 0)
        ):
            erros.append("a solicitação aprovada não comprova liberação integral")
        for item in eventos:
            if item["acao"] != "APROVACAO_LIBERACAO":
                continue
            try:
                detalhes = json.loads(item["detalhes"] or "{}")
            except (TypeError, ValueError):
                detalhes = {}
            if int(detalhes.get("solicitacao_id") or 0) == int(solicitacao["id"]):
                aprovacao = {**item, "detalhes_json": detalhes}
                break
        if not aprovacao:
            erros.append("evento de aprovação vinculado à solicitação não encontrado")
        else:
            antes = aprovacao["detalhes_json"].get("antes") or {}
            depois = aprovacao["detalhes_json"].get("depois") or {}
            if not (
                int(antes.get("saldo_bloqueado_g") or 0) == int(solicitacao["peso_g"])
                and int(depois.get("saldo_bloqueado_g") or 0) == 0
                and int(depois.get("saldo_operacional_g") or 0) == int(solicitacao["peso_g"])
            ):
                erros.append("evento de aprovação não comprova a movimentação integral")

    snapshot_estoque = {nome: int(registro[nome] or 0) for nome in (
        "saldo_inicial_g", "saldo_bloqueado_g", "saldo_pendente_g", "saldo_operacional_g",
        "saldo_reservado_operacional_g", "saldo_destinado_g", "caixas_iniciais",
        "bandejas_iniciais", "caixas_bloqueadas", "bandejas_bloqueadas",
    )}
    return {
        "alvo": NUMERO_ALVO, "registro_id": registro["id"], "status": registro["status"],
        "apto": not erros, "ja_aplicada": ja_aplicada, "erros": erros,
        "solicitacao_aprovada_id": solicitacao["id"] if solicitacao else None,
        "evento_aprovacao_id": aprovacao["id"] if aprovacao else None,
        "snapshot_estoque": snapshot_estoque, "relacionados_incompativeis": relacionados,
        "eventos_reconciliacao": len(reconciliacoes), "eventos_rollback": len(rollbacks),
        "documento": {nome: registro.get(nome) for nome in (
            "status", "decisao", "decidido_por", "perfil_decisao", "decidido_em",
            "justificativa_destinacao", "atualizado_em",
        )},
    }


def diagnosticar():
    conn = conectar()
    try:
        return _diagnosticar_cursor(conn.cursor())
    finally:
        conn.close()


def reconciliar(*, confirmar=False, usuario="Reconciliação P1.1.1", perfil="admin"):
    if not confirmar:
        return {**diagnosticar(), "modo": "SIMULACAO", "alterado": False}
    with transaction() as conn:
        cursor = conn.cursor()
        diagnostico = _diagnosticar_cursor(cursor, bloquear=True)
        if diagnostico.get("ja_aplicada") and diagnostico.get("apto"):
            return {**diagnostico, "modo": "EXECUCAO", "alterado": False}
        if not diagnostico["apto"]:
            raise RuntimeError("Reconciliação abortada: " + "; ".join(diagnostico["erros"]))
        cursor.execute(q("SELECT * FROM pa_nao_conforme_solicitacoes WHERE id=?"),
                       (diagnostico["solicitacao_aprovada_id"],))
        solicitacao = dict(cursor.fetchone())
        agora = _agora()
        documento_antes = diagnostico["documento"]
        cursor.execute(q("""UPDATE pa_nao_conformes SET status='LIBERADO',decisao='LIBERAR',
            decidido_por=?,perfil_decisao=?,decidido_em=?,justificativa_destinacao=?,atualizado_em=?
            WHERE id=? AND status='BLOQUEADO'"""), (
                solicitacao["decidido_por"], solicitacao["perfil_decisor"],
                solicitacao["decidido_em"], solicitacao["justificativa_decisao"], agora,
                diagnostico["registro_id"],
            ))
        if cursor.rowcount != 1:
            raise RuntimeError("Reconciliação abortada por alteração concorrente do estado documental.")
        detalhes = {
            "versao": "P1.1.1", "alvo": NUMERO_ALVO,
            "solicitacao_aprovada_id": diagnostico["solicitacao_aprovada_id"],
            "evento_aprovacao_id": diagnostico["evento_aprovacao_id"],
            "documento_antes": documento_antes,
            "documento_depois": {"status": "LIBERADO", "decisao": "LIBERAR",
                                  "decidido_em": str(solicitacao["decidido_em"])},
            "snapshot_estoque": diagnostico["snapshot_estoque"],
            "estoque_movimentado_novamente": False,
        }
        cursor.execute(q("""INSERT INTO pa_nao_conforme_eventos (
            pa_nao_conforme_id,acao,status_anterior,status_novo,usuario,perfil,
            justificativa,detalhes,origem,criado_em
        ) VALUES (?,?,?,?,?,?,?,?,?,?)"""), (
            diagnostico["registro_id"], ACAO_RECONCILIACAO, "BLOQUEADO", "LIBERADO",
            usuario, perfil, "Reconciliação controlada do estado legado após liberação integral já efetivada.",
            json.dumps(detalhes, ensure_ascii=False, sort_keys=True, default=str), ORIGEM, agora,
        ))
        return {**diagnostico, "modo": "EXECUCAO", "alterado": True,
                "status_anterior": "BLOQUEADO", "status_novo": "LIBERADO"}


def reverter(*, confirmar=False, usuario="Rollback P1.1.1", perfil="admin"):
    if not confirmar:
        return {**diagnosticar(), "modo": "SIMULACAO_ROLLBACK", "alterado": False}
    with transaction() as conn:
        cursor = conn.cursor()
        sufixo = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE numero=?" + sufixo), (NUMERO_ALVO,))
        registro = cursor.fetchone()
        if not registro:
            raise RuntimeError("Rollback abortado: registro alvo inexistente.")
        registro = dict(registro)
        eventos = _eventos(cursor, registro["id"])
        evento = next((item for item in eventos if item["acao"] == ACAO_RECONCILIACAO), None)
        rollback = next((item for item in eventos if item["acao"] == ACAO_ROLLBACK), None)
        if rollback and registro["status"] == "BLOQUEADO":
            return {"alvo": NUMERO_ALVO, "modo": "EXECUCAO_ROLLBACK", "alterado": False,
                    "ja_revertida": True}
        if not evento or registro["status"] != "LIBERADO":
            raise RuntimeError("Rollback abortado: reconciliação aplicada não encontrada ou estado divergente.")
        posteriores = [item for item in eventos if item["id"] > evento["id"] and item["acao"] != ACAO_ROLLBACK]
        if posteriores:
            raise RuntimeError("Rollback abortado: há eventos posteriores à reconciliação.")
        detalhes = json.loads(evento["detalhes"])
        estoque_esperado = detalhes["snapshot_estoque"]
        if any(int(registro[nome] or 0) != int(valor) for nome, valor in estoque_esperado.items()):
            raise RuntimeError("Rollback abortado: posição de estoque divergiu após a reconciliação.")
        antes = detalhes["documento_antes"]
        agora = _agora()
        cursor.execute(q("""UPDATE pa_nao_conformes SET status=?,decisao=?,decidido_por=?,
            perfil_decisao=?,decidido_em=?,justificativa_destinacao=?,atualizado_em=?
            WHERE id=? AND status='LIBERADO'"""), (
                antes["status"], antes["decisao"], antes["decidido_por"], antes["perfil_decisao"],
                antes["decidido_em"], antes["justificativa_destinacao"], agora, registro["id"],
            ))
        if cursor.rowcount != 1:
            raise RuntimeError("Rollback abortado por alteração concorrente.")
        cursor.execute(q("""INSERT INTO pa_nao_conforme_eventos (
            pa_nao_conforme_id,acao,status_anterior,status_novo,usuario,perfil,
            justificativa,detalhes,origem,criado_em
        ) VALUES (?,?,?,?,?,?,?,?,?,?)"""), (
            registro["id"], ACAO_ROLLBACK, "LIBERADO", antes["status"], usuario, perfil,
            "Rollback controlado da reconciliação documental P1.1.1.",
            json.dumps({"evento_reconciliacao_id": evento["id"], "snapshot_estoque": estoque_esperado,
                        "estoque_movimentado": False}, sort_keys=True), ORIGEM, agora,
        ))
        return {"alvo": NUMERO_ALVO, "modo": "EXECUCAO_ROLLBACK", "alterado": True,
                "status_anterior": "LIBERADO", "status_novo": antes["status"]}
