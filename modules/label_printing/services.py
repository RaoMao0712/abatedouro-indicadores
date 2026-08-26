"""Fila P3.2. Nunca envia dados diretamente a uma impressora."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import secrets
import uuid

from flask import current_app, has_app_context

from database import DATABASE_URL, conectar, q, transaction


TIPO_ETIQUETA_CAIXA = "CAIXA_PA"
ESTADOS_PENDENTES = ("PENDENTE", "EM_PROCESSAMENTO", "FALHA_TEMPORARIA")
ESTADOS_FINAIS = ("ENVIADA_IMPRESSORA", "CONFERENCIA_NECESSARIA", "FALHA_PERMANENTE", "INVALIDADA")
VARIAVEIS_CENTRAIS = {
    "fabricacao": "data_fabricacao",
    "validade": "data_validade",
    "lote": "codigo_caixa",
    "pecas": "quantidade_bandejas",
    "peso_bruto": "peso_bruto",
    "tara": "peso_tara",
    "peso_liquido": "peso_liquido",
}


def _agora():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _data_utc(valor):
    data = valor if isinstance(valor, datetime) else datetime.fromisoformat(str(valor))
    return data.replace(tzinfo=timezone.utc) if data.tzinfo is None else data.astimezone(timezone.utc)


def _decimal(valor):
    try:
        return Decimal(str(valor or 0))
    except (InvalidOperation, ValueError):
        raise ValueError("Peso ou quantidade persistida inválida para a etiqueta.")


def _decimal_texto(valor):
    return format(_decimal(valor), "f")


def _flag(nome):
    return bool(has_app_context() and current_app.config.get(nome, False))


def criar_tabelas_impressao_etiquetas():
    conn = conectar()
    cursor = conn.cursor()
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS label_model_configs (
        id {pk}, sku TEXT NOT NULL, apresentacao TEXT NOT NULL, label_type TEXT NOT NULL,
        template_path TEXT NOT NULL, template_sha256 TEXT NOT NULL, printer_allowlist TEXT NOT NULL,
        variable_map_json TEXT NOT NULL, pieces_source TEXT NOT NULL,
        ativo INTEGER NOT NULL DEFAULT 0, criado_em {timestamp} NOT NULL,
        UNIQUE(sku, apresentacao, label_type))""")
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS local_print_agents (
        id {pk}, agent_uuid TEXT NOT NULL UNIQUE, nome TEXT NOT NULL, station_code TEXT NOT NULL,
        token_hash TEXT, pairing_code_hash TEXT, pairing_expires_at {timestamp},
        printer_name TEXT, printer_model TEXT, nicelabel_version TEXT, agent_version TEXT,
        status TEXT NOT NULL DEFAULT 'NAO_PAREADO', auto_print_enabled INTEGER NOT NULL DEFAULT 0, last_seen_at {timestamp},
        criado_em {timestamp} NOT NULL)""")
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS label_print_jobs (
        id {pk}, job_uuid TEXT NOT NULL UNIQUE, caixa_id INTEGER NOT NULL, label_type TEXT NOT NULL,
        op_id INTEGER, product TEXT NOT NULL, presentation TEXT NOT NULL,
        generation INTEGER NOT NULL DEFAULT 1, original_job_id INTEGER,
        model_config_id INTEGER NOT NULL, agent_id INTEGER,
        state TEXT NOT NULL, snapshot_json TEXT NOT NULL, template_sha256 TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, lease_token_hash TEXT, lease_expires_at {timestamp},
        idempotency_key TEXT NOT NULL, justification TEXT, requested_by TEXT, created_at {timestamp} NOT NULL,
        updated_at {timestamp} NOT NULL, reserved_at {timestamp}, sent_at {timestamp}, confirmed_at {timestamp}, invalidated_at {timestamp},
        error_code TEXT, error_message TEXT, spool_reference TEXT,
        box_reversed INTEGER NOT NULL DEFAULT 0,
        UNIQUE(caixa_id, label_type, generation))""")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_label_jobs_state ON label_print_jobs(state, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_label_jobs_caixa ON label_print_jobs(caixa_id, created_at)")
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS label_print_audit_events (
        id {pk}, entity_type TEXT NOT NULL, entity_uuid TEXT NOT NULL, action TEXT NOT NULL,
        actor TEXT, details_json TEXT NOT NULL, created_at {timestamp} NOT NULL)""")
    conn.commit()
    conn.close()


def _carregar_modelo(cursor, sku, apresentacao):
    cursor.execute(q("""SELECT * FROM label_model_configs
        WHERE sku=? AND apresentacao=? AND label_type=? AND ativo=1"""),
        (sku, apresentacao, TIPO_ETIQUETA_CAIXA))
    return cursor.fetchone()


def _auditar(cursor, entidade, identificador, acao, *, ator=None, detalhes=None):
    cursor.execute(q("""INSERT INTO label_print_audit_events(
        entity_type,entity_uuid,action,actor,details_json,created_at) VALUES(?,?,?,?,?,?)"""),
        (entidade, str(identificador), acao, ator,
         json.dumps(detalhes or {}, ensure_ascii=False, sort_keys=True), _agora()))


def _snapshot_caixa(cursor, caixa_id):
    cursor.execute(q("SELECT * FROM pa_caixas WHERE id=?"), (caixa_id,))
    caixa = cursor.fetchone()
    if not caixa:
        raise ValueError("Caixa persistida não encontrada para gerar a etiqueta.")
    bruto = _decimal(caixa["peso_bruto"])
    liquido = _decimal(caixa["peso_liquido"])
    tara = _decimal(caixa["peso_tara"])
    if bruto != liquido + tara:
        raise ValueError("Pesos persistidos incoerentes: bruto deve ser igual a líquido mais tara.")
    pecas = _decimal(caixa["quantidade_bandejas"])
    if pecas != pecas.to_integral_value() or pecas <= 0:
        raise ValueError("A quantidade persistida de bandejas não é válida como peças.")
    codigo = str(caixa["codigo_caixa"] or "").strip()
    if not codigo:
        raise ValueError("A caixa não possui lote físico oficial persistido.")
    sku = str(caixa["sku"] or "").strip()
    cursor.execute(q("SELECT DISTINCT op_id FROM pa_caixa_composicao WHERE caixa_id=? ORDER BY op_id"), (caixa_id,))
    op_ids = [int(item["op_id"]) for item in cursor.fetchall()]
    return {
        "schema_version": "1", "caixa_id": int(caixa["id"]), "codigo_caixa": codigo,
        "op_id": op_ids[0] if len(op_ids) == 1 else None, "op_ids": op_ids,
        "product": sku, "product_id": None, "sku": sku, "apresentacao": sku,
        "data_fabricacao": str(caixa["data_fabricacao"] or ""),
        "data_validade": str(caixa["data_validade"] or ""),
        "quantidade_bandejas": _decimal_texto(pecas), "peso_bruto": _decimal_texto(bruto),
        "peso_tara": _decimal_texto(tara), "peso_liquido": _decimal_texto(liquido),
    }


def criar_job_caixa_cursor(cursor, caixa_id, *, solicitado_por=None):
    """Cria o job na mesma transação da caixa, somente quando a automação está habilitada."""
    if not (_flag("LABEL_PRINTING_ENABLED") and _flag("BOX_LABEL_AUTO_PRINT_ENABLED")):
        return None
    snapshot = _snapshot_caixa(cursor, caixa_id)
    modelo = _carregar_modelo(cursor, snapshot["sku"], snapshot["apresentacao"])
    if not modelo:
        return None
    if str(modelo["pieces_source"]) != "quantidade_bandejas":
        raise ValueError("O modelo não possui equivalência validada entre bandejas e peças.")
    snapshot["template_sha256"] = str(modelo["template_sha256"])
    agora = _agora()
    job_uuid = str(uuid.uuid4())
    cursor.execute(q("""INSERT INTO label_print_jobs(
        job_uuid,caixa_id,label_type,op_id,product,presentation,generation,model_config_id,state,snapshot_json,
        template_sha256,idempotency_key,requested_by,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""), (job_uuid, caixa_id, TIPO_ETIQUETA_CAIXA,
        snapshot["op_id"], snapshot["product"], snapshot["apresentacao"], 1,
        modelo["id"], "PENDENTE", json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
        modelo["template_sha256"], f"{caixa_id}:{TIPO_ETIQUETA_CAIXA}:1", solicitado_por, agora, agora))
    _auditar(cursor, "JOB", job_uuid, "CRIADO", ator=solicitado_por,
             detalhes={"caixa_id": caixa_id, "generation": 1})
    return job_uuid


