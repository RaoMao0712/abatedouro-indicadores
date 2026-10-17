"""Reabertura e estorno integral, auditaveis e atomicos, de ordens de producao."""

from datetime import datetime
from decimal import Decimal
import json
import os

from database import DATABASE_URL, conectar, q, transaction
from modules.expedicao.estornos_embalagem import (
    STATUS_INATIVOS,
    _bloqueio_sql,
    _buscar_bloqueios,
    _carregar_contexto,
    _estornar_caixa_cursor,
    _movimentos_pi_originais,
    _totais_op,
    criar_tabelas_estornos_embalagem,
    funcionalidade_estorno_habilitada,
)
from modules.expedicao.movimentacoes_canonicas import buscar_eventos_sucessores_cursor
from .performance import invalidar_por_reabertura


PERFIS_AUTORIZADOS = {"admin", "pcp", "gerencia"}
ETAPAS_REABERTURA = {
    "EMBALAGEM_SECUNDARIA": "Embalagem Secundária",
    "CONFERENCIA_FINAL": "Conferência final",
}
_SCHEMA_INICIALIZADO = False


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


def _decimal(valor):
    return Decimal(str(valor or 0))


def _alterar(cursor, postgres_sql, sqlite_sql):
    try:
        cursor.execute(postgres_sql if DATABASE_URL else sqlite_sql)
    except Exception as erro:
        if DATABASE_URL or "duplicate column" not in str(erro).lower():
            raise


def funcionalidade_operacoes_op_habilitada():
    return os.getenv("OP_REVERSAL_REOPEN_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on", "sim",
    }


