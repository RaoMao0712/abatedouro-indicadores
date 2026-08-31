"""Reconciliação transacional e idempotente de PA pendente no Marco Zero."""

from argparse import ArgumentParser
from datetime import datetime
from decimal import Decimal
import json
import os

from database import DATABASE_URL, conectar, q, transaction
from modules.producao.services import gerar_producao_automatica_setores
from modules.producao.operacoes_op import criar_tabelas_operacoes_op
from .services import criar_tabelas_estoque_pi_pa
from .estoque_service import (
    CICLO_OPERACIONAL,
    CICLO_TRANSICAO,
    ativar_estoque_op_encerrada,
    classificar_ciclo_operacional_op,
    criar_tabelas_estoque_confiavel,
)


ACAO_RECONCILIACAO = "OP_CICLO_MARCO_ZERO_RECONCILIADA"
CHAVE_PADRAO = "HOTFIX-MZ-OP-71-V1"
CONFIRMACAO_OP_71 = "RECONCILIAR-OP-71"
STATUS_INATIVOS = {"ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO"}


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _decimal(valor):
    return Decimal(str(valor or 0))


def _dict(linha):
    return dict(linha) if linha else None


def _bloqueio_sql():
    return " FOR UPDATE" if DATABASE_URL else ""


def _preflight_cursor(cursor, op_id, *, bloquear=False):
    cursor.execute(q("SELECT * FROM estoque_marcos WHERE tipo='MARCO_ZERO' LIMIT 1"))
    marco = cursor.fetchone()
    cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + (_bloqueio_sql() if bloquear else "")), (op_id,))
    op = cursor.fetchone()
    if not op:
        raise ValueError("OP não encontrada.")
    if not marco:
        raise ValueError("Marco Zero não encontrado.")

    cursor.execute(q("""
    SELECT * FROM embalagem_primaria_apontamentos
    WHERE op_id=? ORDER BY id
    """), (op_id,))
    primaria = cursor.fetchall()
    bandejas_primaria = sum((_decimal(item["quantidade_bandejas"]) for item in primaria), Decimal("0"))

    sql_caixas = """
    SELECT cx.*, comp.quantidade_bandejas AS composicao_bandejas,
           (SELECT COUNT(DISTINCT c2.op_id) FROM pa_caixa_composicao c2
            WHERE c2.caixa_id=cx.id) AS total_ops
    FROM pa_caixas cx
    INNER JOIN pa_caixa_composicao comp ON comp.caixa_id=cx.id
    WHERE comp.op_id=?
    ORDER BY cx.codigo_caixa, cx.id
    """
    if bloquear:
        sql_caixas += _bloqueio_sql()
    cursor.execute(q(sql_caixas), (op_id,))
    caixas = cursor.fetchall()
    caixas_ativas = [item for item in caixas if str(item["status"] or "").upper() not in STATUS_INATIVOS]
    bandejas_caixas = sum((_decimal(item["composicao_bandejas"]) for item in caixas_ativas), Decimal("0"))
    peso_liquido = sum((_decimal(item["peso_liquido"]) for item in caixas_ativas), Decimal("0"))
    peso_bruto = sum((_decimal(item["peso_bruto"]) for item in caixas_ativas), Decimal("0"))

    if bloquear and DATABASE_URL:
        cursor.execute(q("SELECT id FROM estoque_produto_intermediario WHERE op_id=? ORDER BY id FOR UPDATE"), (op_id,))
        cursor.fetchall()
    cursor.execute(q("SELECT * FROM estoque_produto_intermediario WHERE op_id=? ORDER BY id"), (op_id,))
    movimentos_pi = cursor.fetchall()
    entradas_pi = sum((_decimal(item["quantidade_bandejas"]) for item in movimentos_pi
                       if str(item["tipo"] or "").startswith("ENTRADA")), Decimal("0"))
    saidas_pi = sum((_decimal(item["quantidade_bandejas"]) for item in movimentos_pi
                     if str(item["tipo"] or "").startswith("SAIDA")), Decimal("0"))
    saldo_pi = entradas_pi - saidas_pi

    ids_caixas = [int(item["id"]) for item in caixas_ativas]
    vinculos = {"estoque_eventos": 0, "pa_movimentacoes": 0, "expedicao_itens": 0}
    if ids_caixas:
        marcadores = ",".join(["?"] * len(ids_caixas))
        for tabela in vinculos:
            cursor.execute(q(f"SELECT COUNT(*) AS total FROM {tabela} WHERE caixa_id IN ({marcadores})"), tuple(ids_caixas))
            vinculos[tabela] = int(cursor.fetchone()["total"] or 0)

    cursor.execute(q("""
    SELECT
      COALESCE(SUM(CASE WHEN LOWER(COALESCE(categoria,'')) LIKE '%%conden%%'
                        THEN quantidade ELSE 0 END),0) AS condenacoes,
      COALESCE(SUM(CASE WHEN LOWER(COALESCE(categoria,'')) NOT LIKE '%%conden%%'
                         AND LOWER(TRIM(COALESCE(motivo,''))) <> 'morte na gaiola'
                        THEN quantidade ELSE 0 END),0) AS descartes,
      COALESCE(SUM(CASE WHEN LOWER(TRIM(COALESCE(motivo,''))) = 'morte na gaiola'
                        THEN quantidade ELSE 0 END),0) AS mortes_na_gaiola
    FROM apontamentos_descartes
    WHERE op_id=? AND LOWER(unidade) IN ('aves','ave','unidade','unidades')
    """), (op_id,))
    perdas = cursor.fetchone()
    total_fechamento = (
        bandejas_primaria + _decimal(perdas["condenacoes"]) + _decimal(perdas["descartes"])
        + _decimal(perdas["mortes_na_gaiola"]) + _decimal(op["mortes_antes_pendura"])
    )

    ciclo = classificar_ciclo_operacional_op(cursor, op, marco)
    codigos = [item["codigo_caixa"] for item in caixas_ativas]
    itens_caixas = [
        {
            "id": int(item["id"]),
            "codigo": item["codigo_caixa"],
            "bandejas": str(_decimal(item["composicao_bandejas"])),
            "peso_liquido": str(_decimal(item["peso_liquido"])),
            "peso_bruto": str(_decimal(item["peso_bruto"])),
            "fabricacao": item["data_fabricacao"],
            "validade": item["data_validade"],
            "disponibilidade": item["disponibilidade"],
            "estoque_operacional": int(item["estoque_operacional"] or 0),
        }
        for item in caixas_ativas
    ]
    chaves_pi = [item["idempotency_key"] for item in movimentos_pi if item["idempotency_key"]]
    bloqueios = []
    if int(op_id) != 71:
        bloqueios.append("O hotfix produtivo é restrito à OP #71.")
    if ciclo not in {CICLO_OPERACIONAL, CICLO_TRANSICAO}:
        bloqueios.append(f"Ciclo {ciclo} não pode ser promovido automaticamente.")
    if not primaria or bandejas_primaria <= 0:
        bloqueios.append("Apontamento original da Embalagem Primária não encontrado.")
    if len(codigos) != len(set(codigos)):
        bloqueios.append("Foram encontrados códigos de caixa duplicados.")
    if any(int(item["total_ops"] or 0) != 1 for item in caixas_ativas):
        bloqueios.append("Há caixa com composição mista ou origem não exclusiva da OP #71.")
    if bandejas_caixas > bandejas_primaria:
        bloqueios.append(
            f"Caixas excedem o PI: {bandejas_caixas} para {bandejas_primaria} bandejas apontadas."
        )
    saldo_esperado = bandejas_primaria - bandejas_caixas
    if entradas_pi != bandejas_primaria or saidas_pi != bandejas_caixas or saldo_pi != saldo_esperado:
        bloqueios.append(
            f"PI divergente: entradas={entradas_pi}, saídas={saidas_pi}, saldo={saldo_pi}, esperado={saldo_esperado}."
        )
    if len(chaves_pi) != len(set(chaves_pi)):
        bloqueios.append("Há chave idempotente duplicada nos movimentos de PI.")
    reservadas = [item["codigo_caixa"] for item in caixas_ativas if
                  item["reservado_expedicao_id"] or _decimal(item["quantidade_pacotes_reservados"]) > 0]
    if reservadas:
        bloqueios.append("Há caixa reservada: " + ", ".join(reservadas))
    if vinculos["pa_movimentacoes"] or vinculos["expedicao_itens"]:
        bloqueios.append("Há movimentação, romaneio ou expedição posterior vinculada às caixas.")
    operacionais = [item for item in caixas_ativas if int(item["estoque_operacional"] or 0) == 1]
    if operacionais and len(operacionais) != len(caixas_ativas):
        bloqueios.append("A formação operacional está parcial; reconciliação automática bloqueada.")
    if vinculos["estoque_eventos"] and not operacionais:
        bloqueios.append("Já existem eventos de estoque sem a correspondente formação operacional.")
    if total_fechamento != _decimal(op["quantidade_aves"]):
        bloqueios.append(
            f"Balanço industrial divergente: fechamento={total_fechamento}, aves={_decimal(op['quantidade_aves'])}."
        )
    if str(op["status"] or "") not in {"Aberta", "Aguardando Embalagem Secundária", "Encerrada"}:
        bloqueios.append(f"Situação da OP incompatível: {op['status']}.")

    caminho = "A_RECONCILIAR_PA_EXISTENTE" if caixas_ativas and saldo_pi == 0 else "B_SALDO_REAL_PARA_PESAGEM"
    return {
        "op": {"id": int(op["id"]), "data": op["data"], "sku": op["sku"], "status": op["status"],
               "estoque_classificacao": op["estoque_classificacao"], "ciclo": ciclo},
        "marco_zero": _dict(marco),
        "caminho": caminho,
        "permitido": not bloqueios,
        "bloqueios": bloqueios,
        "primaria": {"apontamentos": len(primaria), "bandejas": str(bandejas_primaria)},
        "pi": {"movimentos": len(movimentos_pi), "entradas": str(entradas_pi),
               "saidas": str(saidas_pi), "saldo": str(saldo_pi)},
        "caixas": {"total": len(caixas_ativas), "ids": ids_caixas, "codigos": codigos,
                   "itens": itens_caixas, "bandejas": str(bandejas_caixas),
                   "peso_liquido": str(peso_liquido), "peso_bruto": str(peso_bruto),
                   "padrao_12": sum(1 for item in caixas_ativas if _decimal(item["composicao_bandejas"]) == 12),
                   "parciais": sum(1 for item in caixas_ativas if _decimal(item["composicao_bandejas"]) != 12),
                   "operacionais": len(operacionais), "reservadas": len(reservadas)},
        "balanco": {"aves": str(_decimal(op["quantidade_aves"])), "fechamento": str(total_fechamento)},
        "vinculos": vinculos,
    }