def listar_jobs_caixas(caixa_ids):
    ids = [int(i) for i in caixa_ids]
    if not ids:
        return {}
    conn = conectar(); cursor = conn.cursor()
    marcadores = ",".join("?" for _ in ids)
    cursor.execute(q(f"SELECT * FROM label_print_jobs WHERE caixa_id IN ({marcadores}) ORDER BY id"), ids)
    resultado = {}
    for item in cursor.fetchall():
        resultado.setdefault(int(item["caixa_id"]), []).append(dict(item))
    conn.close()
    return resultado


def invalidar_jobs_caixa_cursor(cursor, caixa_id, *, motivo="CAIXA_ESTORNADA"):
    agora = _agora()
    try:
        cursor.execute(q("""UPDATE label_print_jobs SET state='INVALIDADA',invalidated_at=?,
            updated_at=?,error_code=? WHERE caixa_id=? AND state IN ('PENDENTE','EM_PROCESSAMENTO','FALHA_TEMPORARIA')"""),
            (agora, agora, motivo, caixa_id))
    except Exception as erro:
        # Compatibilidade durante rollout: o estoque não pode depender da fila
        # antes de a migration aditiva existir. Demais erros continuam fatais.
        mensagem = str(erro).lower()
        if "no such table" in mensagem or "does not exist" in mensagem or "undefinedtable" in type(erro).__name__.lower():
            return
        raise
    cursor.execute(q("""UPDATE label_print_jobs SET box_reversed=1,updated_at=?
        WHERE caixa_id=? AND state NOT IN ('PENDENTE','EM_PROCESSAMENTO','FALHA_TEMPORARIA')"""),
        (agora, caixa_id))
    _auditar(cursor, "BOX", caixa_id, "JOBS_INVALIDADOS_POR_ESTORNO", detalhes={"motivo": motivo})


