"""Conferencia auditavel das caixas da Embalagem Secundaria."""

from datetime import datetime
from decimal import Decimal
import hashlib
import json

from database import DATABASE_URL, conectar, q, transaction

from .estornos_embalagem import (
    STATUS_INATIVOS,
    _buscar_bloqueios,
    criar_tabelas_estornos_embalagem,
)


JANELA_DUPLICIDADE_SEGUNDOS = 120


def _decimal(valor):
    return Decimal(str(valor or 0))


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_data(valor):
    if not valor:
        return None
    texto = str(valor).replace("T", " ")[:19]
    try:
        return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def criar_tabelas_conferencia_embalagem():
    criar_tabelas_estornos_embalagem()
    conn = conectar()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS usuario_pesagem TEXT" if DATABASE_URL
                       else "ALTER TABLE pa_caixas ADD COLUMN usuario_pesagem TEXT")
    except Exception as erro:
        if DATABASE_URL or "duplicate column" not in str(erro).lower():
            conn.rollback()
            conn.close()
            raise
    pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS embalagem_secundaria_conferencias (
            id {pk}, op_id INTEGER NOT NULL, usuario TEXT NOT NULL, perfil TEXT NOT NULL,
            confirmado_em {timestamp} NOT NULL, caixas_ativas INTEGER NOT NULL,
            caixas_estornadas INTEGER NOT NULL, total_bandejas TEXT NOT NULL,
            peso_bruto TEXT NOT NULL, peso_tara TEXT NOT NULL DEFAULT '0', peso_liquido TEXT NOT NULL,
            saldo_pendente TEXT NOT NULL DEFAULT '0',
            caixas_ativas_json TEXT NOT NULL, duplicidades_json TEXT NOT NULL,
            hash_conferencia TEXT NOT NULL, snapshot_json TEXT,
            confirmada INTEGER NOT NULL DEFAULT 1
        )
    """)
    for nome in ("peso_tara", "saldo_pendente"):
        try:
            cursor.execute(
                f"ALTER TABLE embalagem_secundaria_conferencias ADD COLUMN IF NOT EXISTS {nome} TEXT NOT NULL DEFAULT '0'"
                if DATABASE_URL else
                f"ALTER TABLE embalagem_secundaria_conferencias ADD COLUMN {nome} TEXT NOT NULL DEFAULT '0'"
            )
        except Exception as erro:
            if DATABASE_URL or "duplicate column" not in str(erro).lower():
                conn.rollback()
                conn.close()
                raise
    try:
        cursor.execute(
            "ALTER TABLE embalagem_secundaria_conferencias ADD COLUMN IF NOT EXISTS snapshot_json TEXT"
            if DATABASE_URL else
            "ALTER TABLE embalagem_secundaria_conferencias ADD COLUMN snapshot_json TEXT"
        )
    except Exception as erro:
        if DATABASE_URL or "duplicate column" not in str(erro).lower():
            conn.rollback()
            conn.close()
            raise
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_conf_emb_op_data ON embalagem_secundaria_conferencias(op_id, confirmado_em)")
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS embalagem_secundaria_requisicoes (
            id {pk}, op_id INTEGER NOT NULL, acao TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE, resultado_json TEXT NOT NULL,
            usuario TEXT, criado_em {timestamp} NOT NULL,
            repeticoes INTEGER NOT NULL DEFAULT 0, ultimo_reenvio_em {timestamp}
        )
    """)
    for nome, definicao in (
        ("repeticoes", "INTEGER NOT NULL DEFAULT 0"),
        ("ultimo_reenvio_em", f"{timestamp}"),
    ):
        try:
            cursor.execute(
                f"ALTER TABLE embalagem_secundaria_requisicoes ADD COLUMN IF NOT EXISTS {nome} {definicao}"
                if DATABASE_URL else
                f"ALTER TABLE embalagem_secundaria_requisicoes ADD COLUMN {nome} {definicao}"
            )
        except Exception as erro:
            if DATABASE_URL or "duplicate column" not in str(erro).lower():
                conn.rollback()
                conn.close()
                raise
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_req_emb_op_data ON embalagem_secundaria_requisicoes(op_id, criado_em)")
    conn.commit()
    conn.close()