def criar_tabelas_operacoes_op():
    """Migration de runtime aditiva, idempotente e compativel com SQLite/Postgres."""
    global _SCHEMA_INICIALIZADO
    if _SCHEMA_INICIALIZADO:
        return
    criar_tabelas_estornos_embalagem()
    from modules.expedicao.conferencia_embalagem import criar_tabelas_conferencia_embalagem
    criar_tabelas_conferencia_embalagem()
    conn = conectar()
    cursor = conn.cursor()
    try:
        id_pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
        timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"
        if not DATABASE_URL:
            # Em producao a coluna ja e provisionada pela migration versionada
            # database/20260825_p0_2_estorno_reabertura_op.sql. Repetir o ALTER
            # TABLE a cada boot de worker exige lock ACCESS EXCLUSIVE em
            # ordens_producao e pode enfileirar leituras concorrentes (ex.:
            # /op/<id>/editar) atras dele. Mantido apenas para SQLite.
            _alterar(cursor,
                     "ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS versao_operacional INTEGER NOT NULL DEFAULT 0",
                     "ALTER TABLE ordens_producao ADD COLUMN versao_operacional INTEGER NOT NULL DEFAULT 0")
        _alterar(cursor,
                 "ALTER TABLE apontamentos_producao ADD COLUMN IF NOT EXISTS vigente INTEGER NOT NULL DEFAULT 1",
                 "ALTER TABLE apontamentos_producao ADD COLUMN vigente INTEGER NOT NULL DEFAULT 1")
        _alterar(cursor,
                 "ALTER TABLE apontamentos_producao ADD COLUMN IF NOT EXISTS invalidado_em TIMESTAMP",
                 "ALTER TABLE apontamentos_producao ADD COLUMN invalidado_em TEXT")
        _alterar(cursor,
                 "ALTER TABLE apontamentos_producao ADD COLUMN IF NOT EXISTS invalidado_por TEXT",
                 "ALTER TABLE apontamentos_producao ADD COLUMN invalidado_por TEXT")
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS op_operacoes_auditoria (
                id {id_pk}, op_id INTEGER NOT NULL, tipo TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE, usuario TEXT NOT NULL,
                perfil TEXT NOT NULL, motivo TEXT NOT NULL, etapa_destino TEXT,
                status_anterior TEXT, status_posterior TEXT,
                preflight_json TEXT NOT NULL, efeitos_json TEXT NOT NULL,
                resultado_json TEXT NOT NULL, ip_origem TEXT,
                criado_em {timestamp_type} NOT NULL
            )
        """)
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS op_encerramento_tentativas (
                id {id_pk}, correlation_id TEXT NOT NULL UNIQUE,
                request_id TEXT, op_id INTEGER NOT NULL,
                idempotency_key TEXT, usuario TEXT NOT NULL,
                perfil TEXT NOT NULL, versao_recebida INTEGER,
                versao_encontrada INTEGER, validacoes_json TEXT NOT NULL,
                motivo_rejeicao TEXT, resultado TEXT NOT NULL,
                resultado_json TEXT NOT NULL, duracao_ms INTEGER NOT NULL DEFAULT 0,
                ip_origem TEXT, criado_em {timestamp_type} NOT NULL,
                concluido_em {timestamp_type}
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_op_operacoes_data ON op_operacoes_auditoria(op_id, criado_em)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_op_tentativas_op_data ON op_encerramento_tentativas(op_id, criado_em)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_op_tentativas_resultado ON op_encerramento_tentativas(resultado, criado_em)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_op_tentativas_idempotencia ON op_encerramento_tentativas(idempotency_key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_apontamentos_producao_vigente ON apontamentos_producao(op_id, vigente)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ops_status_data_id ON ordens_producao(status, data, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_estoque_eventos_caixa_acao ON estoque_eventos(caixa_id, acao)")
        conn.commit()
        _SCHEMA_INICIALIZADO = True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _validar_autorizacao(usuario, perfil, motivo, idempotency_key):
    if not funcionalidade_operacoes_op_habilitada():
        raise PermissionError("Reabertura e estorno integral de OP estão temporariamente desativados.")
    if str(perfil or "").lower() not in PERFIS_AUTORIZADOS:
        raise PermissionError("Seu perfil não possui permissão para reabrir ou estornar uma OP.")
    if not str(usuario or "").strip():
        raise ValueError("Usuário responsável não identificado.")
    if len(str(motivo or "").strip()) < 5:
        raise ValueError("Informe um motivo objetivo com ao menos 5 caracteres.")
    if not str(idempotency_key or "").strip():
        raise ValueError("Chave de idempotência obrigatória.")


def _resultado_idempotente(cursor, chave):
    cursor.execute(q("SELECT resultado_json FROM op_operacoes_auditoria WHERE idempotency_key=?"), (chave,))
    linha = cursor.fetchone()
    return json.loads(linha["resultado_json"]) if linha else None


def _caixas_op(cursor, op_id, bloquear=False):
    # PostgreSQL não permite FOR UPDATE em uma consulta com DISTINCT. O EXISTS
    # preserva uma linha por caixa e permite bloquear exatamente os registros
    # que serão revalidados/mutados pelo estorno integral.
    sql = """SELECT cx.* FROM pa_caixas cx
        WHERE EXISTS (
            SELECT 1 FROM pa_caixa_composicao comp
            WHERE comp.caixa_id=cx.id AND comp.op_id=?
        ) ORDER BY cx.id"""
    if bloquear:
        sql += _bloqueio_sql()
    cursor.execute(q(sql), (op_id,))
    return cursor.fetchall()


def _saldo_pi_op(cursor, op_id, bloquear=False):
    if bloquear and DATABASE_URL:
        cursor.execute(q("""SELECT id FROM estoque_produto_intermediario
            WHERE op_id=? ORDER BY id FOR UPDATE"""), (op_id,))
        cursor.fetchall()
    cursor.execute(q("""SELECT
        COALESCE(SUM(CASE
            WHEN tipo LIKE 'ENTRADA%%' THEN quantidade_bandejas
            WHEN tipo LIKE 'SAIDA%%' THEN -quantidade_bandejas
            ELSE quantidade_bandejas END),0) saldo,
        COALESCE(SUM(CASE WHEN tipo IN ('ENTRADA_OP','ENTRADA_EMBALAGEM_PRIMARIA')
            THEN quantidade_bandejas ELSE 0 END),0) entrada_base
        FROM estoque_produto_intermediario WHERE op_id=?"""), (op_id,))
    linha = cursor.fetchone()
    return _decimal(linha["saldo"]), _decimal(linha["entrada_base"])


def _preflight_retomada_cursor(cursor, op, caixas, *, bloquear=False):
    ativas = [c for c in caixas if str(c["status"] or "").upper() not in STATUS_INATIVOS]
    saldo_pi, entrada_base = _saldo_pi_op(cursor, op["id"], bloquear=bloquear)
    status = str(op["status"] or "")
    bloqueios = []
    if status != "Aguardando Embalagem Secundária":
        bloqueios.append(
            "A retomada explícita exige a situação Aguardando Embalagem Secundária; "
            f"situação atual: {status or 'não informada'}."
        )
    if entrada_base <= 0:
        bloqueios.append("A produção base não possui entrada válida de PI da Embalagem Primária.")
    if not ativas:
        bloqueios.append("A OP ainda não possui caixa ativa; utilize o lançamento inicial da Embalagem Secundária.")
    if saldo_pi <= 0:
        bloqueios.append("A OP não possui saldo pendente de PI para retomar a Embalagem Secundária.")
    totais = _totais_op(cursor, op["id"])
    return {
        "op_id": int(op["id"]), "tipo": "RETOMADA_EMBALAGEM_SECUNDARIA",
        "status_atual": status, "permitido": not bloqueios, "bloqueios": bloqueios,
        "caixas_total": len(caixas), "caixas_ativas": len(ativas),
        "caixas_estornadas": len(caixas) - len(ativas),
        "saldo_pi": str(saldo_pi), "entrada_pi_base": str(entrada_base), "totais": totais,
    }


def _agrupar_por_caixa(linhas):
    agrupado = {}
    for linha in linhas:
        agrupado.setdefault(int(linha["caixa_id"]), []).append(linha)
    return agrupado


def _dados_bloqueios_caixas(cursor, caixas):
    """Carrega em lote os vínculos usados pelos preflights, sem reduzir validações."""
    ids = [int(caixa["id"]) for caixa in caixas]
    if not ids:
        return {chave: {} for chave in ("composicoes", "expedicoes", "movimentacoes", "eventos", "pncs")}
    marcadores = ",".join("?" for _ in ids)

    cursor.execute(q(f"""SELECT caixa_id,id,op_id,quantidade_bandejas
        FROM pa_caixa_composicao WHERE caixa_id IN ({marcadores}) ORDER BY caixa_id,id"""), ids)
    composicoes = _agrupar_por_caixa(cursor.fetchall())
    cursor.execute(q(f"""SELECT i.caixa_id,e.numero_romaneio,e.status,e.id
        FROM expedicao_itens i JOIN expedicoes e ON e.id=i.expedicao_id
        WHERE i.caixa_id IN ({marcadores}) ORDER BY i.caixa_id,e.id"""), ids)
    expedicoes = _agrupar_por_caixa(cursor.fetchall())
    eventos = _agrupar_por_caixa(buscar_eventos_sucessores_cursor(cursor, ids))
    cursor.execute(q(f"""SELECT caixa_id,id,status,COALESCE(saldo_destinado_g,0) saldo_destinado_g
        FROM pa_nao_conformes WHERE caixa_id IN ({marcadores}) ORDER BY caixa_id,id"""), ids)
    pncs = _agrupar_por_caixa(cursor.fetchall())
    return {
        "composicoes": composicoes, "expedicoes": expedicoes,
        "eventos": eventos, "pncs": pncs,
    }


def _bloqueios_reabertura(cursor, op_id, caixas):
    bloqueios = []
    dados = _dados_bloqueios_caixas(cursor, caixas)
    for caixa in caixas:
        caixa_id = int(caixa["id"])
        if len({int(item["op_id"]) for item in dados["composicoes"].get(caixa_id, [])}) > 1:
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: composição mista com outra OP.")
        for item in dados["expedicoes"].get(caixa_id, []):
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: Romaneio nº {item['numero_romaneio']} ({item['status']}).")
        for item in dados["eventos"].get(caixa_id, []):
            descricao = "movimentação posterior" if item["fonte"] == "pa_movimentacoes_fallback" else "evento sucessor"
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: {descricao} {item['tipo']}.")
        if caixa["reservado_expedicao_id"] or _decimal(caixa["quantidade_pacotes_reservados"]) > 0:
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: reserva operacional ativa.")
        for pnc in dados["pncs"].get(caixa_id, []):
            status = str(pnc["status"] or "").upper()
            if status in {"LIBERADO", "DESTINADO", "DESCARTADO", "FINALIZADO", "REPROCESSADO"} or int(pnc["saldo_destinado_g"] or 0) > 0:
                bloqueios.append(f"Caixa {caixa['codigo_caixa']}: PNC nº {pnc['id']} já possui destinação ({pnc['status']}).")
    return list(dict.fromkeys(bloqueios))


def preflight_operacao_op(op_id, tipo):
    """Consulta estritamente read-only dos efeitos e impedimentos da operacao."""
    criar_tabelas_operacoes_op()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        caixas = _caixas_op(cursor, op_id)
        ativas = [c for c in caixas if str(c["status"] or "").upper() not in STATUS_INATIVOS]
        bloqueios = []
        if tipo == "REABERTURA":
            if op["status"] != "Encerrada":
                bloqueios.append(f"Somente OP Encerrada pode ser reaberta; situação atual: {op['status']}.")
            bloqueios.extend(_bloqueios_reabertura(cursor, op_id, ativas))
        elif tipo == "ESTORNO_INTEGRAL":
            if str(op["status"] or "").upper() in STATUS_INATIVOS:
                bloqueios.append(f"A OP já está {op['status']}; nenhuma nova mutação será executada.")
            if not funcionalidade_estorno_habilitada():
                bloqueios.append("O estorno de caixas está desativado pela feature flag.")
            dados = _dados_bloqueios_caixas(cursor, ativas)
            cursor.execute(q("""SELECT * FROM estoque_produto_intermediario
                WHERE op_id=? AND tipo='SAIDA_EMBALAGEM_SECUNDARIA' ORDER BY id"""), (op_id,))
            movimentos_op = cursor.fetchall()
            for caixa in ativas:
                caixa_id = int(caixa["id"])
                for item in dados["expedicoes"].get(caixa_id, []):
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: A caixa está vinculada ao Romaneio nº {item['numero_romaneio']} ({item['status']}).")
                for item in dados["pncs"].get(caixa_id, []):
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: A caixa está vinculada ao Produto Não Conforme nº {item['id']} ({item['status']}).")
                for item in dados["eventos"].get(caixa_id, []):
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: A caixa possui evento sucessor de estoque: {item['tipo']}.")
                if caixa["reservado_expedicao_id"]:
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: A caixa está reservada pelo romaneio interno #{caixa['reservado_expedicao_id']}.")
                if _decimal(caixa["quantidade_pacotes_reservados"]) > 0:
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: A caixa possui {caixa['quantidade_pacotes_reservados']} unidades reservadas.")
                disponibilidade = str(caixa["disponibilidade"] or "PENDENTE_OP").upper()
                if disponibilidade not in {"PENDENTE_OP", "DISPONIVEL"}:
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: A caixa está na situação operacional {disponibilidade}.")
                try:
                    composicoes = dados["composicoes"].get(caixa_id, [])
                    ops = {int(item["op_id"]) for item in composicoes}
                    if ops != {int(op_id)}:
                        raise ValueError("A caixa possui composição ausente ou vinculada a múltiplas OPs.")
                    movimentos = [item for item in movimentos_op if (
                        item["caixa_id"] is not None and int(item["caixa_id"]) == caixa_id
                    ) or (
                        item["caixa_id"] is None and f"caixa PA #{caixa_id}." in str(item["observacoes"] or "")
                    )]
                    esperado = sum((_decimal(item["quantidade_bandejas"]) for item in composicoes), Decimal("0"))
                    encontrado = sum((_decimal(item["quantidade_bandejas"]) for item in movimentos), Decimal("0"))
                    if not movimentos or encontrado != esperado:
                        raise ValueError(
                            f"Os movimentos originais de PI da caixa não estão íntegros: esperado {esperado}, encontrado {encontrado}."
                        )
                except ValueError as erro:
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: {erro}")
            cursor.execute(q("""SELECT COUNT(*) total FROM estoque_produto_intermediario
                WHERE op_id=? AND tipo IN ('ENTRADA_OP','ENTRADA_EMBALAGEM_PRIMARIA')"""), (op_id,))
            if caixas and int(cursor.fetchone()["total"] or 0) == 0:
                bloqueios.append("A OP possui caixas, mas o movimento original de entrada de PI não foi encontrado.")
        else:
            raise ValueError("Tipo de operação inválido.")
        totais = _totais_op(cursor, op_id)
        return {
            "op_id": int(op_id), "tipo": tipo, "status_atual": op["status"],
            "permitido": not bloqueios, "bloqueios": bloqueios,
            "caixas_total": len(caixas), "caixas_ativas": len(ativas),
            "caixas_estornadas": len(caixas) - len(ativas), "totais": totais,
        }
    finally:
        conn.close()


def preflight_retomada_embalagem_secundaria(op_id):
    """Consulta somente leitura para a retomada de uma OP parcialmente apontada."""
    criar_tabelas_operacoes_op()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        caixas = _caixas_op(cursor, op_id)
        return _preflight_retomada_cursor(cursor, op, caixas)
    finally:
        conn.close()


def _auditar(cursor, *, op_id, tipo, chave, usuario, perfil, motivo, etapa,
             status_anterior, status_posterior, preflight, efeitos, resultado, ip_origem):
    cursor.execute(q("""INSERT INTO op_operacoes_auditoria(
        op_id,tipo,idempotency_key,usuario,perfil,motivo,etapa_destino,status_anterior,
        status_posterior,preflight_json,efeitos_json,resultado_json,ip_origem,criado_em)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""), (
        op_id, tipo, chave, usuario, perfil, motivo.strip(), etapa, status_anterior,
        status_posterior, _json(preflight), _json(efeitos), _json(resultado), ip_origem, _agora(),
    ))


