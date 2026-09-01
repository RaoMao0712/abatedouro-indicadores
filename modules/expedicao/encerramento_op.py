"""Encerramento oficial, transacional, auditável e idempotente de OP."""

from datetime import datetime
from decimal import Decimal
import hashlib
import json
import time
import uuid

from database import DATABASE_URL, conectar, q, transaction
from modules.producao.services import gerar_producao_automatica_setores


TIPO_AUDITORIA = "ENCERRAMENTO_OP"
STATUS_INATIVOS = {"ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO"}


def _valor(linha, campo, padrao=None):
    try:
        return linha[campo]
    except (IndexError, KeyError):
        return padrao


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _tabela_existe(cursor, nome):
    if DATABASE_URL:
        cursor.execute("SELECT to_regclass(%s) AS tabela", (f"public.{nome}",))
    else:
        cursor.execute(
            "SELECT name AS tabela FROM sqlite_master WHERE type='table' AND name=?",
            (nome,),
        )
    linha = cursor.fetchone()
    return bool(linha and linha["tabela"])


def _carregar_op(cursor, op_id, bloquear=False):
    sql = "SELECT * FROM ordens_producao WHERE id=?"
    if bloquear and DATABASE_URL:
        sql += " FOR UPDATE"
    cursor.execute(q(sql), (op_id,))
    op = cursor.fetchone()
    if not op:
        raise ValueError("OP não encontrada.")
    return op


def _carregar_caixas(cursor, op_id, bloquear=False):
    sql = """SELECT cx.* FROM pa_caixas cx
        WHERE EXISTS (
            SELECT 1 FROM pa_caixa_composicao c
            WHERE c.caixa_id=cx.id AND c.op_id=?
        ) ORDER BY cx.id"""
    if bloquear and DATABASE_URL:
        sql += " FOR UPDATE"
    cursor.execute(q(sql), (op_id,))
    return cursor.fetchall()


def _livro_pi(cursor, op_id, bloquear=False):
    if not _tabela_existe(cursor, "estoque_produto_intermediario"):
        return {"entradas": 0, "saidas": 0, "saldo": 0}
    if bloquear and DATABASE_URL:
        cursor.execute(q(
            "SELECT id FROM estoque_produto_intermediario WHERE op_id=? ORDER BY id FOR UPDATE"
        ), (op_id,))
        cursor.fetchall()
    cursor.execute(q("""
        SELECT
          COALESCE(SUM(CASE WHEN tipo LIKE 'ENTRADA%%' THEN quantidade_bandejas ELSE 0 END),0) entradas,
          COALESCE(SUM(CASE WHEN tipo LIKE 'SAIDA%%' THEN quantidade_bandejas ELSE 0 END),0) saidas,
          COALESCE(SUM(CASE WHEN tipo='SAIDA_EMBALAGEM_SECUNDARIA'
                            THEN quantidade_bandejas ELSE 0 END),0)
            - COALESCE(SUM(CASE WHEN tipo='ENTRADA_ESTORNO_CAIXA'
                                THEN quantidade_bandejas ELSE 0 END),0) consumo_liquido,
          COALESCE(SUM(CASE WHEN tipo LIKE 'ENTRADA%%' THEN quantidade_bandejas
                            WHEN tipo LIKE 'SAIDA%%' THEN -quantidade_bandejas
                            ELSE quantidade_bandejas END),0) saldo
        FROM estoque_produto_intermediario WHERE op_id=?
    """), (op_id,))
    return cursor.fetchone()


