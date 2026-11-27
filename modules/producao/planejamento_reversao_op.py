"""Inventário read-only de consequências para a futura reversão de uma OP."""

from hashlib import sha256
import json
from uuid import uuid4

from database import DATABASE_URL, q, transaction
from modules.expedicao.estornos_embalagem import STATUS_INATIVOS
from modules.expedicao.eventos_compensatorios import localizar_origens_compensaveis_cursor
from .ciclos_op import apontamentos_correntes_cursor, ciclo_corrente_cursor, tabela_de_ciclo_existe
from .reversao_expedicao_op import eventos_cmv_item_cursor
from .reversao_pi_op import planejar_compensacoes_pi_cursor


def planejar_reversao_op(op_id, ponto_retorno="INICIO_DO_CICLO"):
    with transaction() as conn:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        else:
            cursor.execute("BEGIN")
        return _snapshot_cursor(cursor, int(op_id), ponto_retorno)


def _snapshot_cursor(cursor, op_id, ponto_retorno):
    if ponto_retorno != "INICIO_DO_CICLO":
        raise ValueError("Ponto de retorno ainda não suportado.")
    dados = _planejar(cursor, op_id)
    ciclo = ciclo_corrente_cursor(cursor, op_id)
    dados["ciclo"] = {"id": ciclo["id"], "numero": ciclo["numero_ciclo"]}
    dados["ponto_retorno"] = ponto_retorno
    impedimentos = []
    try:
        dados["compensacoes_pi"] = planejar_compensacoes_pi_cursor(cursor, op_id)
    except ValueError as erro:
        dados["compensacoes_pi"] = []
        impedimentos.append(str(erro))
    dados["apontamentos"] = apontamentos_correntes_cursor(cursor, op_id)
    cursor.execute(q("""SELECT p.pallet_id,p.caixa_id,p.evento_origem_id
        FROM pallet_caixas_atuais p WHERE EXISTS (
          SELECT 1 FROM pa_caixa_composicao c WHERE c.caixa_id=p.caixa_id AND c.op_id=?
        ) ORDER BY p.pallet_id,p.caixa_id"""), (op_id,))
    dados["pallets"] = [dict(item) for item in cursor.fetchall()]
    documentos = {documento["id"]: documento for documento in dados["documentos"]}
    dados["cmv"] = []
    existe_cmv = tabela_de_ciclo_existe(cursor, "cmv_eventos")
    dados["camadas_cmv"] = []
    if existe_cmv:
        cursor.execute(q("""SELECT id,produto,unidade,quantidade_disponivel
            FROM cmv_camadas WHERE op_id=? AND status IN ('ATIVA','ESGOTADA') ORDER BY id"""), (op_id,))
        dados["camadas_cmv"] = [dict(camada) for camada in cursor.fetchall()]
    caixas_ativas = {caixa["id"]: caixa for caixa in dados["caixas"]
                     if caixa["consequencia"] != "PRESERVAR_HISTORICO"}
    impedimentos.extend(
        f"Caixa #{caixa['id']}: {caixa['consequencia']}"
        for caixa in dados["caixas"] if caixa["consequencia"].startswith("RECONCILIAR")
    )
    for item in dados["itens_documentos"]:
        if item["ativo"]:
            documento = documentos[item["expedicao_id"]]
            if item["pertence_op"] and (documento["status"] != "Concluído" or documento["tipo_movimentacao"] not in {
                "TRANSFERENCIA", "VENDA_DIRETA",
            }):
                impedimentos.append(f"Item #{item['id']}: documento {documento['status']} requer regularização.")
            elif item["pertence_op"] and item["caixa_id"] in caixas_ativas:
                caixa = caixas_ativas[item["caixa_id"]]
                try:
                    origens = localizar_origens_compensaveis_cursor(
                        cursor, acao="ESTORNO_ROMANEIO", caixa_id=item["caixa_id"], expedicao_id=documento["id"],
                        quantidade=item["quantidade_pacotes"] or caixa["quantidade_bandejas"] or 1,
                        expedicao_item_id=item["id"],
                    )
                    item["origens_fisicas"] = [{"id": origem["id"], "quantidade": str(quantidade)}
                                                for origem, quantidade in origens]
                except ValueError as erro:
                    impedimentos.append(f"Item #{item['id']}, romaneio #{documento['id']}: {erro}")
            if not existe_cmv or documento["tipo_movimentacao"] != "VENDA_DIRETA":
                continue
            for evento in eventos_cmv_item_cursor(cursor, item["id"], documento["numero_romaneio"] or documento["id"]):
                atribuido = evento["origem_tipo"] == "EXPEDICAO_ITEM"
                if not atribuido and item["pertence_op"]:
                    impedimentos.append(f"CMV #{evento['id']}: falta vínculo ao item #{item['id']} do documento #{documento['id']}.")
                elif atribuido and item["pertence_op"]:
                    cursor.execute(q("""SELECT ca.id,ca.op_id FROM cmv_consumos co
                        JOIN cmv_camadas ca ON ca.id=co.camada_id
                        WHERE co.evento_id=? AND ca.op_id<>? ORDER BY ca.id"""), (evento["id"], op_id))
                    for consumo in cursor.fetchall():
                        impedimentos.append(f"CMV #{evento['id']}: item #{item['id']} consumiu a camada "
                                            f"#{consumo['id']} da OP #{consumo['op_id']}.")
                if atribuido or item["pertence_op"]:
                    dados["cmv"].append({**evento, "item_id": item["id"],
                        "consequencia": ("Compensar valor histórico" if item["pertence_op"] else
                                         "Preservar parcela de outra OP") if atribuido else "Conciliar origem"})
    dados["impedimentos"] = impedimentos
    dados["executavel"] = not impedimentos
    return dados