def retomar_embalagem_secundaria(op_id, *, usuario, perfil, idempotency_key,
                                  ip_origem=None, confirmacao=False):
    """Abre a etapa de caixas sem recriar ou apagar qualquer efeito da OP."""
    motivo = "Retomada operacional da Embalagem Secundária parcialmente apontada"
    _validar_autorizacao(usuario, perfil, motivo, idempotency_key)
    if not confirmacao:
        raise ValueError("Confirme expressamente a retomada preservando PI, PA, caixas e histórico.")
    criar_tabelas_operacoes_op()
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            return existente
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + _bloqueio_sql()), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        caixas = _caixas_op(cursor, op_id, bloquear=True)
        preflight = _preflight_retomada_cursor(cursor, op, caixas, bloquear=True)
        if not preflight["permitido"]:
            raise ValueError("Retomada bloqueada: " + " ".join(preflight["bloqueios"]))
        cursor.execute(q("""UPDATE ordens_producao SET status='Aberta',
            versao_operacional=COALESCE(versao_operacional,0)+1
            WHERE id=? AND status='Aguardando Embalagem Secundária'"""), (op_id,))
        if cursor.rowcount != 1:
            raise ValueError("A OP foi alterada concorrentemente; a retomada foi cancelada.")
        cursor.execute(q("UPDATE embalagem_secundaria_conferencias SET confirmada=0 WHERE op_id=? AND confirmada=1"), (op_id,))
        conferencias_invalidadas = cursor.rowcount
        efeitos = {
            "pi_preservado": True, "pa_preservado": True,
            "caixas_ativas_preservadas": preflight["caixas_ativas"],
            "caixas_estornadas_preservadas": preflight["caixas_estornadas"],
            "saldo_pi_pendente": preflight["saldo_pi"],
            "conferencias_invalidadas": conferencias_invalidadas,
            "hard_delete": False,
        }
        resultado = {
            "sucesso": True, "op_id": int(op_id), "tipo": "RETOMADA_EMBALAGEM_SECUNDARIA",
            "status_op_anterior": op["status"], "status_op_posterior": "Aberta",
            "etapa_destino": "EMBALAGEM_SECUNDARIA", "efeitos": efeitos,
        }
        _auditar(
            cursor, op_id=op_id, tipo="RETOMADA_EMBALAGEM_SECUNDARIA",
            chave=idempotency_key, usuario=usuario, perfil=perfil, motivo=motivo,
            etapa="EMBALAGEM_SECUNDARIA", status_anterior=op["status"],
            status_posterior="Aberta", preflight=preflight, efeitos=efeitos,
            resultado=resultado, ip_origem=ip_origem,
        )
        return resultado