def _calcular_fechamento_cursor(cursor, op):
    """Calcula as invariantes sem executar bootstrap, DDL ou commit implícito."""
    op_id = int(op["id"])
    cursor.execute(q("""
        SELECT COALESCE(SUM(quantidade_bandejas),0) total
        FROM embalagem_primaria_apontamentos WHERE op_id=?
    """), (op_id,))
    bandejas_primaria = float(cursor.fetchone()["total"] or 0)
    cursor.execute(q("""
        SELECT
          COALESCE(SUM(CASE WHEN LOWER(COALESCE(categoria,'')) LIKE '%%conden%%'
                            THEN quantidade ELSE 0 END),0) condenacoes,
          COALESCE(SUM(CASE WHEN LOWER(COALESCE(categoria,'')) NOT LIKE '%%conden%%'
                             AND LOWER(TRIM(COALESCE(motivo,'')))<>'morte na gaiola'
                            THEN quantidade ELSE 0 END),0) descartes,
          COALESCE(SUM(CASE WHEN LOWER(TRIM(COALESCE(motivo,'')))='morte na gaiola'
                            THEN quantidade ELSE 0 END),0) mortes_na_gaiola
        FROM apontamentos_descartes WHERE op_id=?
          AND LOWER(unidade) IN ('aves','ave','unidade','unidades')
    """), (op_id,))
    perdas = cursor.fetchone()
    condenacoes = float(perdas["condenacoes"] or 0)
    descartes = float(perdas["descartes"] or 0)
    mortes_antes_pendura = (
        float(op["mortes_antes_pendura"] or 0) + float(perdas["mortes_na_gaiola"] or 0)
    )
    cursor.execute(q("""
        SELECT COUNT(DISTINCT cx.id) caixas,
          COALESCE(SUM(comp.quantidade_bandejas),0) bandejas_consumidas,
          COALESCE(SUM(cx.peso_liquido*comp.quantidade_bandejas/
            NULLIF((SELECT SUM(c2.quantidade_bandejas) FROM pa_caixa_composicao c2
                    WHERE c2.caixa_id=comp.caixa_id),0)),0) peso_liquido_total,
          COALESCE(SUM(cx.peso_bruto*comp.quantidade_bandejas/
            NULLIF((SELECT SUM(c2.quantidade_bandejas) FROM pa_caixa_composicao c2
                    WHERE c2.caixa_id=comp.caixa_id),0)),0) peso_bruto_total
        FROM pa_caixa_composicao comp
        JOIN pa_caixas cx ON cx.id=comp.caixa_id
        WHERE comp.op_id=? AND UPPER(COALESCE(cx.status,''))
          NOT IN ('CANCELADA','CANCELADO','ESTORNADA','ESTORNADO')
    """), (op_id,))
    caixas = cursor.fetchone()
    aves_vivas = float(op["quantidade_aves"] or 0)
    bandejas_consumidas = float(caixas["bandejas_consumidas"] or 0)
    peso_liquido_total = float(caixas["peso_liquido_total"] or 0)
    peso_bruto_total = float(caixas["peso_bruto_total"] or 0)
    saldo_aves = aves_vivas - (
        bandejas_primaria + descartes + condenacoes + mortes_antes_pendura
    )
    saldo_pi = bandejas_primaria - bandejas_consumidas
    pendencias = []
    if abs(saldo_aves) > 0.0001:
        pendencias.append(
            f"Balanço de aves divergente em {saldo_aves:g} aves. Revise Embalagem "
            "Primária, descartes, condenações ou mortes na gaiola."
        )
    if abs(saldo_pi) > 0.0001:
        pendencias.append(
            (f"Existem {saldo_pi:g} bandejas sem pesagem. Lance uma caixa parcial antes de encerrar."
             if saldo_pi > 0 else
             f"A Embalagem Secundária consumiu {-saldo_pi:g} bandejas a mais que o PI produzido.")
        )
    exige_peso = str(op["sku"] or "") != "Galinha Inteira"
    if int(caixas["caixas"] or 0) == 0 or (exige_peso and peso_liquido_total <= 0):
        pendencias.append(
            "Nenhuma caixa com peso líquido foi registrada para esta OP."
            if exige_peso else "Nenhuma posição de pacotes foi registrada para esta OP."
        )
    if str(op["status"] or "") != "Aberta":
        pendencias.append(f"Esta OP está em situação {op['status']} e não pode ser encerrada novamente.")
    return {
        "op": op, "aves_vivas": aves_vivas,
        "mortes_antes_pendura": mortes_antes_pendura,
        "bandejas_primaria": bandejas_primaria,
        "descartes": descartes, "condenacoes": condenacoes,
        "bandejas_consumidas": bandejas_consumidas,
        "peso_liquido_total": peso_liquido_total,
        "peso_bruto_total": peso_bruto_total,
        "saldo_aves": saldo_aves, "saldo_pi": saldo_pi,
        "pendencias": pendencias,
        "pode_encerrar": not pendencias,
    }


