"""Ciclo físico e documental de reprocessamento de Produtos Não Conformes."""

from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
from uuid import uuid4

from flask import has_request_context, request, session

from database import q
from . import produtos_nao_conformes as nc


PERFIS_REPROCESSAMENTO = {"admin", "gerencia", "qualidade"}
EM_ANDAMENTO = "EM_ANDAMENTO"
CONCLUIDO = "CONCLUIDO"
CANCELADO = "CANCELADO"
CANCELADA_LIBERACAO = "CANCELADA_POR_REPROCESSAMENTO"


def _agora():
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def _identidade(usuario=None, perfil=None, origem=None):
    if has_request_context():
        usuario = usuario or session.get("nome") or "Usuário não identificado"
        perfil = perfil or session.get("perfil") or "não identificado"
        origem = origem or request.remote_addr or "web"
    return usuario or "Sistema", (perfil or "sistema").lower(), origem or "interno"


def _gramas(valor, campo="Peso"):
    texto = str(valor or "0").strip().replace(".", "").replace(",", ".") if "," in str(valor or "") else str(valor or "0").strip()
    try:
        numero = Decimal(texto)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{campo} inválido.")
    if numero < 0:
        raise ValueError(f"{campo} não pode ser negativo.")
    return int((numero * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _inteiro(valor, campo):
    try:
        numero = Decimal(str(valor or "0").strip())
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{campo} inválido.")
    if numero != numero.to_integral_value() or numero < 0:
        raise ValueError(f"{campo} deve ser um inteiro não negativo.")
    return int(numero)


def garantir_schema():
    nc.criar_tabelas_pa_nao_conforme()
    conn = nc.conectar()
    cursor = conn.cursor()
    id_pk = "SERIAL PRIMARY KEY" if nc.DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = "TIMESTAMP" if nc.DATABASE_URL else "TEXT"
    try:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS pnc_reprocessamentos (
                id {id_pk}, pa_nao_conforme_id INTEGER NOT NULL,
                status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE,
                modalidade TEXT NOT NULL, peso_g INTEGER NOT NULL DEFAULT 0,
                caixas INTEGER NOT NULL DEFAULT 0, bandejas INTEGER NOT NULL DEFAULT 0,
                galinhas INTEGER NOT NULL DEFAULT 0, pacotes INTEGER NOT NULL DEFAULT 0,
                justificativa TEXT NOT NULL, observacoes TEXT,
                iniciado_por TEXT NOT NULL, perfil_inicio TEXT NOT NULL,
                iniciado_em {timestamp_type} NOT NULL, concluido_por TEXT,
                concluido_em {timestamp_type}, cancelado_por TEXT,
                cancelado_em {timestamp_type}, justificativa_fechamento TEXT,
                snapshot_json TEXT NOT NULL, atualizado_em {timestamp_type} NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pnc_reprocessamento_registro ON pnc_reprocessamentos(pa_nao_conforme_id,status)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _saldo_disponivel(cursor, registro):
    if registro["tipo_registro"] == nc.TIPO_LEGADO:
        return {
            "peso_g": int(registro["saldo_bloqueado_g"] or 0),
            "caixas": int(registro["caixas_bloqueadas"] or 0),
            "bandejas": int(registro["bandejas_bloqueadas"] or 0),
            "galinhas": int(registro["galinhas_bloqueadas"] or 0) if "galinhas_bloqueadas" in registro.keys() else 0,
            "pacotes": int(registro["pacotes_bloqueados"] or 0) if "pacotes_bloqueados" in registro.keys() else 0,
        }
    unidade = str(registro["unidade"] or "").upper()
    quantidade = _inteiro(registro["quantidade"], "Quantidade do PNC")
    galinhas = 0
    if unidade == "PACOTE" and registro["caixa_id"]:
        if nc.DATABASE_URL:
            possui_colunas_aves = True
        else:
            cursor.execute("PRAGMA table_info(pa_caixas)")
            colunas = {linha[1] for linha in cursor.fetchall()}
            possui_colunas_aves = {"quantidade_pacotes", "quantidade_galinhas"} <= colunas
        if possui_colunas_aves:
            cursor.execute(q("SELECT quantidade_pacotes,quantidade_galinhas FROM pa_caixas WHERE id=?"),
                           (registro["caixa_id"],))
            caixa = cursor.fetchone()
            if caixa:
                quantidade = _inteiro(caixa["quantidade_pacotes"], "Pacotes da caixa")
                galinhas = _inteiro(caixa["quantidade_galinhas"], "Galinhas da caixa")
    return {
        "peso_g": 0 if unidade == "PACOTE" else _gramas(registro["peso"], "Peso do PNC"),
        "caixas": 0 if unidade == "PACOTE" else 1,
        "bandejas": quantidade if unidade == "BANDEJA" else 0,
        "galinhas": galinhas,
        "pacotes": quantidade if unidade == "PACOTE" else 0,
    }


def _quantidades(dados, disponivel, legado):
    modalidade = str(dados.get("modalidade") or "INTEGRAL").upper()
    if modalidade not in {"INTEGRAL", "PARCIAL"}:
        raise ValueError("Modalidade de reprocessamento inválida.")
    if modalidade == "PARCIAL" and not legado:
        raise ValueError("Caixa rastreada não pode ser fracionada no reprocessamento.")
    if modalidade == "INTEGRAL":
        return modalidade, dict(disponivel)
    saida = {
        "peso_g": _gramas(dados.get("peso")),
        "caixas": _inteiro(dados.get("caixas"), "Caixas"),
        "bandejas": _inteiro(dados.get("bandejas"), "Bandejas"),
        "galinhas": _inteiro(dados.get("galinhas"), "Galinhas"),
        "pacotes": _inteiro(dados.get("pacotes"), "Pacotes"),
    }
    if not any(saida.values()):
        raise ValueError("Informe ao menos uma quantidade para reprocessamento.")
    for chave, valor in saida.items():
        if valor > disponivel[chave]:
            raise ValueError("A quantidade de reprocessamento excede o saldo bloqueado.")
    return modalidade, saida


def iniciar_reprocessamento(registro_id, dados, *, usuario=None, perfil=None, origem=None,
                            idempotency_key=None, checkpoint=None):
    """Retira o lote escolhido do bloqueio e o coloca em reprocessamento."""
    usuario, perfil, origem = _identidade(usuario, perfil, origem)
    if perfil not in PERFIS_REPROCESSAMENTO:
        raise PermissionError("Perfil sem permissão para iniciar reprocessamento.")
    justificativa = str(dados.get("justificativa") or "").strip()
    if not justificativa:
        raise ValueError("A justificativa do reprocessamento é obrigatória.")
    garantir_schema()
    chave = idempotency_key or dados.get("idempotency_key") or f"REPROC-{registro_id}-{uuid4().hex}"
    with nc.transaction() as conn:
        cursor = conn.cursor()
        bloqueio = " FOR UPDATE" if nc.DATABASE_URL else ""
        cursor.execute(q("SELECT * FROM pa_nao_conformes WHERE id=?" + bloqueio), (registro_id,))
        registro = cursor.fetchone()
        if not registro:
            raise ValueError("Produto Não Conforme não encontrado.")
        cursor.execute(q("SELECT * FROM pnc_reprocessamentos WHERE idempotency_key=?"), (chave,))
        existente = cursor.fetchone()
        if existente:
            return dict(existente)
        if registro["status"] not in {"BLOQUEADO", "EM_AVALIACAO", "MANTIDO_BLOQUEADO"}:
            raise ValueError("O PNC não está disponível para iniciar reprocessamento.")
        cursor.execute(q("SELECT id FROM pnc_reprocessamentos WHERE pa_nao_conforme_id=? AND status=?" + bloqueio),
                       (registro_id, EM_ANDAMENTO))
        if cursor.fetchone():
            raise ValueError("Já existe reprocessamento em andamento para este PNC.")
        disponivel = _saldo_disponivel(cursor, registro)
        if not any(disponivel.values()):
            raise ValueError("O PNC não possui saldo físico bloqueado.")
        modalidade, saida = _quantidades(dados, disponivel, registro["tipo_registro"] == nc.TIPO_LEGADO)
        remanescente = {chave_saldo: disponivel[chave_saldo] - saida[chave_saldo] for chave_saldo in disponivel}
        agora = _agora()
        snapshot = {
            "saldo_anterior": disponivel, "quantidade_reprocessada": saida,
            "saldo_remanescente": remanescente, "status_anterior": registro["status"],
            "numero_pnc": registro["numero"], "produto": registro["produto"],
            "idempotency_key": chave,
        }
        params = (registro_id, EM_ANDAMENTO, chave, modalidade, saida["peso_g"], saida["caixas"],
                  saida["bandejas"], saida["galinhas"], saida["pacotes"], justificativa,
                  str(dados.get("observacoes") or "").strip(), usuario, perfil, agora,
                  json.dumps(snapshot, ensure_ascii=False, sort_keys=True), agora)
        sql = """INSERT INTO pnc_reprocessamentos(pa_nao_conforme_id,status,idempotency_key,
            modalidade,peso_g,caixas,bandejas,galinhas,pacotes,justificativa,observacoes,
            iniciado_por,perfil_inicio,iniciado_em,snapshot_json,atualizado_em)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
        if nc.DATABASE_URL:
            cursor.execute(q(sql + " RETURNING id"), params)
            reprocessamento_id = cursor.fetchone()["id"]
        else:
            cursor.execute(q(sql), params)
            reprocessamento_id = cursor.lastrowid
        if registro["tipo_registro"] == nc.TIPO_LEGADO:
            cursor.execute(q("""UPDATE pa_nao_conformes SET saldo_bloqueado_g=?,caixas_bloqueadas=?,
                bandejas_bloqueadas=?,galinhas_bloqueadas=?,pacotes_bloqueados=?,saldo_pendente_g=0,
                status='REPROCESSO',
                decisao='REPROCESSO',justificativa_destinacao=?,decidido_por=?,perfil_decisao=?,
                decidido_em=?,atualizado_em=? WHERE id=? AND status=?"""),
                (remanescente["peso_g"], remanescente["caixas"], remanescente["bandejas"],
                 remanescente["galinhas"], remanescente["pacotes"], justificativa, usuario,
                 perfil, agora, agora, registro_id, registro["status"]))
        else:
            cursor.execute(q("""UPDATE pa_nao_conformes SET status='REPROCESSO',decisao='REPROCESSO',
                saldo_pendente_g=0,justificativa_destinacao=?,decidido_por=?,perfil_decisao=?,decidido_em=?,atualizado_em=?
                WHERE id=? AND status=?"""),
                (justificativa, usuario, perfil, agora, agora, registro_id, registro["status"]))
            if cursor.rowcount == 1 and registro["caixa_id"]:
                cursor.execute(q("""UPDATE pa_caixas SET condicao='NAO_CONFORME',
                    disponibilidade='REPROCESSAMENTO',zona_estoque='Produto Não Conforme'
                    WHERE id=?"""), (registro["caixa_id"],))
        if cursor.rowcount != 1:
            raise ValueError("O PNC foi alterado simultaneamente; revalide o saldo.")
        cursor.execute(q("""UPDATE pa_nao_conforme_solicitacoes SET status=?,decidido_por=?,
            perfil_decisor=?,decidido_em=?,justificativa_decisao=?,atualizado_em=?
            WHERE pa_nao_conforme_id=? AND status='AGUARDANDO_VALIDACAO_GERENCIA'"""),
            (CANCELADA_LIBERACAO, usuario, perfil, agora,
             "Solicitação incompatível cancelada ao iniciar reprocessamento.", agora, registro_id))
        nc._evento(cursor, registro_id, "INICIO_REPROCESSAMENTO", registro["status"], "REPROCESSO",
                   usuario, perfil, origem, justificativa,
                   json.dumps({**snapshot, "reprocessamento_id": reprocessamento_id}, ensure_ascii=False, sort_keys=True))
        if checkpoint:
            checkpoint("reprocessamento_iniciado")
        return {"id": reprocessamento_id, "status": EM_ANDAMENTO, **snapshot}


def _obter_para_fechamento(cursor, reprocessamento_id):
    bloqueio = " FOR UPDATE" if nc.DATABASE_URL else ""
    cursor.execute(q("""SELECT r.*,nc.status AS pnc_status,nc.tipo_registro,nc.caixa_id,
        nc.saldo_bloqueado_g,nc.caixas_bloqueadas,nc.bandejas_bloqueadas,
        nc.galinhas_bloqueadas,nc.pacotes_bloqueados
        FROM pnc_reprocessamentos r JOIN pa_nao_conformes nc ON nc.id=r.pa_nao_conforme_id
        WHERE r.id=?""" + bloqueio), (reprocessamento_id,))
    registro = cursor.fetchone()
    if not registro:
        raise ValueError("Reprocessamento não encontrado.")
    return registro


def concluir_reprocessamento(reprocessamento_id, justificativa, *, usuario=None, perfil=None,
                             origem=None, idempotency_key=None, checkpoint=None):
    """Conclui o consumo físico; saldo parcial remanescente volta ao bloqueio."""
    usuario, perfil, origem = _identidade(usuario, perfil, origem)
    if perfil not in PERFIS_REPROCESSAMENTO:
        raise PermissionError("Perfil sem permissão para concluir reprocessamento.")
    justificativa = str(justificativa or "").strip()
    if not justificativa:
        raise ValueError("Informe o resultado documentado do reprocessamento.")
    garantir_schema()
    with nc.transaction() as conn:
        cursor = conn.cursor()
        registro = _obter_para_fechamento(cursor, reprocessamento_id)
        if registro["status"] == CONCLUIDO:
            return {"id": reprocessamento_id, "status": CONCLUIDO,
                    "pnc_status": registro["pnc_status"], "idempotente": True}
        if registro["status"] != EM_ANDAMENTO or registro["pnc_status"] != "REPROCESSO":
            raise ValueError("O reprocessamento não está em andamento.")
        remanescente = any(int(registro[campo] or 0) > 0 for campo in (
            "saldo_bloqueado_g", "caixas_bloqueadas", "bandejas_bloqueadas",
            "galinhas_bloqueadas", "pacotes_bloqueados"
        )) if registro["tipo_registro"] == nc.TIPO_LEGADO else False
        novo_status = "BLOQUEADO" if remanescente else "REPROCESSADO"
        agora = _agora()
        cursor.execute(q("""UPDATE pnc_reprocessamentos SET status=?,concluido_por=?,concluido_em=?,
            justificativa_fechamento=?,atualizado_em=? WHERE id=? AND status=?"""),
            (CONCLUIDO, usuario, agora, justificativa, agora, reprocessamento_id, EM_ANDAMENTO))
        if cursor.rowcount != 1:
            raise ValueError("O reprocessamento foi concluído simultaneamente.")
        cursor.execute(q("UPDATE pa_nao_conformes SET status=?,atualizado_em=? WHERE id=? AND status='REPROCESSO'"),
                       (novo_status, agora, registro["pa_nao_conforme_id"]))
        if cursor.rowcount != 1:
            raise ValueError("O PNC foi alterado simultaneamente.")
        if registro["caixa_id"]:
            cursor.execute(q("""UPDATE pa_caixas SET disponibilidade='REPROCESSADO',
                zona_estoque='Histórico de Produto Não Conforme' WHERE id=?"""), (registro["caixa_id"],))
        nc._evento(cursor, registro["pa_nao_conforme_id"], "CONCLUSAO_REPROCESSAMENTO",
                   "REPROCESSO", novo_status, usuario, perfil, origem, justificativa,
                   json.dumps({"reprocessamento_id": reprocessamento_id,
                               "idempotency_key": idempotency_key or f"REPROC-CONCLUIR-{reprocessamento_id}"}, sort_keys=True))
        if checkpoint:
            checkpoint("reprocessamento_concluido")
        return {"id": reprocessamento_id, "status": CONCLUIDO, "pnc_status": novo_status}


def cancelar_reprocessamento(reprocessamento_id, justificativa, *, usuario=None, perfil=None,
                             origem=None, checkpoint=None):
    """Cancela antes da conclusão e devolve exatamente o saldo ao bloqueio."""
    usuario, perfil, origem = _identidade(usuario, perfil, origem)
    if perfil not in PERFIS_REPROCESSAMENTO:
        raise PermissionError("Perfil sem permissão para cancelar reprocessamento.")
    justificativa = str(justificativa or "").strip()
    if not justificativa:
        raise ValueError("A justificativa do cancelamento é obrigatória.")
    garantir_schema()
    with nc.transaction() as conn:
        cursor = conn.cursor()
        registro = _obter_para_fechamento(cursor, reprocessamento_id)
        if registro["status"] == CANCELADO:
            return {"id": reprocessamento_id, "status": CANCELADO, "idempotente": True}
        if registro["status"] != EM_ANDAMENTO or registro["pnc_status"] != "REPROCESSO":
            raise ValueError("Somente reprocessamento em andamento pode ser cancelado.")
        agora = _agora()
        cursor.execute(q("""UPDATE pnc_reprocessamentos SET status=?,cancelado_por=?,cancelado_em=?,
            justificativa_fechamento=?,atualizado_em=? WHERE id=? AND status=?"""),
            (CANCELADO, usuario, agora, justificativa, agora, reprocessamento_id, EM_ANDAMENTO))
        if registro["tipo_registro"] == nc.TIPO_LEGADO:
            cursor.execute(q("""UPDATE pa_nao_conformes SET status='BLOQUEADO',saldo_bloqueado_g=saldo_bloqueado_g+?,
                caixas_bloqueadas=caixas_bloqueadas+?,bandejas_bloqueadas=bandejas_bloqueadas+?,
                galinhas_bloqueadas=galinhas_bloqueadas+?,pacotes_bloqueados=pacotes_bloqueados+?,atualizado_em=?
                WHERE id=? AND status='REPROCESSO'"""),
                (registro["peso_g"], registro["caixas"], registro["bandejas"], registro["galinhas"],
                 registro["pacotes"], agora, registro["pa_nao_conforme_id"]))
        else:
            cursor.execute(q("UPDATE pa_nao_conformes SET status='BLOQUEADO',atualizado_em=? WHERE id=? AND status='REPROCESSO'"),
                           (agora, registro["pa_nao_conforme_id"]))
            if cursor.rowcount == 1 and registro["caixa_id"]:
                cursor.execute(q("""UPDATE pa_caixas SET disponibilidade='BLOQUEADO',
                    zona_estoque='Produto Não Conforme' WHERE id=?"""), (registro["caixa_id"],))
        if cursor.rowcount != 1:
            raise ValueError("O PNC foi alterado simultaneamente.")
        nc._evento(cursor, registro["pa_nao_conforme_id"], "CANCELAMENTO_REPROCESSAMENTO",
                   "REPROCESSO", "BLOQUEADO", usuario, perfil, origem, justificativa,
                   json.dumps({"reprocessamento_id": reprocessamento_id,
                               "saldo_restaurado": {"peso_g": registro["peso_g"], "caixas": registro["caixas"],
                               "bandejas": registro["bandejas"], "galinhas": registro["galinhas"],
                               "pacotes": registro["pacotes"]}}, sort_keys=True))
        if checkpoint:
            checkpoint("reprocessamento_cancelado")
        return {"id": reprocessamento_id, "status": CANCELADO, "pnc_status": "BLOQUEADO"}


def listar_reprocessamentos(registro_id):
    garantir_schema()
    conn = nc.conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM pnc_reprocessamentos WHERE pa_nao_conforme_id=? ORDER BY iniciado_em DESC,id DESC"),
                       (registro_id,))
        return cursor.fetchall()
    finally:
        conn.close()