def reabrir_op(op_id, *, usuario, perfil, motivo, etapa_destino, idempotency_key,
               ip_origem=None, confirmacao=False):
    _validar_autorizacao(usuario, perfil, motivo, idempotency_key)
    if etapa_destino not in ETAPAS_REABERTURA:
        raise ValueError("Selecione a etapa operacional de destino.")
    if not confirmacao:
        raise ValueError("Confirme expressamente que a reabertura preservará PI, PA e caixas existentes.")
    criar_tabelas_operacoes_op()
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            return existente
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + _bloqueio_sql()), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        caixas = _caixas_op(cursor, op_id, bloquear=True)
        ativas = [c for c in caixas if str(c["status"] or "").upper() not in STATUS_INATIVOS]
        bloqueios = [] if op["status"] == "Encerrada" else [f"Somente OP Encerrada pode ser reaberta; situação atual: {op['status']}."]
        bloqueios.extend(_bloqueios_reabertura(cursor, op_id, ativas))
        preflight = {"permitido": not bloqueios, "bloqueios": bloqueios, "caixas_ativas": len(ativas)}
        if bloqueios:
            raise ValueError("Reabertura bloqueada: " + " ".join(bloqueios))
        cursor.execute(q("""UPDATE ordens_producao SET status='Aberta',
            versao_operacional=COALESCE(versao_operacional,0)+1
            WHERE id=? AND status='Encerrada'"""), (op_id,))
        if cursor.rowcount != 1:
            raise ValueError("A OP foi alterada concorrentemente; atualize a tela e tente novamente.")
        cursor.execute(q("UPDATE embalagem_secundaria_conferencias SET confirmada=0 WHERE op_id=? AND confirmada=1"), (op_id,))
        conferencias_invalidadas = cursor.rowcount
        invalidar_por_reabertura(op_id, cursor=cursor, usuario=usuario, perfil=perfil, justificativa=motivo)
        efeitos = {
            "pi_preservado": True, "pa_preservado": True, "caixas_preservadas": len(caixas),
            "apontamentos_preservados": True, "conferencias_invalidadas": conferencias_invalidadas,
        }
        resultado = {
            "sucesso": True, "op_id": int(op_id), "tipo": "REABERTURA",
            "status_op_anterior": op["status"], "status_op_posterior": "Aberta",
            "etapa_destino": etapa_destino, "efeitos": efeitos,
        }
        _auditar(cursor, op_id=op_id, tipo="REABERTURA", chave=idempotency_key,
                 usuario=usuario, perfil=perfil, motivo=motivo, etapa=etapa_destino,
                 status_anterior=op["status"], status_posterior="Aberta", preflight=preflight,
                 efeitos=efeitos, resultado=resultado, ip_origem=ip_origem)
        return resultado


