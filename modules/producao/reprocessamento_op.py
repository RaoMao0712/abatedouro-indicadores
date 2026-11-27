"""Orquestra compensações e troca de ciclo na mesma transação."""

from collections import defaultdict

from database import DATABASE_URL, q, transaction
from modules.cmv.services import invalidar_camadas_op_cursor
from modules.expedicao.palletizacao import remover_caixas
from .ciclos_op import invalidar_apontamentos_cursor, substituir_ciclo_cursor
from .operacoes_op import _agora, _auditar, _resultado_idempotente
from .performance import invalidar_por_reabertura
from .planejamento_reversao_op import revalidar_previa_cursor
from .reversao_expedicao_op import reverter_item_expedicao_cursor
from .reversao_pa_op import reverter_caixa_cursor
from .reversao_pi_op import compensar_pi_cursor


TIPO_REPROCESSAMENTO = "OP_NOVO_CICLO_REPROCESSAMENTO"


def executar_reprocessamento_op(op_id, plano_id, *, usuario, perfil, motivo,
                                confirmacao, ip_origem=None, checkpoint=None):
    if perfil != "admin" or not str(usuario or "").strip():
        raise PermissionError("Somente administradores podem reprocessar uma OP.")
    if not confirmacao or not str(motivo or "").strip() or not plano_id:
        raise ValueError("Prévia, motivo e confirmação são obrigatórios.")
    for tentativa in range(3):
        try:
            return _executar(op_id, plano_id, usuario, perfil, motivo, ip_origem, checkpoint)
        except Exception as erro:
            if getattr(erro, "pgcode", None) not in {"40001", "40P01"}:
                raise
            if tentativa == 2:
                raise ValueError("A OP está ocupada. Tente confirmar a prévia novamente.") from erro


def _executar(op_id, plano_id, usuario, perfil, motivo, ip_origem, checkpoint):
    chave = f"REPROCESSAMENTO-{op_id}-{plano_id}"
    with transaction() as conn:
        cursor = conn.cursor()
        if DATABASE_URL:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        else:
            cursor.execute("BEGIN IMMEDIATE")
        lock = " FOR UPDATE" if DATABASE_URL else ""
        cursor.execute(q("SELECT status,versao_operacional FROM ordens_producao WHERE id=?" + lock), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        anterior = _resultado_idempotente(cursor, chave)
        if anterior:
            return anterior
        previa = revalidar_previa_cursor(cursor, op_id, plano_id)
        if not previa["executavel"]:
            raise ValueError(" ".join(previa["impedimentos"]))
        ciclo_id = previa["ciclo"]["id"]
        agora = _agora()
        caixas = [caixa for caixa in previa["caixas"] if caixa["consequencia"] != "PRESERVAR_HISTORICO"]
        if not caixas and not previa["compensacoes_pi"] and not any(previa["apontamentos"].values()):
            raise ValueError("A OP não possui efeitos para reprocessar neste ciclo.")
        if any(caixa["consequencia"].startswith("RECONCILIAR") for caixa in caixas):
            raise ValueError("A prévia contém caixas cuja composição ou formação exige conciliação.")
        ids_caixas = {caixa["id"] for caixa in caixas}
        documentos = defaultdict(set)
        expedicao = []
        for item in reversed(previa["itens_documentos"]):
            if not item["pertence_op"] or item["caixa_id"] not in ids_caixas:
                continue
            if item["ativo"]:
                expedicao.append(reverter_item_expedicao_cursor(
                    cursor, op_id, item["id"], operacao_id=chave, usuario=usuario,
                    motivo=motivo, agora=agora, checkpoint=checkpoint,
                ))
            documentos[item["caixa_id"]].add(item["expedicao_id"])
        camadas = invalidar_camadas_op_cursor(cursor, op_id, usuario=usuario, motivo=motivo) if previa["camadas_cmv"] else []
        if checkpoint:
            checkpoint("apos_expedicao")
        pallets = defaultdict(list)
        for vinculo in previa["pallets"]:
            if vinculo["caixa_id"] in ids_caixas:
                pallets[vinculo["pallet_id"]].append(vinculo["caixa_id"])
        for pallet_id, caixa_ids in pallets.items():
            pallet = remover_caixas(
                pallet_id, caixa_ids, usuario=usuario, justificativa=motivo,
                idempotency_key=f"{chave}:PALLET:{pallet_id}", conn_existente=conn,
            )
            if not pallet["caixas"]:
                cursor.execute(q("""UPDATE pallets SET status='DISPONIVEL',versao=versao+1
                    WHERE id=? AND status IN ('CARREGADO','PARCIALMENTE_CARREGADO')"""), (pallet_id,))
        pa = [reverter_caixa_cursor(
            cursor, op_id, caixa["id"], operacao_id=chave, usuario=usuario,
            perfil=perfil, motivo=motivo, agora=agora,
            documentos_revertidos=documentos[caixa["id"]], checkpoint=checkpoint,
        ) for caixa in caixas]
        if checkpoint:
            checkpoint("apos_caixas")
        compensar_pi_cursor(
            cursor, op_id, plano=previa["compensacoes_pi"], operacao_id=chave, agora=agora,
        )
        if checkpoint:
            checkpoint("apos_pi")
        invalidar_apontamentos_cursor(cursor, ciclo_id, previa["apontamentos"])
        cursor.execute(q("""UPDATE embalagem_secundaria_conferencias SET confirmada=0
            WHERE op_id=? AND confirmada=1"""), (op_id,))
        invalidar_por_reabertura(op_id, cursor=cursor, usuario=usuario, perfil=perfil, justificativa=motivo)
        novo = substituir_ciclo_cursor(
            cursor, op_id, ciclo_id=ciclo_id, operacao_id=chave, usuario=usuario,
            motivo=motivo, agora=agora, checkpoint=checkpoint,
        )
        versao = int(op["versao_operacional"] or 0)
        cursor.execute(q("""UPDATE ordens_producao SET status='Aberta',versao_operacional=?
            WHERE id=? AND COALESCE(versao_operacional,0)=?"""), (versao + 1, op_id, versao))
        if cursor.rowcount != 1:
            raise ValueError("A OP mudou desde a análise.")
        cursor.execute(q("SELECT hash_consequencias FROM op_planos_reprocessamento WHERE id=?"), (plano_id,))
        hash_plano = cursor.fetchone()["hash_consequencias"]
        efeitos = {"expedicao": expedicao, "pa": pa, "pi": previa["compensacoes_pi"], "camadas_cmv": camadas,
                   "pallets": [{"pallet_id": pallet_id, "caixa_ids": ids} for pallet_id, ids in pallets.items()],
                   "apontamentos": previa["apontamentos"]}
        resultado = {"tipo": TIPO_REPROCESSAMENTO, "op_id": op_id, "plano_id": plano_id,
                     "hash_plano": hash_plano, "ciclo_anterior": previa["ciclo"]["numero"],
                     "ciclo_atual": novo["numero_ciclo"], "versao_anterior": versao,
                     "versao_atual": versao + 1, "efeitos": efeitos}
        _auditar(cursor, op_id=op_id, tipo=TIPO_REPROCESSAMENTO, chave=chave,
                 usuario=usuario, perfil=perfil, motivo=motivo, etapa="EMBALAGEM_PRIMARIA",
                 status_anterior=op["status"], status_posterior="Aberta", preflight=previa,
                 efeitos=efeitos, resultado=resultado, ip_origem=ip_origem)
        return resultado