def registrar_previa_reprocessamento(op_id, *, perfil, usuario, ponto_retorno="INICIO_DO_CICLO"):
    if perfil != "admin" or not str(usuario or "").strip():
        raise PermissionError("Somente um administrador identificado pode registrar uma prévia.")
    with transaction() as conn:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        else:
            cursor.execute("BEGIN IMMEDIATE")
        snapshot = _snapshot_cursor(cursor, int(op_id), ponto_retorno)
        serializado, resumo = _serializar_snapshot(snapshot)
        plano_id = str(uuid4())
        cursor.execute(q("""INSERT INTO op_planos_reprocessamento (
            id,ciclo_id,versao_operacional,hash_consequencias,snapshot_json,criado_por
        ) VALUES (?,?,?,?,?,?)"""), (
            plano_id, snapshot["ciclo"]["id"], snapshot["op"]["versao_operacional"] or 0,
            resumo, serializado, usuario,
        ))
    return {"plano_id": plano_id, "hash_consequencias": resumo, "snapshot": snapshot}


def hash_previa_reprocessamento(snapshot):
    return _serializar_snapshot(snapshot)[1]


def _serializar_snapshot(snapshot):
    serializado = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
    return serializado, sha256(serializado.encode("utf-8")).hexdigest()


def revalidar_previa_cursor(cursor, op_id, plano_id):
    """Compara a prévia com as consequências atuais após o lock da OP."""
    cursor.execute(q("""SELECT p.hash_consequencias,p.snapshot_json,p.ciclo_id
        FROM op_planos_reprocessamento p JOIN op_ciclos c ON c.id=p.ciclo_id
        WHERE p.id=? AND c.op_id=?"""), (plano_id, op_id))
    plano = cursor.fetchone()
    if not plano:
        raise ValueError("Prévia de reprocessamento não encontrada para esta OP.")
    ciclo = ciclo_corrente_cursor(cursor, op_id, bloquear=True)
    if ciclo["id"] != plano["ciclo_id"]:
        raise ValueError("O ciclo corrente mudou desde a análise.")
    anterior = json.loads(plano["snapshot_json"])
    atual = _snapshot_cursor(cursor, op_id, anterior["ponto_retorno"])
    serializado, resumo = _serializar_snapshot(atual)
    if resumo != plano["hash_consequencias"] or serializado != plano["snapshot_json"]:
        raise ValueError("As consequências desta OP mudaram desde a análise. Revise o plano atualizado.")
    return atual