def estornar_op_integral(op_id, *, usuario, perfil, motivo, idempotency_key,
                         ip_origem=None, confirmacao=False):
    _validar_autorizacao(usuario, perfil, motivo, idempotency_key)
    if not funcionalidade_estorno_habilitada():
        raise PermissionError("O estorno integral está desativado pela feature flag da Embalagem Secundária.")
    if not confirmacao:
        raise ValueError("Confirme expressamente o estorno integral e seus efeitos em PI, PA e indicadores.")
    criar_tabelas_operacoes_op()
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            return existente
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + _bloqueio_sql()), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        if str(op["status"] or "").upper() in STATUS_INATIVOS:
            raise ValueError(f"A OP já está {op['status']}; nenhuma movimentação foi realizada.")
        caixas = _caixas_op(cursor, op_id, bloquear=True)
        ativas = [c for c in caixas if str(c["status"] or "").upper() not in STATUS_INATIVOS]
        bloqueios = []
        contextos = []
        cursor.execute(q("""SELECT * FROM estoque_produto_intermediario
            WHERE op_id=? AND tipo IN ('ENTRADA_OP','ENTRADA_EMBALAGEM_PRIMARIA') ORDER BY id"""), (op_id,))
        originais_pi = cursor.fetchall()
        if caixas and not originais_pi:
            bloqueios.append("A OP possui caixas, mas o movimento original de entrada de PI não foi encontrado.")
        for caixa in ativas:
            detalhes = _buscar_bloqueios(cursor, caixa)
            if detalhes:
                bloqueios.extend(f"Caixa {caixa['codigo_caixa']}: {item}" for item in detalhes)
                continue
            _, _, composicoes = _carregar_contexto(cursor, op_id, caixa["id"])
            _movimentos_pi_originais(cursor, op_id, caixa["id"], composicoes)
            contextos.append(caixa)
        preflight = {"permitido": not bloqueios, "bloqueios": bloqueios, "caixas_ativas": len(ativas)}
        if bloqueios:
            raise ValueError("Estorno integral bloqueado: " + " ".join(bloqueios))
        antes = _totais_op(cursor, op_id)
        resultados_caixas = []
        for indice, caixa in enumerate(contextos, start=1):
            resultados_caixas.append(_estornar_caixa_cursor(
                cursor, op_id, caixa["id"], usuario, perfil, motivo,
                f"{idempotency_key}:CAIXA:{indice}", ip_origem, ajustar_op=False))
        compensacoes = []
        for movimento in originais_pi:
            chave = f"{idempotency_key}:PI:{movimento['id']}"
            cursor.execute(q("""INSERT INTO estoque_produto_intermediario(
                data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,
                movimento_origem_id,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)"""), (
                _agora()[:10], "SAIDA_ESTORNO_OP", op_id, movimento["sku"],
                str(_decimal(movimento["quantidade_bandejas"])), "Estorno integral da OP",
                f"Compensação do movimento PI #{movimento['id']}.", movimento["id"], chave,
            ))
            compensacoes.append({"movimento_origem_id": movimento["id"], "quantidade": str(_decimal(movimento["quantidade_bandejas"]))})
        cursor.execute(q("""UPDATE apontamentos_producao SET vigente=0,invalidado_em=?,invalidado_por=?
            WHERE op_id=? AND COALESCE(vigente,1)=1 AND (
            observacoes LIKE 'Gerado automaticamente no encerramento da OP%%'
            OR observacoes LIKE 'Produção final informada no encerramento da OP%%'
            OR observacoes LIKE 'Kg final produzido informado no encerramento da OP%%')"""), (_agora(), usuario, op_id))
        apontamentos_invalidados = cursor.rowcount
        cursor.execute(q("UPDATE embalagem_secundaria_conferencias SET confirmada=0 WHERE op_id=? AND confirmada=1"), (op_id,))
        conferencias_invalidadas = cursor.rowcount
        cursor.execute(q("""UPDATE ordens_producao SET status='Estornada',
            versao_operacional=COALESCE(versao_operacional,0)+1
            WHERE id=? AND UPPER(COALESCE(status,'')) NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')"""), (op_id,))
        if cursor.rowcount != 1:
            raise ValueError("A OP foi alterada concorrentemente; o estorno integral foi cancelado.")
        depois = _totais_op(cursor, op_id)
        efeitos = {
            "caixas_estornadas": len(resultados_caixas), "caixas_ja_estornadas_preservadas": len(caixas) - len(ativas),
            "compensacoes_pi": compensacoes, "apontamentos_invalidados": apontamentos_invalidados,
            "conferencias_invalidadas": conferencias_invalidadas, "hard_delete": False,
        }
        resultado = {
            "sucesso": True, "op_id": int(op_id), "tipo": "ESTORNO_INTEGRAL",
            "status_op_anterior": op["status"], "status_op_posterior": "Estornada",
            "totais_antes": antes, "totais_depois": depois,
            "caixas_estornadas": len(resultados_caixas), "efeitos": efeitos,
        }
        _auditar(cursor, op_id=op_id, tipo="ESTORNO_INTEGRAL", chave=idempotency_key,
                 usuario=usuario, perfil=perfil, motivo=motivo, etapa=None,
                 status_anterior=op["status"], status_posterior="Estornada", preflight=preflight,
                 efeitos=efeitos, resultado=resultado, ip_origem=ip_origem)
        return resultado


TIPO_REVERSAO_ESTORNO_OP = "REVERSAO_ESTORNO_OP"
TIPO_PI_REVERSAO_ESTORNO_OP = "ENTRADA_REVERSAO_ESTORNO_OP"
TIPO_REVERSAO_PRIMARIA = "REVERSAO_EMBALAGEM_PRIMARIA"
TIPO_PI_REVERSAO_PRIMARIA = "SAIDA_REVERSAO_EMBALAGEM_PRIMARIA"
_DISPONIBILIDADES_CAIXA_ESTORNADA = {"ESTORNADO", "ESTORNADA", "CANCELADO", "CANCELADA"}


def _compensacoes_estorno_integral(cursor, op_id):
    """Identifica, sem ambiguidade, os movimentos SAIDA_ESTORNO_OP do último estorno integral."""
    bloqueios = []
    cursor.execute(q("""SELECT * FROM op_operacoes_auditoria
        WHERE op_id=? AND tipo='ESTORNO_INTEGRAL' ORDER BY id DESC LIMIT 1"""), (op_id,))
    estorno = cursor.fetchone()
    if not estorno:
        return None, [], ["Não há registro auditado de estorno integral desta OP; a reversão exige o movimento SAIDA_ESTORNO_OP produzido por ele."]
    prefixo = f"{estorno['idempotency_key']}:PI:"
    cursor.execute(q("""SELECT * FROM estoque_produto_intermediario
        WHERE op_id=? AND tipo='SAIDA_ESTORNO_OP' ORDER BY id"""), (op_id,))
    movimentos = [m for m in cursor.fetchall() if str(m["idempotency_key"] or "").startswith(prefixo)]
    try:
        esperados = json.loads(estorno["efeitos_json"]).get("compensacoes_pi") or []
    except (TypeError, ValueError):
        esperados = []
    if not movimentos:
        bloqueios.append("O movimento SAIDA_ESTORNO_OP do estorno integral não foi encontrado.")
    elif len(movimentos) != len(esperados) or sorted(
        (int(m["movimento_origem_id"] or 0), str(_decimal(m["quantidade_bandejas"]))) for m in movimentos
    ) != sorted((int(e["movimento_origem_id"]), str(_decimal(e["quantidade"]))) for e in esperados):
        bloqueios.append("Os movimentos SAIDA_ESTORNO_OP divergem da auditoria do estorno integral; identificação ambígua.")
    for movimento in movimentos:
        if not movimento["movimento_origem_id"]:
            bloqueios.append(f"O movimento SAIDA_ESTORNO_OP #{movimento['id']} não referencia o movimento original de PI.")
        cursor.execute(q("""SELECT id FROM estoque_produto_intermediario
            WHERE tipo=? AND movimento_origem_id=?"""), (TIPO_PI_REVERSAO_ESTORNO_OP, movimento["id"]))
        previa = cursor.fetchone()
        if previa:
            bloqueios.append(f"O movimento SAIDA_ESTORNO_OP #{movimento['id']} já foi compensado pelo movimento #{previa['id']}.")
    return estorno, movimentos, bloqueios