def solicitar_reimpressao(caixa_id, *, usuario, justificativa):
    justificativa = str(justificativa or "").strip()
    if len(justificativa) < 10:
        raise ValueError("Informe uma justificativa de reimpressão com ao menos 10 caracteres.")
    if not _flag("LABEL_PRINTING_ENABLED"):
        raise ValueError("Impressão de etiquetas está desabilitada.")
    with transaction() as conn:
        cursor = conn.cursor(); snapshot = _snapshot_caixa(cursor, caixa_id)
        cursor.execute(q("""SELECT * FROM label_print_jobs WHERE caixa_id=? AND label_type=?
            ORDER BY generation DESC LIMIT 1"""), (caixa_id, TIPO_ETIQUETA_CAIXA))
        original = cursor.fetchone()
        if not original:
            raise ValueError("A caixa não possui job original de etiqueta.")
        modelo = _carregar_modelo(cursor, snapshot["sku"], snapshot["apresentacao"])
        if not modelo:
            raise ValueError("Não existe modelo ativo compatível com a caixa.")
        snapshot["template_sha256"] = str(modelo["template_sha256"])
        geracao = int(original["generation"]) + 1; agora = _agora(); job_uuid = str(uuid.uuid4())
        cursor.execute(q("""INSERT INTO label_print_jobs(job_uuid,caixa_id,label_type,generation,
            op_id,product,presentation,original_job_id,model_config_id,state,snapshot_json,template_sha256,
            idempotency_key,justification,requested_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
            (job_uuid, caixa_id, TIPO_ETIQUETA_CAIXA, geracao, snapshot["op_id"], snapshot["product"],
             snapshot["apresentacao"], original["id"], modelo["id"],
             "PENDENTE", json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
             modelo["template_sha256"], f"{caixa_id}:{TIPO_ETIQUETA_CAIXA}:{geracao}", justificativa, usuario, agora, agora))
        _auditar(cursor, "JOB", job_uuid, "REIMPRESSAO_SOLICITADA", ator=usuario,
                 detalhes={"original_job_uuid": original["job_uuid"], "justificativa": justificativa})
        return job_uuid


def criar_codigo_pareamento(agent_uuid, nome, station_code):
    if not _flag("LOCAL_PRINT_AGENT_ENABLED"):
        raise ValueError("Agente local está desabilitado.")
    codigo = f"{secrets.randbelow(1000000):06d}"; agora = datetime.now(timezone.utc)
    with transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(q("""INSERT INTO local_print_agents(agent_uuid,nome,station_code,
            pairing_code_hash,pairing_expires_at,status,criado_em) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(agent_uuid) DO UPDATE SET nome=excluded.nome,station_code=excluded.station_code,
            pairing_code_hash=excluded.pairing_code_hash,pairing_expires_at=excluded.pairing_expires_at,
            status='AGUARDANDO_PAREAMENTO'"""), (agent_uuid, nome, station_code,
            hashlib.sha256(codigo.encode()).hexdigest(), (agora + timedelta(minutes=10)).replace(microsecond=0).isoformat(),
            "AGUARDANDO_PAREAMENTO", agora.replace(microsecond=0).isoformat()))
        _auditar(cursor, "AGENT", agent_uuid, "CODIGO_PAREAMENTO_CRIADO")
    return codigo


def parear_agente(agent_uuid, codigo, *, agent_version=None):
    if not _flag("LOCAL_PRINT_AGENT_ENABLED"):
        raise ValueError("Agente local está desabilitado.")
    token = secrets.token_urlsafe(32); token_hash = hashlib.sha256(token.encode()).hexdigest()
    with transaction() as conn:
        cursor = conn.cursor(); cursor.execute(q("SELECT * FROM local_print_agents WHERE agent_uuid=?"), (agent_uuid,))
        agente = cursor.fetchone()
        if not agente or not hmac.compare_digest(str(agente["pairing_code_hash"] or ""), hashlib.sha256(str(codigo).encode()).hexdigest()):
            raise ValueError("Código de pareamento inválido.")
        if _data_utc(agente["pairing_expires_at"]) < datetime.now(timezone.utc):
            raise ValueError("Código de pareamento expirado.")
        cursor.execute(q("""UPDATE local_print_agents SET token_hash=?,pairing_code_hash=NULL,
            pairing_expires_at=NULL,status='ATIVO',auto_print_enabled=0,agent_version=?,last_seen_at=? WHERE id=?"""),
            (token_hash, agent_version, _agora(), agente["id"]))
        _auditar(cursor, "AGENT", agent_uuid, "PAREADO")
    return token


def autenticar_agente(token):
    if not (_flag("LABEL_PRINTING_ENABLED") and _flag("LOCAL_PRINT_AGENT_ENABLED")):
        return None
    token_hash = hashlib.sha256(str(token or "").encode()).hexdigest()
    conn = conectar(); cursor = conn.cursor(); cursor.execute(q("SELECT * FROM local_print_agents WHERE token_hash=? AND status='ATIVO'"), (token_hash,))
    agente = cursor.fetchone(); conn.close(); return dict(agente) if agente else None


def registrar_heartbeat(agent_id, diagnostico=None):
    with transaction() as conn:
        cursor = conn.cursor(); agora = _agora()
        cursor.execute(q("UPDATE local_print_agents SET last_seen_at=? WHERE id=? AND status='ATIVO'"), (agora, agent_id))
        if cursor.rowcount != 1:
            raise ValueError("Agente não encontrado.")
        _auditar(cursor, "AGENT", agent_id, "HEARTBEAT", detalhes=diagnostico or {})


def configurar_impressao_agente(agent_uuid, habilitada, *, usuario):
    with transaction() as conn:
        cursor = conn.cursor(); cursor.execute(q("""UPDATE local_print_agents SET auto_print_enabled=?
            WHERE agent_uuid=? AND status='ATIVO'"""), (1 if habilitada else 0, agent_uuid))
        if cursor.rowcount != 1:
            raise ValueError("Agente ativo não encontrado.")
        _auditar(cursor, "AGENT", agent_uuid, "IMPRESSAO_AUTOMATICA_CONFIGURADA", ator=usuario,
                 detalhes={"habilitada": bool(habilitada)})


def obter_proximo_job(agent_id, *, printer_name, printer_model):
    with transaction() as conn:
        cursor = conn.cursor(); cursor.execute(q("SELECT * FROM local_print_agents WHERE id=?"), (agent_id,)); agente = cursor.fetchone()
        if not agente or agente["status"] != "ATIVO":
            raise ValueError("Agente não encontrado.")
        agora = _agora(); cursor.execute(q("UPDATE local_print_agents SET last_seen_at=?,printer_name=?,printer_model=? WHERE id=?"), (agora, printer_name, printer_model, agent_id))
        if not bool(agente["auto_print_enabled"]):
            return None
        cursor.execute(q("""UPDATE label_print_jobs SET state='CONFERENCIA_NECESSARIA',
            error_code='LEASE_EXPIRED_AMBIGUOUS',updated_at=? WHERE state='EM_PROCESSAMENTO'
            AND lease_expires_at IS NOT NULL AND lease_expires_at < ?"""), (agora, agora))
        bloqueio = " FOR UPDATE SKIP LOCKED" if DATABASE_URL else ""
        cursor.execute(q("""SELECT j.*,m.template_path,m.printer_allowlist,m.variable_map_json
            FROM label_print_jobs j JOIN label_model_configs m ON m.id=j.model_config_id
            WHERE j.state IN ('PENDENTE','FALHA_TEMPORARIA') ORDER BY j.id LIMIT 1""" + bloqueio))
        job = cursor.fetchone()
        if not job:
            return None
        permitidas = json.loads(job["printer_allowlist"])
        if printer_name not in permitidas:
            raise ValueError("Impressora fora da allowlist exata do modelo.")
        lease = secrets.token_urlsafe(24); expira = (datetime.now(timezone.utc) + timedelta(minutes=2)).replace(microsecond=0).isoformat()
        cursor.execute(q("""UPDATE label_print_jobs SET state='EM_PROCESSAMENTO',agent_id=?,attempts=attempts+1,
            lease_token_hash=?,lease_expires_at=?,reserved_at=?,updated_at=? WHERE id=? AND state IN ('PENDENTE','FALHA_TEMPORARIA')"""),
            (agent_id, hashlib.sha256(lease.encode()).hexdigest(), expira, agora, agora, job["id"]))
        _auditar(cursor, "JOB", job["job_uuid"], "RETIRADO", ator=f"agent:{agent_id}")
        retorno = dict(job); retorno["lease_token"] = lease; retorno["snapshot"] = json.loads(job["snapshot_json"])
        retorno["variable_map"] = json.loads(job["variable_map_json"]); return retorno


def registrar_resultado(job_uuid, lease_token, *, outcome, spool_reference=None, error_code=None, error_message=None):
    estados = {"SPOOL_ACCEPTED": "ENVIADA_IMPRESSORA", "AMBIGUOUS": "CONFERENCIA_NECESSARIA",
               "TEMPORARY_FAILURE": "FALHA_TEMPORARIA", "PERMANENT_FAILURE": "FALHA_PERMANENTE"}
    if outcome not in estados:
        raise ValueError("Resultado do adaptador inválido.")
    with transaction() as conn:
        cursor = conn.cursor(); cursor.execute(q("SELECT * FROM label_print_jobs WHERE job_uuid=?"), (job_uuid,)); job = cursor.fetchone()
        if not job or job["state"] != "EM_PROCESSAMENTO":
            raise ValueError("Job não está disponível para conclusão.")
        recebido = hashlib.sha256(str(lease_token).encode()).hexdigest()
        if not hmac.compare_digest(str(job["lease_token_hash"] or ""), recebido):
            raise ValueError("Lease do job inválido.")
        estado = estados[outcome]; agora = _agora(); enviado = agora if estado == "ENVIADA_IMPRESSORA" else None
        cursor.execute(q("""UPDATE label_print_jobs SET state=?,spool_reference=?,error_code=?,error_message=?,
            sent_at=?,confirmed_at=?,updated_at=?,lease_token_hash=NULL,lease_expires_at=NULL WHERE id=?"""),
            (estado, spool_reference, error_code, str(error_message or "")[:1000], enviado, agora, agora, job["id"]))
        _auditar(cursor, "JOB", job_uuid, "RESULTADO", detalhes={"outcome": outcome, "state": estado,
            "error_code": error_code, "spool_reference": spool_reference})
    return estado
