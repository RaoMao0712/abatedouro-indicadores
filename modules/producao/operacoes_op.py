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


def _bloqueios_reabertura(cursor, op_id, caixas):
    bloqueios = []
    for caixa in caixas:
        caixa_id = caixa["id"]
        cursor.execute(q("SELECT COUNT(DISTINCT op_id) total FROM pa_caixa_composicao WHERE caixa_id=?"), (caixa_id,))
        if int(cursor.fetchone()["total"] or 0) > 1:
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: composição mista com outra OP.")
        cursor.execute(q("""SELECT e.numero_romaneio,e.status FROM expedicao_itens i
            JOIN expedicoes e ON e.id=i.expedicao_id WHERE i.caixa_id=? ORDER BY e.id"""), (caixa_id,))
        for item in cursor.fetchall():
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: Romaneio nº {item['numero_romaneio']} ({item['status']}).")
        cursor.execute(q("SELECT tipo FROM pa_movimentacoes WHERE caixa_id=? ORDER BY id"), (caixa_id,))
        for item in cursor.fetchall():
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: movimentação posterior {item['tipo']}.")
        cursor.execute(q("""SELECT acao FROM estoque_eventos WHERE caixa_id=?
            AND acao NOT IN ('FORMACAO_ESTOQUE','ESTORNO_CAIXA_EMBALAGEM') ORDER BY id"""), (caixa_id,))
        for item in cursor.fetchall():
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: evento sucessor {item['acao']}.")
        if caixa["reservado_expedicao_id"] or _decimal(caixa["quantidade_pacotes_reservados"]) > 0:
            bloqueios.append(f"Caixa {caixa['codigo_caixa']}: reserva operacional ativa.")
        cursor.execute(q("""SELECT id,status,COALESCE(saldo_destinado_g,0) saldo_destinado_g
            FROM pa_nao_conformes WHERE caixa_id=? ORDER BY id"""), (caixa_id,))
        for pnc in cursor.fetchall():
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
            for caixa in ativas:
                for detalhe in _buscar_bloqueios(cursor, caixa):
                    bloqueios.append(f"Caixa {caixa['codigo_caixa']}: {detalhe}")
                try:
                    cursor.execute(q("SELECT * FROM pa_caixa_composicao WHERE caixa_id=? ORDER BY id"), (caixa["id"],))
                    composicoes = cursor.fetchall()
                    ops = {int(item["op_id"]) for item in composicoes}
                    if ops != {int(op_id)}:
                        raise ValueError("A caixa possui composição ausente ou vinculada a múltiplas OPs.")
                    _movimentos_pi_originais(cursor, op_id, caixa["id"], composicoes)
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