def _preflight_reversao_estorno_cursor(cursor, op, *, bloquear=False):
    op_id = int(op["id"])
    bloqueios = []
    status = str(op["status"] or "")
    if status.upper() not in {"ESTORNADA", "ESTORNADO"}:
        bloqueios.append(f"Somente OP Estornada pode ter o estorno revertido; situação atual: {status or 'não informada'}.")
    caixas = _caixas_op(cursor, op_id, bloquear=bloquear)
    saldo_pi, _ = _saldo_pi_op(cursor, op_id, bloquear=bloquear)
    if saldo_pi != 0:
        bloqueios.append(f"O saldo líquido atual de PI da OP é {saldo_pi:f} e deveria ser zero.")
    estorno, movimentos, bloqueios_mov = _compensacoes_estorno_integral(cursor, op_id)
    bloqueios.extend(bloqueios_mov)
    dados = _dados_bloqueios_caixas(cursor, caixas)
    for caixa in caixas:
        caixa_id = int(caixa["id"])
        codigo = caixa["codigo_caixa"]
        if str(caixa["status"] or "").upper() not in STATUS_INATIVOS:
            bloqueios.append(f"Caixa {codigo}: não está estornada (situação {caixa['status']}).")
        if int(caixa["estoque_operacional"] or 0) == 1:
            bloqueios.append(f"Caixa {codigo}: possui estoque operacional ativo.")
        disponibilidade = str(caixa["disponibilidade"] or "").upper()
        if disponibilidade not in _DISPONIBILIDADES_CAIXA_ESTORNADA:
            bloqueios.append(f"Caixa {codigo}: disponibilidade {disponibilidade or 'não informada'}.")
        if caixa["reservado_expedicao_id"] or _decimal(caixa["quantidade_pacotes_reservados"]) > 0:
            bloqueios.append(f"Caixa {codigo}: possui reserva ativa.")
        for item in dados["expedicoes"].get(caixa_id, []):
            bloqueios.append(f"Caixa {codigo}: vinculada ao Romaneio nº {item['numero_romaneio']} ({item['status']}).")
        for item in dados["eventos"].get(caixa_id, []):
            descricao = "movimentação de PA posterior" if item["fonte"] == "pa_movimentacoes_fallback" else "evento de estoque posterior"
            bloqueios.append(f"Caixa {codigo}: {descricao} {item['tipo']}.")
        for item in dados["pncs"].get(caixa_id, []):
            bloqueios.append(f"Caixa {codigo}: vinculada ao Produto Não Conforme nº {item['id']} ({item['status']}).")
    quantidade = sum((_decimal(m["quantidade_bandejas"]) for m in movimentos), Decimal("0"))
    return {
        "op_id": op_id, "tipo": TIPO_REVERSAO_ESTORNO_OP, "status_atual": status,
        "permitido": not bloqueios, "bloqueios": list(dict.fromkeys(bloqueios)),
        "versao_operacional": int(op["versao_operacional"] or 0) if "versao_operacional" in op.keys() else 0,
        "caixas_historicas": len(caixas), "pi_a_restaurar": str(quantidade),
        "movimentos_compensar": [int(m["id"]) for m in movimentos],
        "estorno_auditoria_id": int(estorno["id"]) if estorno else None,
    }


def preflight_reversao_estorno_op(op_id):
    """Consulta somente leitura das condições para reverter o estorno integral."""
    criar_tabelas_operacoes_op()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        return _preflight_reversao_estorno_cursor(cursor, op)
    finally:
        conn.close()


def reverter_estorno_op(op_id, *, usuario, perfil, motivo, idempotency_key,
                        versao_esperada=None, ip_origem=None, confirmacao=False):
    """Restaura o PI estornado por compensação e reabre a OP, sem tocar no histórico."""
    _validar_autorizacao(usuario, perfil, motivo, idempotency_key)
    if not confirmacao:
        raise ValueError("Confirme expressamente a reversão do estorno e a restauração do PI.")
    criar_tabelas_operacoes_op()
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            if existente.get("tipo") != TIPO_REVERSAO_ESTORNO_OP:
                raise ValueError("A chave de idempotência já foi usada por outra operação.")
            return existente
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + _bloqueio_sql()), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        versao_anterior = int(op["versao_operacional"] or 0)
        if versao_esperada not in (None, "") and int(versao_esperada) != versao_anterior:
            raise ValueError("A OP foi alterada por outra solicitação; atualize a tela e tente novamente.")
        preflight = _preflight_reversao_estorno_cursor(cursor, op, bloquear=True)
        if not preflight["permitido"]:
            raise ValueError("Reversão do estorno bloqueada: " + " ".join(preflight["bloqueios"]))
        ids = preflight["movimentos_compensar"]
        cursor.execute(q("SELECT * FROM estoque_produto_intermediario WHERE id IN ({}) ORDER BY id".format(
            ",".join("?" for _ in ids))), ids)
        compensados = cursor.fetchall()
        novos = []
        for movimento in compensados:
            cursor.execute(q("""INSERT INTO estoque_produto_intermediario(
                data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,
                movimento_origem_id,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?)"""), (
                _agora()[:10], TIPO_PI_REVERSAO_ESTORNO_OP, op_id, movimento["sku"],
                str(_decimal(movimento["quantidade_bandejas"])), "Reversão do estorno integral da OP",
                f"Compensação do movimento SAIDA_ESTORNO_OP #{movimento['id']}.",
                movimento["id"], f"{idempotency_key}:PI:{movimento['id']}",
            ))
            novos.append({
                "movimento_compensado_id": int(movimento["id"]),
                "quantidade": str(_decimal(movimento["quantidade_bandejas"])),
            })
        cursor.execute(q("""UPDATE ordens_producao SET status='Aberta',
            versao_operacional=COALESCE(versao_operacional,0)+1
            WHERE id=? AND UPPER(COALESCE(status,'')) IN ('ESTORNADA','ESTORNADO')
              AND COALESCE(versao_operacional,0)=?"""), (op_id, versao_anterior))
        if cursor.rowcount != 1:
            raise ValueError("A OP foi alterada concorrentemente; a reversão do estorno foi cancelada.")
        cursor.execute(q("UPDATE embalagem_secundaria_conferencias SET confirmada=0 WHERE op_id=? AND confirmada=1"), (op_id,))
        conferencias_invalidadas = cursor.rowcount
        saldo_depois, _ = _saldo_pi_op(cursor, op_id)
        if saldo_depois != _decimal(preflight["pi_a_restaurar"]):
            raise RuntimeError("Saldo de PI após a reversão diverge do esperado; operação cancelada.")
        efeitos = {
            "versao_anterior": versao_anterior, "versao_nova": versao_anterior + 1,
            "movimentos_saida_estorno_compensados": ids,
            "compensacoes_pi": novos, "pi_restaurado": preflight["pi_a_restaurar"],
            "saldo_pi_posterior": str(saldo_depois),
            "caixas_historicas_preservadas": preflight["caixas_historicas"],
            "conferencias_invalidadas": conferencias_invalidadas, "hard_delete": False,
        }
        resultado = {
            "sucesso": True, "op_id": int(op_id), "tipo": TIPO_REVERSAO_ESTORNO_OP,
            "status_op_anterior": op["status"], "status_op_posterior": "Aberta",
            "etapa_destino": "EMBALAGEM_SECUNDARIA", "efeitos": efeitos,
        }
        _auditar(cursor, op_id=op_id, tipo=TIPO_REVERSAO_ESTORNO_OP, chave=idempotency_key,
                 usuario=usuario, perfil=perfil, motivo=motivo, etapa="EMBALAGEM_SECUNDARIA",
                 status_anterior=op["status"], status_posterior="Aberta", preflight=preflight,
                 efeitos=efeitos, resultado=resultado, ip_origem=ip_origem)
        return resultado