def _planejar(cursor, op_id):
    cursor.execute(q("SELECT id,status,versao_operacional FROM ordens_producao WHERE id=?"), (op_id,))
    op = cursor.fetchone()
    if not op:
        raise ValueError("OP não encontrada.")
    cursor.execute(q("""
        SELECT cx.id,cx.codigo_caixa,cx.status,cx.peso_liquido,cx.estoque_operacional,
               (SELECT SUM(c.quantidade_bandejas) FROM pa_caixa_composicao c
                WHERE c.caixa_id=cx.id AND c.op_id=?) AS quantidade_bandejas,
               (SELECT COUNT(*) FROM pa_caixa_composicao outra
                WHERE outra.caixa_id=cx.id AND outra.op_id<>?) AS outras_composicoes,
               (SELECT COUNT(*) FROM estoque_eventos ev
                WHERE ev.caixa_id=cx.id AND ev.acao='FORMACAO_ESTOQUE'
                AND NOT EXISTS (SELECT 1 FROM estoque_eventos comp
                                WHERE comp.evento_origem_id=ev.id)) AS formacoes
        FROM pa_caixas cx WHERE EXISTS (
            SELECT 1 FROM pa_caixa_composicao c WHERE c.caixa_id=cx.id AND c.op_id=?
        ) ORDER BY cx.id
    """), (op_id, op_id, op_id))
    caixas = [dict(item) for item in cursor.fetchall()]
    for caixa in caixas:
        if str(caixa["status"] or "").upper() in STATUS_INATIVOS:
            caixa["consequencia"] = "PRESERVAR_HISTORICO"
        elif caixa["outras_composicoes"] or caixa["formacoes"] > 1:
            caixa["consequencia"] = "RECONCILIAR_COMPOSICAO_OU_FORMACAO"
        elif caixa["formacoes"]:
            caixa["consequencia"] = "COMPENSAR_FORMACAO"
        elif caixa["estoque_operacional"]:
            caixa["consequencia"] = "RECONCILIAR_PA_ATIVO_SEM_FORMACAO"
        else:
            caixa["consequencia"] = "INVALIDAR_CAIXA_SEM_COMPENSAR_PA"

    cursor.execute(q("""
        SELECT e.id,e.numero_romaneio,e.status,e.tipo_movimentacao,
               SUM(CASE WHEN COALESCE(i.ativo,1)=1 THEN 1 ELSE 0 END) AS itens_ativos_op,
               (SELECT COUNT(*) FROM expedicao_itens j WHERE j.expedicao_id=e.id
                  AND COALESCE(j.ativo,1)=1 AND NOT EXISTS (
                  SELECT 1 FROM pa_caixa_composicao c2 WHERE c2.caixa_id=j.caixa_id AND c2.op_id=?
               )) AS itens_ativos_fora_op
        FROM expedicoes e JOIN expedicao_itens i ON i.expedicao_id=e.id
        WHERE EXISTS (SELECT 1 FROM pa_caixa_composicao c
                      WHERE c.caixa_id=i.caixa_id AND c.op_id=?)
        GROUP BY e.id,e.numero_romaneio,e.status,e.tipo_movimentacao ORDER BY e.id
    """), (op_id, op_id))
    documentos = [dict(item) for item in cursor.fetchall()]
    for doc in documentos:
        if not doc["itens_ativos_op"]:
            doc["consequencia"] = "PRESERVAR_HISTORICO"
        elif doc["status"] == "Concluído" and doc["tipo_movimentacao"] != "HISTORICO_MARCO_ZERO":
            doc["consequencia"] = "REVERTER_SOMENTE_ITENS_DA_OP"
        elif doc["status"] == "Aberto":
            doc["consequencia"] = "REVISAR_CANCELAMENTO_OU_LIBERACAO_DE_RESERVA"
        else:
            doc["consequencia"] = "SEM_REVERSAO_DOCUMENTAL_SUPORTADA"

    cursor.execute(q("""
        SELECT i.id,i.expedicao_id,i.caixa_id,COALESCE(i.ativo,1) AS ativo,
               i.quantidade_pacotes,i.quantidade_kg,
               CASE WHEN EXISTS (
                SELECT 1 FROM pa_caixa_composicao c WHERE c.caixa_id=i.caixa_id AND c.op_id=?
               ) THEN 1 ELSE 0 END AS pertence_op
        FROM expedicao_itens i WHERE EXISTS (
            SELECT 1 FROM expedicao_itens alvo JOIN pa_caixa_composicao c ON c.caixa_id=alvo.caixa_id
            WHERE alvo.expedicao_id=i.expedicao_id AND c.op_id=?
        ) ORDER BY i.expedicao_id,i.id
    """), (op_id, op_id))
    itens = [dict(item) for item in cursor.fetchall()]
    cursor.execute(q("""SELECT tipo,COUNT(*) AS movimentos,SUM(quantidade_bandejas) AS bandejas
        FROM estoque_produto_intermediario WHERE op_id=? GROUP BY tipo ORDER BY tipo"""), (op_id,))
    return {
        "op": dict(op), "pi": [dict(item) for item in cursor.fetchall()],
        "caixas": caixas, "documentos": documentos, "itens_documentos": itens,
        "executavel": False,
    }