def _linhas_op(cursor, op_id):
    cursor.execute(q("""
        SELECT cx.*
        FROM pa_caixas cx
        WHERE EXISTS (
            SELECT 1 FROM pa_caixa_composicao comp
            WHERE comp.caixa_id=cx.id AND comp.op_id=?
        )
        ORDER BY cx.criado_em DESC, cx.id DESC
    """), (op_id,))
    return [dict(item) for item in cursor.fetchall()]


def _usuario_caixa(caixa):
    return caixa.get("formado_por") or caixa.get("usuario_pesagem") or caixa.get("usuario") or "-"


def _chave_semantica(caixa):
    return (
        str(_decimal(caixa.get("peso_bruto")).quantize(Decimal("0.001"))),
        str(_decimal(caixa.get("peso_liquido")).quantize(Decimal("0.001"))),
        str(_decimal(caixa.get("quantidade_bandejas")).normalize()),
        str(caixa.get("data_fabricacao") or ""),
        str(caixa.get("data_validade") or ""),
        str(caixa.get("lote") or caixa.get("codigo_lote") or ""),
        _usuario_caixa(caixa),
    )


def _marcar_duplicidades(caixas):
    ativas = [c for c in caixas if str(c.get("status") or "").upper() not in STATUS_INATIVOS]
    grupos = {}
    for caixa in ativas:
        grupos.setdefault(_chave_semantica(caixa), []).append(caixa)
    duplicadas = set()
    for grupo in grupos.values():
        grupo.sort(key=lambda c: (_parse_data(c.get("criado_em")) or datetime.min, c["id"]))
        for anterior, atual in zip(grupo, grupo[1:]):
            data_a = _parse_data(anterior.get("criado_em"))
            data_b = _parse_data(atual.get("criado_em"))
            if data_a and data_b and (data_b - data_a).total_seconds() <= JANELA_DUPLICIDADE_SEGUNDOS:
                duplicadas.update((int(anterior["id"]), int(atual["id"])))
    for caixa in caixas:
        caixa["usuario_lancamento"] = _usuario_caixa(caixa)
        caixa["possivel_duplicidade"] = int(caixa["id"]) in duplicadas
    return duplicadas


def _totais(caixas):
    ativas = [c for c in caixas if str(c.get("status") or "").upper() not in STATUS_INATIVOS]
    return {
        "caixas_ativas": len(ativas),
        "caixas_estornadas": len(caixas) - len(ativas),
        "bandejas": sum((_decimal(c.get("quantidade_bandejas")) for c in ativas), Decimal("0")),
        "peso_bruto": sum((_decimal(c.get("peso_bruto")) for c in ativas), Decimal("0")),
        "peso_tara": sum((_decimal(c.get("peso_tara")) for c in ativas), Decimal("0")),
        "peso_liquido": sum((_decimal(c.get("peso_liquido")) for c in ativas), Decimal("0")),
    }


def _saldo_pendente(cursor, op_id):
    cursor.execute(q("""SELECT COALESCE(SUM(CASE
        WHEN tipo LIKE 'ENTRADA%%' THEN quantidade_bandejas
        WHEN tipo LIKE 'SAIDA%%' THEN -quantidade_bandejas
        ELSE quantidade_bandejas END), 0) AS saldo
        FROM estoque_produto_intermediario WHERE op_id=?"""), (op_id,))
    linha = cursor.fetchone()
    return _decimal(linha["saldo"] if linha else 0)


def _hash(caixas):
    dados = [{
        "id": int(c["id"]), "versao": int(c.get("versao") or 0),
        "status": str(c.get("status") or ""),
        "bandejas": str(_decimal(c.get("quantidade_bandejas"))),
        "bruto": str(_decimal(c.get("peso_bruto"))),
        "liquido": str(_decimal(c.get("peso_liquido"))),
    } for c in caixas if str(c.get("status") or "").upper() not in STATUS_INATIVOS]
    dados.sort(key=lambda item: item["id"])
    return hashlib.sha256(json.dumps(dados, sort_keys=True).encode("utf-8")).hexdigest()