def preflight_reconciliacao_op(op_id=71):
    """Inspeção estritamente read-only; não cria schema nem grava auditoria."""
    conn = conectar()
    try:
        return _preflight_cursor(conn.cursor(), int(op_id))
    finally:
        conn.close()


def reconciliar_op_71(*, usuario, perfil="admin", commit=None,
                      idempotency_key=CHAVE_PADRAO, confirmacao=None,
                      checkpoint=None):
    if confirmacao != CONFIRMACAO_OP_71:
        raise ValueError(f"Confirmação explícita obrigatória: {CONFIRMACAO_OP_71}.")
    if not str(usuario or "").strip():
        raise ValueError("Executor da reconciliação não identificado.")
    if not str(idempotency_key or "").strip():
        raise ValueError("Chave de idempotência obrigatória.")

    criar_tabelas_estoque_pi_pa()
    criar_tabelas_estoque_confiavel()
    criar_tabelas_operacoes_op()
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT resultado_json FROM op_operacoes_auditoria WHERE idempotency_key=?"),
                       (idempotency_key,))
        existente = cursor.fetchone()
        if existente:
            return json.loads(existente["resultado_json"])

        preflight = _preflight_cursor(cursor, 71, bloquear=True)
        if not preflight["permitido"]:
            raise ValueError("Reconciliação bloqueada: " + " ".join(preflight["bloqueios"]))
        if preflight["caminho"] != "A_RECONCILIAR_PA_EXISTENTE":
            raise ValueError("O caminho B mantém somente o saldo real disponível e não promove caixas automaticamente.")

        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=71"))
        op = cursor.fetchone()
        status_anterior = op["status"]
        if status_anterior != "Encerrada":
            gerar_producao_automatica_setores(
                op=op, data_lancamento=op["data"], hora_inicio="N/A", hora_fim="N/A",
                unidades_produzidas=preflight["caixas"]["bandejas"],
                kg_produzidos=preflight["caixas"]["peso_liquido"],
                descontar_almoco=False, conn=conn,
            )
            cursor.execute(q("""
            UPDATE ordens_producao SET status='Encerrada'
            WHERE id=71 AND status=?
            """), (status_anterior,))
            if cursor.rowcount != 1:
                raise ValueError("A OP #71 foi alterada concorrentemente; transação cancelada.")
        if checkpoint:
            checkpoint("antes_formacao_estoque")
        ativar_estoque_op_encerrada(cursor, 71)
        if checkpoint:
            checkpoint("depois_formacao_estoque")

        agora = _agora()
        justificativa = (
            "Reconciliação auditável do PA já formado da OP #71; caixas, pesos, fabricação, "
            "validade e movimentos de PI preservados."
        )
        for caixa in preflight["caixas"]["itens"]:
            caixa_id = caixa["id"]
            codigo = caixa["codigo"]
            cursor.execute(q("""
            INSERT INTO estoque_eventos(
                caixa_id,acao,situacao_anterior,situacao_nova,condicao_anterior,condicao_nova,
                quantidade,peso,justificativa,observacao,usuario,perfil,criado_em,idempotency_key
            )
            SELECT id,?,?,?,?,?,quantidade_bandejas,peso_liquido,?,?,?,?,?,?
            FROM pa_caixas WHERE id=?
            """), (
                ACAO_RECONCILIACAO, "PENDENTE_OP", "DISPONIVEL", "CONFORME", "CONFORME",
                justificativa,
                json.dumps({"op_id": 71, "codigo_caixa": codigo, "commit": commit}, ensure_ascii=False),
                usuario, perfil, agora, f"{idempotency_key}:CAIXA:{caixa_id}", caixa_id,
            ))

        resultado = {
            "sucesso": True, "op_id": 71, "acao": ACAO_RECONCILIACAO,
            "status_anterior": status_anterior, "status_posterior": "Encerrada",
            "ciclo": preflight["op"]["ciclo"], "commit": commit,
            "caixas_reaproveitadas": preflight["caixas"]["total"],
            "caixas_criadas": 0, "pi_criado": 0, "pi_consumido_novamente": 0,
            "movimentos_formacao_criados": preflight["caixas"]["total"],
            "eventos_reconciliacao_criados": preflight["caixas"]["total"],
            "bandejas": preflight["caixas"]["bandejas"],
            "peso_liquido": preflight["caixas"]["peso_liquido"],
        }
        cursor.execute(q("""
        INSERT INTO op_operacoes_auditoria(
            op_id,tipo,idempotency_key,usuario,perfil,motivo,etapa_destino,
            status_anterior,status_posterior,preflight_json,efeitos_json,
            resultado_json,ip_origem,criado_em
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """), (
            71, ACAO_RECONCILIACAO, idempotency_key, usuario, perfil, justificativa,
            "ESTOQUE_PA", status_anterior, "Encerrada",
            json.dumps(preflight, ensure_ascii=False, default=str),
            json.dumps({"movimentos_estoque_formacao_criados": preflight["caixas"]["total"],
                        "eventos_reconciliacao_criados": preflight["caixas"]["total"],
                        "caixas_reaproveitadas": preflight["caixas"]["total"],
                        "pi_reaproveitado": True, "financeiro_alterado": False}, ensure_ascii=False),
            json.dumps(resultado, ensure_ascii=False), None, agora,
        ))
        return resultado


def main(argv=None):
    parser = ArgumentParser(description="Reconciliação idempotente da OP #71")
    parser.add_argument("--op", type=int, default=71)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--user", default=os.getenv("USER") or "Hotfix P0")
    parser.add_argument("--profile", default="admin")
    parser.add_argument("--commit")
    parser.add_argument("--idempotency-key", default=CHAVE_PADRAO)
    args = parser.parse_args(argv)
    if args.op != 71:
        parser.error("este comando produtivo aceita somente --op 71")
    if not args.execute:
        print(json.dumps(preflight_reconciliacao_op(args.op), ensure_ascii=False, indent=2, default=str))
        return 0
    resultado = reconciliar_op_71(
        usuario=args.user, perfil=args.profile, commit=args.commit,
        idempotency_key=args.idempotency_key, confirmacao=args.confirm,
    )
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