def _preflight_cursor(cursor, op, bloquear=False):
    op_id = int(op["id"])
    caixas = _carregar_caixas(cursor, op_id, bloquear=bloquear)
    ativas = [c for c in caixas if str(c["status"] or "").upper() not in STATUS_INATIVOS]
    pi = _livro_pi(cursor, op_id, bloquear=bloquear)
    fechamento = _calcular_fechamento_cursor(cursor, op)
    bloqueios = list(fechamento["pendencias"])
    saldo_pi = Decimal(str(pi["saldo"] or 0))
    possui_movimentos_pa = _tabela_existe(cursor, "pa_movimentacoes")
    possui_expedicao_itens = _tabela_existe(cursor, "expedicao_itens")

    ids_ativas = [int(caixa["id"]) for caixa in ativas]
    composicoes_por_caixa = {}
    movimentos_por_caixa = {}
    expedicoes_por_caixa = {}
    if ids_ativas:
        marcadores = ",".join("?" for _ in ids_ativas)
        cursor.execute(q(f"""SELECT caixa_id,COUNT(DISTINCT op_id) total
            FROM pa_caixa_composicao WHERE caixa_id IN ({marcadores}) GROUP BY caixa_id"""), ids_ativas)
        composicoes_por_caixa = {int(item["caixa_id"]): int(item["total"] or 0) for item in cursor.fetchall()}
        if possui_movimentos_pa:
            cursor.execute(q(f"""SELECT caixa_id,COUNT(*) total FROM pa_movimentacoes
                WHERE caixa_id IN ({marcadores}) GROUP BY caixa_id"""), ids_ativas)
            movimentos_por_caixa = {int(item["caixa_id"]): int(item["total"] or 0) for item in cursor.fetchall()}
        if possui_expedicao_itens:
            cursor.execute(q(f"""SELECT caixa_id,COUNT(*) total FROM expedicao_itens
                WHERE caixa_id IN ({marcadores}) GROUP BY caixa_id"""), ids_ativas)
            expedicoes_por_caixa = {int(item["caixa_id"]): int(item["total"] or 0) for item in cursor.fetchall()}

    if saldo_pi != 0:
        bloqueios.append(
            f"Saldo real de PI divergente. Esperado 0, encontrado {saldo_pi.normalize()} bandeja(s)."
        )
    if not ativas:
        bloqueios.append("Nenhuma caixa ativa foi encontrada para a OP.")

    pendentes = 0
    operacionais = 0
    for caixa in ativas:
        codigo = caixa["codigo_caixa"]
        disponibilidade = str(_valor(caixa, "disponibilidade", "") or "").upper()
        operacional = int(_valor(caixa, "estoque_operacional", 0) or 0)
        operacionais += 1 if operacional else 0
        if disponibilidade == "PENDENTE_OP" and not operacional:
            pendentes += 1
        else:
            bloqueios.append(
                f"Caixa {codigo}: esperado PENDENTE_OP não operacional; "
                f"encontrado {disponibilidade or 'sem disponibilidade'}, operacional={operacional}."
            )
        if _valor(caixa, "reservado_expedicao_id") or Decimal(
            str(_valor(caixa, "quantidade_pacotes_reservados", 0) or 0)
        ) > 0:
            bloqueios.append(f"Caixa {codigo}: possui reserva operacional ativa.")
        caixa_id = int(caixa["id"])
        if composicoes_por_caixa.get(caixa_id, 0) != 1:
            bloqueios.append(
                f"Caixa {codigo}: composição mista impede encerramento atômico desta OP."
            )
        if movimentos_por_caixa.get(caixa_id, 0):
            bloqueios.append(f"Caixa {codigo}: possui movimentação de PA anterior ao encerramento.")
        if expedicoes_por_caixa.get(caixa_id, 0):
            bloqueios.append(f"Caixa {codigo}: já está vinculada a romaneio ou expedição.")

    bloqueios = list(dict.fromkeys(bloqueios))
    status = str(op["status"] or "")
    pronta = status == "Aberta" and saldo_pi == 0 and bool(ativas) and pendentes == len(ativas) and not bloqueios
    caixas_itens = [{
        "id": int(caixa["id"]),
        "codigo": caixa["codigo_caixa"],
        "bandejas": float(_valor(caixa, "quantidade_bandejas", 0) or 0),
        "peso_liquido": float(_valor(caixa, "peso_liquido", 0) or 0),
        "peso_bruto": float(_valor(caixa, "peso_bruto", 0) or 0),
        "fabricacao": str(_valor(caixa, "data_fabricacao", "") or ""),
        "validade": str(_valor(caixa, "data_validade", "") or ""),
        "status": caixa["status"],
        "disponibilidade": _valor(caixa, "disponibilidade", ""),
        "estoque_operacional": int(_valor(caixa, "estoque_operacional", 0) or 0),
    } for caixa in ativas]
    caixas_dados_hash = hashlib.sha256(
        json.dumps([
            {k: v for k, v in item.items() if k not in {
                "status", "disponibilidade", "estoque_operacional"
            }} for item in caixas_itens
        ], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    resultado = {
        "op_id": op_id,
        "op": op,
        "status": status,
        "versao_operacional": int(_valor(op, "versao_operacional", 0) or 0),
        "permitido": pronta,
        "pronta_para_encerramento": pronta,
        "bloqueios": bloqueios,
        "pode_encerrar": pronta,
        "pendencias": bloqueios,
        "pi": {
            "entradas": float(pi["entradas"] or 0),
            "saidas": float(pi["saidas"] or 0),
            "saldo": float(pi["saldo"] or 0),
        },
        "caixas_ativas": len(ativas),
        "caixas": len(ativas),
        "caixas_estornadas": len(caixas) - len(ativas),
        "caixas_pendentes": pendentes,
        "caixas_dados_hash": caixas_dados_hash,
        "caixas_itens": caixas_itens,
        "aves_vivas": fechamento.get("aves_vivas", 0),
        "mortes_antes_pendura": fechamento.get("mortes_antes_pendura", 0),
        "bandejas_primaria": fechamento.get("bandejas_primaria", fechamento["bandejas_consumidas"]),
        "descartes": fechamento.get("descartes", 0),
        "condenacoes": fechamento.get("condenacoes", 0),
        "bandejas_consumidas": fechamento["bandejas_consumidas"],
        "saldo_pi": float(pi["saldo"] or 0),
        "peso_liquido_total": fechamento["peso_liquido_total"],
        "peso_bruto_total": fechamento.get("peso_bruto_total", fechamento["peso_liquido_total"]),
        "fechamento": fechamento,
    }
    from modules.producao.integridade_encerramento import (
        BLOQUEADA_PARA_ENCERRAMENTO, ESTADO_INCONSISTENTE, classificar_estado_funcional,
    )
    snapshot_estado = {
        "status": status, "caixas": len(ativas), "caixas_pendentes": pendentes,
        "caixas_operacionais": operacionais, "eventos_formacao": 0,
        "eventos_duplicados": 0, "saldo_pi": pi["saldo"],
        "bandejas_pi": pi["consumo_liquido"],
        "bandejas_caixas": fechamento["bandejas_consumidas"],
        "peso_liquido": fechamento["peso_liquido_total"], "caixas_mistas": 0,
        "codigos_duplicados": 0, "auditorias_sucesso": 0, "sucessos_incoerentes": 0,
        "bandejas_primaria": fechamento["bandejas_primaria"],
        "quantidade_aves": fechamento["aves_vivas"], "descartes": fechamento["descartes"],
        "condenacoes": fechamento["condenacoes"],
        "mortes_antes_pendura": fechamento["mortes_antes_pendura"], "mortes_na_gaiola": 0,
        "sku": _valor(op, "sku", ""),
    }
    estado, motivos_estado = classificar_estado_funcional(snapshot_estado)
    if bloqueios and estado != ESTADO_INCONSISTENTE:
        estado, motivos_estado = BLOQUEADA_PARA_ENCERRAMENTO, bloqueios
    resultado["estado_funcional"] = estado
    resultado["motivos_estado"] = motivos_estado
    return resultado


def preflight_encerramento_op(op_id):
    """Executa apenas SELECTs e não cria schema, eventos ou auditoria."""
    conn = conectar()
    try:
        cursor = conn.cursor()
        op = _carregar_op(cursor, int(op_id))
        return _preflight_cursor(cursor, op)
    finally:
        conn.close()


def _resultado_idempotente(cursor, chave):
    if not chave or not _tabela_existe(cursor, "op_operacoes_auditoria"):
        return None
    cursor.execute(q(
        "SELECT resultado_json FROM op_operacoes_auditoria WHERE idempotency_key=?"
    ), (chave,))
    linha = cursor.fetchone()
    return json.loads(linha["resultado_json"]) if linha else None


def _resultado_encerramento_anterior(cursor, op_id):
    if not _tabela_existe(cursor, "op_operacoes_auditoria"):
        return None
    cursor.execute(q("""SELECT resultado_json FROM op_operacoes_auditoria
        WHERE op_id=? AND tipo=? ORDER BY id DESC LIMIT 1"""), (op_id, TIPO_AUDITORIA))
    linha = cursor.fetchone()
    return json.loads(linha["resultado_json"]) if linha else None


def _auditar(cursor, op_id, chave, usuario, perfil, preflight, resultado, ip_origem):
    cursor.execute(q("""INSERT INTO op_operacoes_auditoria(
        op_id,tipo,idempotency_key,usuario,perfil,motivo,etapa_destino,
        status_anterior,status_posterior,preflight_json,efeitos_json,
        resultado_json,ip_origem,criado_em
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""), (
        op_id, TIPO_AUDITORIA, chave, usuario or "Sistema", perfil or "sistema",
        "Encerramento industrial pelo serviço oficial", "ESTOQUE_PA",
        "Aberta", "Encerrada",
        json.dumps({k: v for k, v in preflight.items() if k not in {"fechamento", "op"}}, ensure_ascii=False, default=str),
        json.dumps({
            "caixas_liberadas": resultado["caixas_liberadas"],
            "pi_consumido_novamente": 0,
            "caixas_criadas": 0,
            "financeiro_alterado": False,
        }, ensure_ascii=False),
        json.dumps(resultado, ensure_ascii=False), ip_origem, _agora(),
    ))


def _registrar_tentativa_inicio(*, correlation_id, request_id, op_id, chave, usuario,
                                perfil, versao_recebida, ip_origem):
    conn = conectar()
    try:
        cursor = conn.cursor()
        if not _tabela_existe(cursor, "op_encerramento_tentativas"):
            raise RuntimeError("Estrutura de auditoria das tentativas de encerramento indisponível.")
        cursor.execute(q("""INSERT INTO op_encerramento_tentativas(
            correlation_id,request_id,op_id,idempotency_key,usuario,perfil,
            versao_recebida,validacoes_json,resultado,resultado_json,duracao_ms,
            ip_origem,criado_em)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"""), (
            correlation_id, request_id, op_id, chave, usuario or "Sistema",
            perfil or "sistema", None if versao_recebida in (None, "") else int(versao_recebida),
            "{}", "EM_PROCESSAMENTO", "{}", 0, ip_origem, _agora(),
        ))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _concluir_tentativa(correlation_id, *, telemetria, resultado, motivo, dados, duracao_ms):
    conn = conectar()
    try:
        cursor = conn.cursor()
        if not _tabela_existe(cursor, "op_encerramento_tentativas"):
            return
        cursor.execute(q("""UPDATE op_encerramento_tentativas SET
            versao_encontrada=?,validacoes_json=?,motivo_rejeicao=?,resultado=?,
            resultado_json=?,duracao_ms=?,concluido_em=? WHERE correlation_id=?"""), (
            telemetria.get("versao_encontrada"),
            json.dumps(telemetria.get("validacoes") or {}, ensure_ascii=False, default=str),
            motivo, resultado, json.dumps(dados or {}, ensure_ascii=False, default=str),
            int(duracao_ms), _agora(), correlation_id,
        ))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def _concluir_tentativa_sucesso_cursor(cursor, correlation_id, telemetria, resultado, duracao_ms):
    cursor.execute(q("""UPDATE op_encerramento_tentativas SET
        versao_encontrada=?,validacoes_json=?,motivo_rejeicao=NULL,resultado='SUCESSO',
        resultado_json=?,duracao_ms=?,concluido_em=? WHERE correlation_id=?"""), (
        telemetria.get("versao_encontrada"),
        json.dumps(telemetria.get("validacoes") or {}, ensure_ascii=False, default=str),
        json.dumps(resultado, ensure_ascii=False, default=str), int(duracao_ms), _agora(),
        correlation_id,
    ))
    if cursor.rowcount != 1:
        raise RuntimeError("A tentativa de encerramento não pôde ser concluída na auditoria.")


def _validar_pos_condicoes(cursor, op_id, preflight, chave):
    """Valida o estado que será commitado; qualquer falha aborta toda a transação."""
    op_final = _carregar_op(cursor, op_id)
    erros = []
    if str(op_final["status"] or "") != "Encerrada":
        erros.append("a OP não permaneceu Encerrada")
    pi = _livro_pi(cursor, op_id)
    if _decimal(pi["saldo"] if isinstance(pi, dict) else pi["saldo"]) != Decimal("0"):
        erros.append(f"o saldo de PI permaneceu em {pi['saldo']}")
    caixas = _carregar_caixas(cursor, op_id)
    ativas = [c for c in caixas if str(c["status"] or "").upper() not in STATUS_INATIVOS]
    if len(ativas) != int(preflight["caixas_ativas"]):
        erros.append("a quantidade física de caixas foi alterada durante o encerramento")
    pendentes = [c for c in ativas if str(_valor(c, "disponibilidade", "") or "").upper() == "PENDENTE_OP"]
    nao_operacionais = [c for c in ativas if int(_valor(c, "estoque_operacional", 0) or 0) != 1]
    if pendentes:
        erros.append(f"{len(pendentes)} caixa(s) permaneceram em PENDENTE_OP")
    if nao_operacionais:
        erros.append(f"{len(nao_operacionais)} caixa(s) não ficaram operacionais")
    cursor.execute(q("""SELECT COUNT(*) total FROM (
        SELECT codigo_caixa FROM pa_caixas WHERE id IN(
          SELECT caixa_id FROM pa_caixa_composicao WHERE op_id=?)
        AND UPPER(COALESCE(status,'')) NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')
        GROUP BY codigo_caixa HAVING COUNT(*)<>1) d"""), (op_id,))
    if int(cursor.fetchone()["total"] or 0):
        erros.append("há código de caixa duplicado")
    cursor.execute(q("""SELECT COUNT(*) total FROM (
        SELECT alvo.caixa_id FROM pa_caixa_composicao alvo
        JOIN pa_caixa_composicao todas ON todas.caixa_id=alvo.caixa_id
        WHERE alvo.op_id=? GROUP BY alvo.caixa_id
        HAVING COUNT(DISTINCT todas.op_id)<>1) d"""), (op_id,))
    if int(cursor.fetchone()["total"] or 0):
        erros.append("há composição de caixa duplicada ou mista")
    cursor.execute(q("""SELECT COUNT(*) total FROM (
        SELECT cx.id FROM pa_caixas cx
        JOIN pa_caixa_composicao c ON c.caixa_id=cx.id
        LEFT JOIN estoque_eventos ev ON ev.caixa_id=cx.id AND ev.acao='FORMACAO_ESTOQUE'
        WHERE c.op_id=? AND UPPER(COALESCE(cx.status,''))
          NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')
        GROUP BY cx.id HAVING COUNT(ev.id)<>1) d"""), (op_id,))
    if int(cursor.fetchone()["total"] or 0):
        erros.append("há movimento de formação de PA ausente ou duplicado")
    depois = _preflight_cursor(cursor, op_final)
    if depois["caixas_dados_hash"] != preflight["caixas_dados_hash"]:
        erros.append("código, fabricação, validade ou composição física de caixa foi alterado")
    peso_esperado = Decimal(str(preflight["peso_liquido_total"])).quantize(Decimal("0.001"))
    peso_operacional = sum(
        (Decimal(str(_valor(c, "peso_liquido", 0) or 0)) for c in ativas
         if int(_valor(c, "estoque_operacional", 0) or 0) == 1), Decimal("0")
    ).quantize(Decimal("0.001"))
    if peso_operacional != peso_esperado:
        erros.append(f"peso operacional {peso_operacional} kg diverge do físico {peso_esperado} kg")
    if Decimal(str(depois["bandejas_consumidas"])) != Decimal(str(preflight["bandejas_consumidas"])):
        erros.append("quantidade de bandejas diverge do consumo registrado")
    cursor.execute(q("""SELECT COUNT(*) total FROM op_operacoes_auditoria
        WHERE op_id=? AND tipo=? AND idempotency_key=?"""), (op_id, TIPO_AUDITORIA, chave))
    if int(cursor.fetchone()["total"] or 0) != 1:
        erros.append("a auditoria oficial não foi persistida exatamente uma vez")
    if erros:
        raise RuntimeError("Pós-validação do encerramento falhou: " + "; ".join(erros) + ".")
    return {"op_encerrada": True, "caixas_pendentes": 0,
            "caixas_operacionais": len(ativas), "saldo_pi": 0,
            "peso_operacional": float(peso_operacional),
            "bandejas": float(preflight["bandejas_consumidas"]),
            "dados_fisicos_preservados": True}


def _decimal(valor):
    return Decimal(str(valor or 0))


def _encerrar_op_transacional(
    op_id, *, checkpoint=None, nao_conformes=None, conferencia_hash=None,
    exigir_conferencia=False, usuario=None, perfil=None, idempotency_key=None,
    versao_esperada=None, ip_origem=None, telemetria=None, preparador=None,
):
    """Encerra a OP e libera seu PA na mesma transação lógica."""
    from .conferencia_embalagem import validar_conferencia_para_encerramento
    from .estoque_service import ativar_estoque_op_encerrada

    op_id = int(op_id)
    with transaction() as conn:
        cursor = conn.cursor()
        if not DATABASE_URL:
            # SQLite não possui SELECT ... FOR UPDATE. O lock de escrita no
            # início reproduz a serialização da OP usada pelo PostgreSQL.
            cursor.execute("BEGIN IMMEDIATE")
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            existente["ja_encerrada"] = True
            existente["correlation_id"] = telemetria["correlation_id"]
            existente["request_id"] = telemetria["request_id"]
            _concluir_tentativa_sucesso_cursor(
                cursor, telemetria["correlation_id"], telemetria, existente,
                round((time.perf_counter() - telemetria["inicio"]) * 1000),
            )
            return existente

        op = _carregar_op(cursor, op_id, bloquear=True)
        versao_atual = int(_valor(op, "versao_operacional", 0) or 0)
        if telemetria is not None:
            telemetria["versao_encontrada"] = versao_atual
        chave = idempotency_key or f"ENCERRAMENTO-OP-{op_id}-V{versao_atual}"
        if str(op["status"] or "") == "Encerrada":
            anterior = _resultado_encerramento_anterior(cursor, op_id)
            if anterior:
                anterior["ja_encerrada"] = True
                anterior["correlation_id"] = telemetria["correlation_id"]
                anterior["request_id"] = telemetria["request_id"]
                _concluir_tentativa_sucesso_cursor(
                    cursor, telemetria["correlation_id"], telemetria, anterior,
                    round((time.perf_counter() - telemetria["inicio"]) * 1000),
                )
                return anterior
            raise ValueError(f"A OP #{op_id} já está encerrada; nenhuma operação foi repetida.")
        if versao_esperada not in (None, "") and int(versao_esperada) != versao_atual:
            raise ValueError(
                f"Conflito de versão da OP #{op_id}. Esperada {versao_esperada}, "
                f"encontrada {versao_atual}. Atualize a página e tente novamente."
            )
        if exigir_conferencia:
            validar_conferencia_para_encerramento(cursor, op_id, conferencia_hash)

        preparacao = preparador(cursor, op, checkpoint) if preparador else {}
        preparacao = preparacao or {}
        nao_conformes_efetivos = preparacao.get("nao_conformes", nao_conformes)

        preflight = _preflight_cursor(cursor, op, bloquear=True)
        if telemetria is not None:
            telemetria["validacoes"] = {
                "estado": "PRONTA_PARA_ENCERRAMENTO" if preflight["permitido"] else "BLOQUEADA_PARA_ENCERRAMENTO",
                "permitido": preflight["permitido"], "bloqueios": preflight["bloqueios"],
                "saldo_pi": preflight["saldo_pi"], "caixas": preflight["caixas_ativas"],
            }
        if not preflight["permitido"]:
            raise ValueError(
                f"Não foi possível encerrar a OP #{op_id}: " + " ".join(preflight["bloqueios"])
            )
        fechamento = preflight["fechamento"]
        if checkpoint:
            checkpoint("antes_formacao_estoque")
        gerar_producao_automatica_setores(
            op=op, data_lancamento=op["data"], hora_inicio="N/A", hora_fim="N/A",
            unidades_produzidas=fechamento["bandejas_consumidas"],
            kg_produzidos=(None if str(op["sku"] or "") == "Galinha Inteira"
                           else fechamento["peso_liquido_total"]),
            descontar_almoco=False, conn=conn,
        )

        possui_versao = "versao_operacional" in op.keys()
        if possui_versao:
            cursor.execute(q("""UPDATE ordens_producao
                SET status='Encerrada',versao_operacional=COALESCE(versao_operacional,0)+1
                WHERE id=? AND status='Aberta' AND COALESCE(versao_operacional,0)=?"""),
                (op_id, versao_atual))
        else:
            cursor.execute(q("UPDATE ordens_producao SET status='Encerrada' WHERE id=? AND status='Aberta'"), (op_id,))
        if cursor.rowcount != 1:
            raise ValueError("A OP foi alterada por outra solicitação; encerramento cancelado integralmente.")
        if checkpoint:
            checkpoint("durante_formacao_estoque")
        if nao_conformes_efetivos:
            from modules.qualidade.produtos_nao_conformes import registrar_itens_encerramento
            registrar_itens_encerramento(cursor, op_id, nao_conformes_efetivos, checkpoint=checkpoint)
        caixas_liberadas = ativar_estoque_op_encerrada(cursor, op_id)
        cursor.execute(q("""SELECT COUNT(*) total FROM pa_caixas cx
            WHERE EXISTS (SELECT 1 FROM pa_caixa_composicao c WHERE c.caixa_id=cx.id AND c.op_id=?)
              AND UPPER(COALESCE(cx.status,'')) NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')
              AND (COALESCE(cx.estoque_operacional,0)<>1 OR COALESCE(cx.disponibilidade,'')='PENDENTE_OP')"""),
            (op_id,))
        restantes = int(cursor.fetchone()["total"] or 0)
        if restantes:
            raise RuntimeError(f"Formação de PA incompleta: {restantes} caixa(s) permaneceriam pendentes.")
        if checkpoint:
            checkpoint("apos_formacao_estoque")

        resultado = {
            "sucesso": True,
            "ja_encerrada": False,
            "op_id": op_id,
            "status_anterior": "Aberta",
            "status_posterior": "Encerrada",
            "versao_anterior": versao_atual,
            "versao_posterior": versao_atual + (1 if possui_versao else 0),
            "caixas": preflight["caixas_ativas"],
            "caixas_liberadas": caixas_liberadas,
            "bandejas_consumidas": fechamento["bandejas_consumidas"],
            "peso_liquido_total": fechamento["peso_liquido_total"],
            "peso_bruto_total": fechamento.get("peso_bruto_total", fechamento["peso_liquido_total"]),
            "pi_consumido_novamente": 0,
            "caixas_criadas": 0,
            "idempotency_key": chave,
        }
        resultado.update(preparacao.get("resultado_extra") or {})
        if _tabela_existe(cursor, "op_operacoes_auditoria"):
            _auditar(cursor, op_id, chave, usuario, perfil, preflight, resultado, ip_origem)
        if checkpoint:
            checkpoint("apos_auditoria")
        resultado["pos_condicoes"] = _validar_pos_condicoes(cursor, op_id, preflight, chave)
        resultado["correlation_id"] = telemetria["correlation_id"]
        resultado["request_id"] = telemetria["request_id"]
        _concluir_tentativa_sucesso_cursor(
            cursor, telemetria["correlation_id"], telemetria, resultado,
            round((time.perf_counter() - telemetria["inicio"]) * 1000),
        )
        return resultado


def encerrar_op_oficial(
    op_id, *, checkpoint=None, nao_conformes=None, conferencia_hash=None,
    exigir_conferencia=False, usuario=None, perfil=None, idempotency_key=None,
    versao_esperada=None, ip_origem=None, request_id=None, preparador=None,
):
    """Fachada observável: só devolve sucesso depois do commit da transação oficial."""
    op_id = int(op_id)
    correlation_id = str(uuid.uuid4())
    request_id = str(request_id or correlation_id)
    inicio = time.perf_counter()
    telemetria = {
        "versao_encontrada": None, "validacoes": {}, "correlation_id": correlation_id,
        "request_id": request_id, "inicio": inicio,
    }
    try:
        _registrar_tentativa_inicio(
            correlation_id=correlation_id, request_id=request_id, op_id=op_id,
            chave=idempotency_key, usuario=usuario, perfil=perfil,
            versao_recebida=versao_esperada, ip_origem=ip_origem,
        )
        resultado = _encerrar_op_transacional(
            op_id, checkpoint=checkpoint, nao_conformes=nao_conformes,
            conferencia_hash=conferencia_hash, exigir_conferencia=exigir_conferencia,
            usuario=usuario, perfil=perfil, idempotency_key=idempotency_key,
            versao_esperada=versao_esperada, ip_origem=ip_origem, telemetria=telemetria,
            preparador=preparador,
        )
        return resultado
    except Exception as erro:
        duracao = round((time.perf_counter() - inicio) * 1000)
        motivo = str(erro) or erro.__class__.__name__
        _concluir_tentativa(correlation_id, telemetria=telemetria, resultado="REJEITADA",
                            motivo=motivo, dados={"sucesso": False}, duracao_ms=duracao)
        mensagem = (f"Não foi possível encerrar a OP #{op_id}. A operação não foi gravada. "
                    f"Motivo: {motivo} Identificador: {correlation_id}.")
        if isinstance(erro, PermissionError):
            raise PermissionError(mensagem) from erro
        if isinstance(erro, ValueError):
            raise ValueError(mensagem) from erro
        raise RuntimeError(mensagem) from erro