def _snapshot_documental(caixas, totais, duplicadas, hash_conferencia, *, usuario, perfil, confirmado_em):
    """Congela a conferência; relatórios históricos nunca consultam caixas posteriores."""
    return {
        "versao": 1,
        "confirmado_em": confirmado_em,
        "usuario": usuario,
        "perfil": perfil,
        "hash": hash_conferencia,
        "duplicidades": sorted(duplicadas),
        "totais": {chave: str(valor) for chave, valor in totais.items()},
        "caixas": json.loads(json.dumps(caixas, ensure_ascii=False, default=str)),
    }


def _ler_snapshot(registro):
    if not registro or "snapshot_json" not in registro.keys() or not registro["snapshot_json"]:
        return None
    try:
        snapshot = json.loads(registro["snapshot_json"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    totais = snapshot.get("totais") or {}
    for campo in ("bandejas", "peso_bruto", "peso_tara", "peso_liquido", "saldo_pendente"):
        totais[campo] = _decimal(totais.get(campo))
    for campo in ("caixas_ativas", "caixas_estornadas"):
        totais[campo] = int(_decimal(totais.get(campo)))
    snapshot["totais"] = totais
    snapshot["ultima_conferencia"] = dict(registro)
    snapshot["confirmacao_valida"] = True
    snapshot["caixas_exibidas"] = snapshot.get("caixas") or []
    snapshot["janela_duplicidade_segundos"] = JANELA_DUPLICIDADE_SEGUNDOS
    return snapshot


def obter_conferencia_op(op_id, filtros=None):
    criar_tabelas_conferencia_embalagem()
    conn = conectar()
    cursor = conn.cursor()
    caixas = _linhas_op(cursor, int(op_id))
    duplicadas = _marcar_duplicidades(caixas)
    for caixa in caixas:
        caixa["bloqueios"] = _buscar_bloqueios(cursor, caixa) if str(caixa.get("status") or "").upper() not in STATUS_INATIVOS else []
        caixa["selecionavel"] = not caixa["bloqueios"] and str(caixa.get("status") or "").upper() not in STATUS_INATIVOS
    totais = _totais(caixas)
    totais["saldo_pendente"] = _saldo_pendente(cursor, int(op_id))
    hash_atual = _hash(caixas)
    cursor.execute(q("""SELECT * FROM embalagem_secundaria_conferencias
        WHERE op_id=? ORDER BY id DESC LIMIT 1"""), (op_id,))
    ultima = cursor.fetchone()
    confirmacao_valida = bool(ultima and ultima["confirmada"] and ultima["hash_conferencia"] == hash_atual)
    conn.close()

    filtros = filtros or {}
    situacao = str(filtros.get("situacao") or "todas").lower()
    busca = str(filtros.get("busca") or "").strip().lower()
    usuario = str(filtros.get("usuario") or "").strip().lower()
    peso_bruto = str(filtros.get("peso_bruto") or "").strip().replace(",", ".")
    bandejas = str(filtros.get("bandejas") or "").strip().replace(",", ".")
    horario_inicial = str(filtros.get("horario_inicial") or "").strip()
    horario_final = str(filtros.get("horario_final") or "").strip()
    somente_duplicadas = str(filtros.get("duplicadas") or "").lower() in {"1", "true", "on"}
    exibidas = []
    for caixa in caixas:
        inativa = str(caixa.get("status") or "").upper() in STATUS_INATIVOS
        if situacao == "ativas" and inativa or situacao == "estornadas" and not inativa:
            continue
        texto = " ".join(str(caixa.get(c) or "") for c in (
            "codigo_caixa", "peso_bruto", "peso_liquido", "quantidade_bandejas",
            "usuario_lancamento", "criado_em", "status"))
        if busca and busca not in texto.lower():
            continue
        if usuario and usuario not in str(caixa.get("usuario_lancamento") or "").lower():
            continue
        try:
            if peso_bruto and _decimal(caixa.get("peso_bruto")) != Decimal(peso_bruto):
                continue
            if bandejas and _decimal(caixa.get("quantidade_bandejas")) != Decimal(bandejas):
                continue
        except Exception:
            continue
        criado = _parse_data(caixa.get("criado_em"))
        if horario_inicial and (not criado or criado.strftime("%H:%M") < horario_inicial):
            continue
        if horario_final and (not criado or criado.strftime("%H:%M") > horario_final):
            continue
        if somente_duplicadas and not caixa["possivel_duplicidade"]:
            continue
        exibidas.append(caixa)
    ordem = str(filtros.get("ordem") or "desc").lower()
    exibidas.sort(
        key=lambda c: (_parse_data(c.get("criado_em")) or datetime.min, int(c["id"])),
        reverse=ordem != "asc",
    )
    return {
        "caixas": caixas, "caixas_exibidas": exibidas, "totais": totais,
        "hash": hash_atual, "duplicidades": sorted(duplicadas),
        "confirmacao_valida": confirmacao_valida, "ultima_conferencia": dict(ultima) if ultima else None,
        "janela_duplicidade_segundos": JANELA_DUPLICIDADE_SEGUNDOS,
        "ordem": ordem, "snapshot_documental": _ler_snapshot(ultima),
    }


def confirmar_conferencia_op(op_id, *, usuario, perfil, hash_informado):
    criar_tabelas_conferencia_embalagem()
    with transaction() as conn:
        cursor = conn.cursor()
        caixas = _linhas_op(cursor, int(op_id))
        duplicadas = _marcar_duplicidades(caixas)
        hash_atual = _hash(caixas)
        if not hash_informado or hash_informado != hash_atual:
            raise ValueError("A relação de caixas mudou. Atualize a conferência antes de confirmar.")
        totais = _totais(caixas)
        totais["saldo_pendente"] = _saldo_pendente(cursor, int(op_id))
        ids_ativas = [int(c["id"]) for c in caixas if str(c.get("status") or "").upper() not in STATUS_INATIVOS]
        confirmado_em = _agora()
        snapshot = _snapshot_documental(
            caixas, totais, duplicadas, hash_atual,
            usuario=usuario, perfil=perfil, confirmado_em=confirmado_em,
        )
        cursor.execute(q("""INSERT INTO embalagem_secundaria_conferencias(
            op_id,usuario,perfil,confirmado_em,caixas_ativas,caixas_estornadas,total_bandejas,
            peso_bruto,peso_tara,peso_liquido,saldo_pendente,caixas_ativas_json,duplicidades_json,
            hash_conferencia,snapshot_json,confirmada)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)"""), (
            op_id, usuario, perfil, confirmado_em, totais["caixas_ativas"], totais["caixas_estornadas"],
            str(totais["bandejas"]), str(totais["peso_bruto"]), str(totais["peso_tara"]),
            str(totais["peso_liquido"]), str(totais["saldo_pendente"]),
            json.dumps(ids_ativas), json.dumps(sorted(duplicadas)), hash_atual,
            json.dumps(snapshot, ensure_ascii=False, default=str),
        ))
    return {**totais, "hash": hash_atual, "usuario": usuario}


def validar_conferencia_para_encerramento(cursor, op_id, hash_informado):
    caixas = _linhas_op(cursor, int(op_id))
    hash_atual = _hash(caixas)
    cursor.execute(q("""SELECT * FROM embalagem_secundaria_conferencias
        WHERE op_id=? ORDER BY id DESC LIMIT 1"""), (op_id,))
    registro = cursor.fetchone()
    if not registro or not registro["confirmada"]:
        raise ValueError("Confirme a Conferência de Caixas da OP antes do encerramento.")
    if not hash_informado or registro["hash_conferencia"] != hash_informado or hash_atual != hash_informado:
        raise ValueError("A conferência está desatualizada. Confira novamente as caixas antes de encerrar.")
    return dict(registro)