def _preflight_reversao_primaria_cursor(cursor, op, *, bloquear=False):
    op_id = int(op["id"])
    bloqueio = _bloqueio_sql() if bloquear else ""
    cursor.execute(q("""SELECT * FROM embalagem_primaria_apontamentos
        WHERE op_id=? AND COALESCE(vigente,1)=1 ORDER BY id DESC""" + bloqueio), (op_id,))
    ativos = cursor.fetchall()
    bloqueios = []
    if not ativos:
        return {
            "op_id": op_id, "tipo": TIPO_REVERSAO_PRIMARIA, "permitido": False,
            "bloqueios": ["Não há apontamento ativo de Embalagem Primária para reverter."],
            "versao_operacional": int(op["versao_operacional"] or 0),
        }
    apontamento = ativos[0]
    if str(op["status"] or "") not in {"Aberta", "Aguardando Embalagem Secundária"}:
        bloqueios.append(f"A OP está em situação {op['status']} e não permite esta reversão.")
    if bloquear and DATABASE_URL:
        cursor.execute(q("SELECT id FROM estoque_produto_intermediario WHERE op_id=? ORDER BY id FOR UPDATE"), (op_id,))
        cursor.fetchall()
    cursor.execute(q("""SELECT * FROM estoque_produto_intermediario
        WHERE op_id=? AND tipo='ENTRADA_EMBALAGEM_PRIMARIA'
          AND (apontamento_origem_id=? OR (
            apontamento_origem_id IS NULL AND sku=? AND quantidade_bandejas=? AND criado_em=?))
        ORDER BY id"""), (
            op_id, apontamento["id"], apontamento["sku"],
            apontamento["quantidade_bandejas"], apontamento["criado_em"],
        ))
    movimentos = cursor.fetchall()
    total_movimentos = sum((_decimal(item["quantidade_bandejas"]) for item in movimentos), Decimal("0"))
    if not movimentos or total_movimentos != _decimal(apontamento["quantidade_bandejas"]):
        bloqueios.append("O vínculo entre o apontamento e os movimentos de PI não é inequívoco.")
    ids = [int(item["id"]) for item in movimentos]
    if ids:
        marcas = ",".join("?" for _ in ids)
        cursor.execute(q(f"""SELECT COUNT(*) total FROM estoque_produto_intermediario
            WHERE tipo=? AND movimento_origem_id IN ({marcas})"""),
            [TIPO_PI_REVERSAO_PRIMARIA, *ids])
        if int(cursor.fetchone()["total"] or 0):
            bloqueios.append("O apontamento já possui movimento compensatório de reversão.")
    cursor.execute(q("""SELECT COUNT(*) total FROM estoque_produto_intermediario saida
        WHERE saida.op_id=? AND saida.tipo='SAIDA_EMBALAGEM_SECUNDARIA'
          AND saida.criado_em>=? AND NOT EXISTS (
            SELECT 1 FROM estoque_produto_intermediario retorno
            WHERE retorno.tipo='ENTRADA_ESTORNO_CAIXA'
              AND retorno.movimento_origem_id=saida.id)
        """), (op_id, apontamento["criado_em"]))
    if int(cursor.fetchone()["total"] or 0):
        bloqueios.append("O PI do apontamento já foi consumido por PA e não foi integralmente estornado.")
    cursor.execute(q("""SELECT COUNT(DISTINCT cx.id) total FROM pa_caixas cx
        JOIN pa_caixa_composicao comp ON comp.caixa_id=cx.id
        WHERE comp.op_id=? AND cx.criado_em>=?
          AND UPPER(COALESCE(cx.status,'')) NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')"""),
        (op_id, apontamento["criado_em"]))
    if int(cursor.fetchone()["total"] or 0):
        bloqueios.append("Há caixa PA ativa formada após o apontamento.")
    saldo, _ = _saldo_pi_op(cursor, op_id)
    if saldo < total_movimentos:
        bloqueios.append(
            f"O saldo PI atual ({saldo:g}) é inferior ao PI do apontamento ({total_movimentos:g})."
        )
    return {
        "op_id": op_id, "tipo": TIPO_REVERSAO_PRIMARIA,
        "permitido": not bloqueios, "bloqueios": list(dict.fromkeys(bloqueios)),
        "apontamento_id": int(apontamento["id"]),
        "quantidade": str(_decimal(apontamento["quantidade_bandejas"])),
        "movimentos": ids, "saldo_pi": str(saldo),
        "versao_operacional": int(op["versao_operacional"] or 0),
    }


