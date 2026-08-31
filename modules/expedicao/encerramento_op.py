"""Encerramento oficial, transacional, auditável e idempotente de OP."""

from datetime import datetime
from decimal import Decimal
import hashlib
import json

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
    if int(caixas["caixas"] or 0) == 0 or peso_liquido_total <= 0:
        pendencias.append("Nenhuma caixa com peso líquido foi registrada para esta OP.")
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

    if saldo_pi != 0:
        bloqueios.append(
            f"Saldo real de PI divergente. Esperado 0, encontrado {saldo_pi.normalize()} bandeja(s)."
        )
    if not ativas:
        bloqueios.append("Nenhuma caixa ativa foi encontrada para a OP.")

    pendentes = 0
    for caixa in ativas:
        codigo = caixa["codigo_caixa"]
        disponibilidade = str(_valor(caixa, "disponibilidade", "") or "").upper()
        operacional = int(_valor(caixa, "estoque_operacional", 0) or 0)
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
        cursor.execute(q(
            "SELECT COUNT(DISTINCT op_id) total FROM pa_caixa_composicao WHERE caixa_id=?"
        ), (caixa["id"],))
        if int(cursor.fetchone()["total"] or 0) != 1:
            bloqueios.append(
                f"Caixa {codigo}: composição mista impede encerramento atômico desta OP."
            )
        if possui_movimentos_pa:
            cursor.execute(q("SELECT COUNT(*) total FROM pa_movimentacoes WHERE caixa_id=?"), (caixa["id"],))
            if int(cursor.fetchone()["total"] or 0):
                bloqueios.append(f"Caixa {codigo}: possui movimentação de PA anterior ao encerramento.")
        if possui_expedicao_itens:
            cursor.execute(q("SELECT COUNT(*) total FROM expedicao_itens WHERE caixa_id=?"), (caixa["id"],))
            if int(cursor.fetchone()["total"] or 0):
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
    return {
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


def encerrar_op_oficial(
    op_id, *, checkpoint=None, nao_conformes=None, conferencia_hash=None,
    exigir_conferencia=False, usuario=None, perfil=None, idempotency_key=None,
    versao_esperada=None, ip_origem=None,
):
    """Encerra a OP e libera seu PA na mesma transação lógica."""
    from .conferencia_embalagem import validar_conferencia_para_encerramento
    from .estoque_service import ativar_estoque_op_encerrada

    op_id = int(op_id)
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            existente["ja_encerrada"] = True
            return existente

        op = _carregar_op(cursor, op_id, bloquear=True)
        versao_atual = int(_valor(op, "versao_operacional", 0) or 0)
        chave = idempotency_key or f"ENCERRAMENTO-OP-{op_id}-V{versao_atual}"
        if str(op["status"] or "") == "Encerrada":
            anterior = _resultado_encerramento_anterior(cursor, op_id)
            if anterior:
                anterior["ja_encerrada"] = True
                return anterior
            raise ValueError(f"A OP #{op_id} já está encerrada; nenhuma operação foi repetida.")
        if versao_esperada not in (None, "") and int(versao_esperada) != versao_atual:
            raise ValueError(
                f"Conflito de versão da OP #{op_id}. Esperada {versao_esperada}, "
                f"encontrada {versao_atual}. Atualize a página e tente novamente."
            )
        if exigir_conferencia:
            validar_conferencia_para_encerramento(cursor, op_id, conferencia_hash)

        preflight = _preflight_cursor(cursor, op, bloquear=True)
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
            kg_produzidos=fechamento["peso_liquido_total"],
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
        if nao_conformes:
            from modules.qualidade.produtos_nao_conformes import registrar_itens_encerramento
            registrar_itens_encerramento(cursor, op_id, nao_conformes, checkpoint=checkpoint)
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
        if _tabela_existe(cursor, "op_operacoes_auditoria"):
            _auditar(cursor, op_id, chave, usuario, perfil, preflight, resultado, ip_origem)
        if checkpoint:
            checkpoint("apos_auditoria")
        return resultado