def preflight_reversao_apontamento_primaria(op_id):
    from modules.expedicao.services import criar_tabelas_estoque_pi_pa
    criar_tabelas_estoque_pi_pa()
    criar_tabelas_operacoes_op()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        return _preflight_reversao_primaria_cursor(cursor, op)
    finally:
        conn.close()


def reverter_apontamento_embalagem_primaria(
    op_id, *, motivo, usuario, perfil, idempotency_key,
    versao_esperada=None, ip_origem=None, confirmacao=False,
):
    _validar_autorizacao(usuario, perfil, motivo, idempotency_key)
    if not confirmacao:
        raise ValueError("Confirme expressamente a reversão do apontamento da Embalagem Primária.")
    from modules.expedicao.services import criar_tabelas_estoque_pi_pa
    criar_tabelas_estoque_pi_pa()
    criar_tabelas_operacoes_op()
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            if existente.get("tipo") != TIPO_REVERSAO_PRIMARIA:
                raise ValueError("A chave de idempotência já foi usada por outra operação.")
            return existente
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + _bloqueio_sql()), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        versao_anterior = int(op["versao_operacional"] or 0)
        if versao_esperada not in (None, "") and int(versao_esperada) != versao_anterior:
            raise ValueError("A OP foi alterada por outra solicitação; atualize a tela e tente novamente.")
        preflight = _preflight_reversao_primaria_cursor(cursor, op, bloquear=True)
        if not preflight["permitido"]:
            raise ValueError("Reversão do apontamento bloqueada: " + " ".join(preflight["bloqueios"]))
        novos = []
        for movimento_id in preflight["movimentos"]:
            cursor.execute(q("SELECT * FROM estoque_produto_intermediario WHERE id=?"), (movimento_id,))
            movimento = cursor.fetchone()
            cursor.execute(q("""INSERT INTO estoque_produto_intermediario(
                data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,
                movimento_origem_id,idempotency_key,apontamento_origem_id)
                VALUES(?,?,?,?,?,?,?,?,?,?)"""), (
                _agora()[:10], TIPO_PI_REVERSAO_PRIMARIA, op_id, movimento["sku"],
                str(_decimal(movimento["quantidade_bandejas"])),
                "Reversão da Embalagem Primária",
                f"Compensação do movimento PI #{movimento_id}.", movimento_id,
                f"{idempotency_key}:PI:{movimento_id}", preflight["apontamento_id"],
            ))
            novos.append({"movimento_origem_id": movimento_id, "quantidade": str(_decimal(movimento["quantidade_bandejas"]))})
        cursor.execute(q("""UPDATE embalagem_primaria_apontamentos
            SET vigente=0,invalidado_em=?,invalidado_por=?,invalidacao_motivo=?
            WHERE id=? AND COALESCE(vigente,1)=1"""),
            (_agora(), usuario, str(motivo).strip(), preflight["apontamento_id"]))
        if cursor.rowcount != 1:
            raise ValueError("O apontamento foi alterado concorrentemente; a reversão foi cancelada.")
        cursor.execute(q("""UPDATE ordens_producao SET status='Aberta',
            versao_operacional=COALESCE(versao_operacional,0)+1
            WHERE id=? AND COALESCE(versao_operacional,0)=?"""), (op_id, versao_anterior))
        if cursor.rowcount != 1:
            raise ValueError("A OP foi alterada concorrentemente; a reversão foi cancelada.")
        cursor.execute(q("UPDATE embalagem_secundaria_conferencias SET confirmada=0 WHERE op_id=? AND confirmada=1"), (op_id,))
        saldo_depois, _ = _saldo_pi_op(cursor, op_id)
        efeitos = {
            "apontamento_invalidado_id": preflight["apontamento_id"],
            "compensacoes_pi": novos, "saldo_pi_posterior": str(saldo_depois),
            "versao_anterior": versao_anterior, "versao_nova": versao_anterior + 1,
            "hard_delete": False,
        }
        resultado = {
            "sucesso": True, "op_id": int(op_id), "tipo": TIPO_REVERSAO_PRIMARIA,
            "status_op_anterior": op["status"], "status_op_posterior": "Aberta",
            "etapa_destino": "EMBALAGEM_PRIMARIA", "efeitos": efeitos,
        }
        _auditar(cursor, op_id=op_id, tipo=TIPO_REVERSAO_PRIMARIA, chave=idempotency_key,
                 usuario=usuario, perfil=perfil, motivo=motivo, etapa="EMBALAGEM_PRIMARIA",
                 status_anterior=op["status"], status_posterior="Aberta", preflight=preflight,
                 efeitos=efeitos, resultado=resultado, ip_origem=ip_origem)
        return resultado


def historico_operacoes_op(op_id):
    criar_tabelas_operacoes_op()
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM op_operacoes_auditoria WHERE op_id=? ORDER BY id DESC"), (op_id,))
        eventos = [dict(item) for item in cursor.fetchall()]
        cursor.execute(q("""SELECT usuario,perfil,confirmado_em FROM embalagem_secundaria_conferencias
            WHERE op_id=? ORDER BY id DESC"""), (op_id,))
        eventos.extend({
            "tipo": "ENCERRAMENTO_CONFERIDO", "status_anterior": "Aberta",
            "status_posterior": "Encerrada", "usuario": item["usuario"],
            "perfil": item["perfil"], "motivo": "Conferência final da Embalagem Secundária",
            "criado_em": item["confirmado_em"],
        } for item in cursor.fetchall())
        cursor.execute(q("""SELECT tipo,usuario,perfil,justificativa,status_anterior,status_posterior,criado_em
            FROM embalagem_secundaria_estornos WHERE op_id=? ORDER BY id DESC"""), (op_id,))
        eventos.extend({
            "tipo": f"ESTORNO_{item['tipo']}", "status_anterior": item["status_anterior"],
            "status_posterior": item["status_posterior"], "usuario": item["usuario"],
            "perfil": item["perfil"], "motivo": item["justificativa"], "criado_em": item["criado_em"],
        } for item in cursor.fetchall())
        return sorted(eventos, key=lambda item: (str(item.get("criado_em") or ""), str(item.get("tipo") or "")), reverse=True)
    finally:
        conn.close()
