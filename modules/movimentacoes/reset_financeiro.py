"""Reset administrativo, auditavel e fail-closed do modulo Financeiro.

O modulo nao e importador e nao executa trabalho ao ser importado. O dry-run e
somente leitura; a execucao real exige que o mesmo estado tenha sido aprovado,
gera backup completo e restaura a transacao inteira diante de qualquer desvio.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import unquote, urlparse

from database import DATABASE_URL, DB_NAME, conectar, q


CONFIRMATION_TOKEN = "RESET_FINANCEIRO_FRIGODATTA"
REPORT_VERSION = 1
AUDIT_TABLE = "reset_financeiro_auditoria"

# Somente tabelas cuja finalidade financeira esta comprovada no codigo ou nas
# migrations do projeto. Tabelas apenas "parecidas" sao bloqueadores do dry-run.
TARGET_TABLE_CLASSES = {
    "movimentacoes_financeiras_importacao_linhas": "linhas_importacao",
    "movimentacoes_financeiras_origens": "vinculos_e_idempotencia",
    "movimentacoes_financeiras": "titulos_e_movimentos",
    "movimentacoes_financeiras_importacao_lotes": "lotes_importacao",
    # Nomes legados ja reconhecidos pela aplicacao historica.
    "logs_importacao_financeira": "logs_importacao",
    "importacao_financeira_logs": "logs_importacao",
    "importacoes_financeiras": "lotes_importacao",
    "financeiro_lancamentos": "titulos_e_movimentos",
    "financeiro": "titulos_e_movimentos",
}

PREFERRED_DELETE_ORDER = tuple(TARGET_TABLE_CLASSES)

PRESERVED_FINANCIAL_TABLES = {
    "movimentacoes_financeiras_auditoria",
    "movimentacoes_financeiras_configuracao_corte",
    "movimentacoes_financeiras_backup_aportes_natureza_20260714",
    "hotfix_aportes_natureza_fluxo",
    "plano_contas_mestre",
    AUDIT_TABLE,
}

# Estas fontes sao operacionais/CMV e nunca podem ser confundidas com caixa.
PROTECTED_OPERATIONAL_TABLES = {
    "vendas_diarias",
    "custos_mensais",
    "parametros_custos",
}

PRESERVATION_GROUPS = {
    "clientes": (("clientes",), ("cliente_", "clientes_")),
    "fornecedores": (("fornecedores",), ("fornecedor_", "fornecedores_")),
    "produtos": (("produtos", "skus", "receitas_sku", "processos_produtivos"), ("produto_", "produtos_", "engenharia_produto")),
    "estoque": (("pa_caixas", "pa_caixa_composicao", "pa_movimentacoes", "locais_estoque"), ("estoque_", "almoxarifado_")),
    "producao": (("ordens_producao",), ("apontamentos_", "producao_", "programacao_linha", "op_", "linha_abate_", "linha_performance_", "embalagem_", "correcoes_administrativas_op", "tentativas_correcao_administrativa_op")),
    "pedidos": (("pedidos_venda",), ("pedido_venda_",)),
    "romaneios": (("expedicoes",), ("romaneio_",)),
    "expedicao": (("expedicoes",), ("expedicao_",)),
    "pnc": (("pa_nao_conformes",), ("pa_nao_conforme", "pnc_", "sgi_")),
    "dados_operacionais_cmv": (("vendas_diarias", "custos_mensais", "parametros_custos"), ("cmv_",)),
    "cadastros_financeiros": (("plano_contas_mestre", "movimentacoes_financeiras_configuracao_corte"), ("contas_bancarias", "formas_pagamento")),
    "auditoria_financeira_global": (("movimentacoes_financeiras_auditoria",), ()),
}

# O bootstrap atual do FrigoDatta regrava este carimbo sem alterar o plano.
# Os campos funcionais e o criado_em continuam participando do checksum.
PRESERVATION_VOLATILE_COLUMNS = {
    "plano_contas_mestre": {"atualizado_em"},
}

FINANCIAL_NAME_MARKERS = (
    "financeir", "conta_receber", "contas_receber", "conta_pagar",
    "contas_pagar", "recebimento", "pagamento", "liquidacao", "concili",
    "movimento_banc", "movimentos_banc", "movimento_caixa", "movimentos_caixa",
    "adiantamento", "mutuo", "provisao_fin", "saldo_inicial_fin",
)

DATE_COLUMN_PREFERENCE = (
    "data_documento", "data_vencimento", "data_realizacao", "data_pagamento",
    "data", "criado_em", "iniciado_em", "finalizado_em",
)
ORIGINAL_VALUE_COLUMNS = ("valor_documento", "valor_original", "valor", "montante")
PAID_VALUE_COLUMNS = ("valor_pago", "valor_baixado", "valor_recebido", "valor_liquidado")
STATUS_CLOSED = {"realizado", "pago", "recebido", "liquidado", "baixado", "cancelado"}


class ResetSafetyError(RuntimeError):
    """Condicao de parada que impede qualquer exclusao."""


def _now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _quote(identifier):
    if not identifier or not all(ch.isalnum() or ch == "_" for ch in identifier):
        raise ResetSafetyError(f"Identificador de banco inseguro: {identifier!r}")
    return f'"{identifier}"'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def _sha(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _row_dict(row, description=None):
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    names = [item[0] for item in description or ()]
    return dict(zip(names, row))


def _fetch_dicts(cursor):
    return [_row_dict(row, cursor.description) for row in cursor.fetchall()]


def _tables(cursor):
    if DATABASE_URL:
        cursor.execute("""
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema='public' AND table_type='BASE TABLE'
            ORDER BY table_name
        """)
    else:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [str(_row_dict(row, cursor.description)["name"]) for row in cursor.fetchall() if _row_dict(row, cursor.description)["name"] != "sqlite_sequence"]


def _columns(cursor, table):
    if DATABASE_URL:
        cursor.execute(q("""
            SELECT column_name AS name, data_type AS type,
                   CASE WHEN is_nullable='YES' THEN 1 ELSE 0 END AS nullable,
                   ordinal_position AS position
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=?
            ORDER BY ordinal_position
        """), (table,))
        return _fetch_dicts(cursor)
    cursor.execute(f"PRAGMA table_info({_quote(table)})")
    return [
        {"name": row[1], "type": row[2], "nullable": not bool(row[3]), "position": row[0] + 1, "pk": row[5]}
        for row in cursor.fetchall()
    ]


def _foreign_keys(cursor, tables):
    if DATABASE_URL:
        cursor.execute("""
            SELECT tc.table_name AS child_table, kcu.column_name AS child_column,
                   ccu.table_name AS parent_table, ccu.column_name AS parent_column,
                   CASE WHEN cols.is_nullable='YES' THEN 1 ELSE 0 END AS nullable
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name=kcu.constraint_name AND tc.table_schema=kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name=tc.constraint_name AND ccu.table_schema=tc.table_schema
            JOIN information_schema.columns cols
              ON cols.table_schema=tc.table_schema AND cols.table_name=tc.table_name
             AND cols.column_name=kcu.column_name
            WHERE tc.constraint_type='FOREIGN KEY' AND tc.table_schema='public'
            ORDER BY tc.table_name,kcu.column_name
        """)
        return _fetch_dicts(cursor)
    result = []
    for child in tables:
        info = {col["name"]: col for col in _columns(cursor, child)}
        cursor.execute(f"PRAGMA foreign_key_list({_quote(child)})")
        for row in cursor.fetchall():
            result.append({
                "child_table": child,
                "child_column": row[3],
                "parent_table": row[2],
                "parent_column": row[4],
                "nullable": bool(info.get(row[3], {}).get("nullable")),
            })
    return result


def _schema_snapshot(cursor):
    tables = _tables(cursor)
    columns = {table: _columns(cursor, table) for table in tables}
    foreign_keys = _foreign_keys(cursor, tables)
    return {"tables": tables, "columns": columns, "foreign_keys": foreign_keys}


def _discover(cursor):
    schema = _schema_snapshot(cursor)
    existing = set(schema["tables"])
    targets = [name for name in PREFERRED_DELETE_ORDER if name in existing]
    unknown = []
    for table in schema["tables"]:
        lowered = table.lower()
        if table in targets or table in PRESERVED_FINANCIAL_TABLES or table in PROTECTED_OPERATIONAL_TABLES:
            continue
        if any(marker in lowered for marker in FINANCIAL_NAME_MARKERS):
            unknown.append(table)

    blockers = []
    if "movimentacoes_financeiras" not in existing:
        blockers.append({
            "code": "CORE_FINANCIAL_TABLE_MISSING",
            "detail": "A tabela financeira principal nao existe; o schema do ambiente nao pode ser comprovado.",
        })
    if unknown:
        blockers.append({
            "code": "UNKNOWN_FINANCIAL_TABLES",
            "detail": "Tabelas de aparencia financeira sem classificacao comprovada.",
            "tables": unknown,
        })

    target_set = set(targets)
    detach = []
    for fk in schema["foreign_keys"]:
        if fk["parent_table"] not in target_set or fk["child_table"] in target_set:
            continue
        if fk["child_table"] == "movimentacoes_financeiras_auditoria":
            blockers.append({
                "code": "IMMUTABLE_AUDIT_FK",
                "detail": "A auditoria imutavel possui FK impeditiva para movimento financeiro.",
                "foreign_key": fk,
            })
        elif fk["nullable"]:
            detach.append(fk)
        else:
            blockers.append({
                "code": "NON_NULL_OPERATIONAL_FK",
                "detail": "Vinculo operacional obrigatorio impediria preservar o documento.",
                "foreign_key": fk,
            })

    order = _delete_order(targets, schema["foreign_keys"])
    return schema, targets, order, detach, blockers


def _delete_order(targets, foreign_keys):
    remaining = list(targets)
    target_set = set(targets)
    edges = {
        (fk["child_table"], fk["parent_table"])
        for fk in foreign_keys
        if fk["child_table"] in target_set and fk["parent_table"] in target_set
        and fk["child_table"] != fk["parent_table"]
    }
    ordered = []
    while remaining:
        ready = [table for table in remaining if not any(parent == table and child in remaining for child, parent in edges)]
        if not ready:
            raise ResetSafetyError("Ciclo de chaves estrangeiras entre tabelas financeiras.")
        ready.sort(key=lambda item: PREFERRED_DELETE_ORDER.index(item))
        for table in ready:
            ordered.append(table)
            remaining.remove(table)
    return ordered


def _count(cursor, table, where="", params=()):
    cursor.execute(q(f"SELECT COUNT(*) AS total FROM {_quote(table)} {where}"), params)
    return int(_row_dict(cursor.fetchone(), cursor.description)["total"] or 0)


def _sum(cursor, table, column):
    cursor.execute(f"SELECT COALESCE(SUM({_quote(column)}),0) AS total FROM {_quote(table)}")
    value = _row_dict(cursor.fetchone(), cursor.description)["total"] or 0
    return str(Decimal(str(value)))


def _table_inventory(cursor, table, functional_class, columns):
    names = [col["name"] for col in columns]
    date_columns = [name for name in DATE_COLUMN_PREFERENCE if name in names]
    original = next((name for name in ORIGINAL_VALUE_COLUMNS if name in names), None)
    paid = next((name for name in PAID_VALUE_COLUMNS if name in names), None)
    status = "status" if "status" in names else None
    result = {
        "table": table,
        "functional_class": functional_class,
        "records": _count(cursor, table),
        "minimum_date": None,
        "maximum_date": None,
        "original_value": "0",
        "paid_value": "0",
        "balance": "0",
        "open_titles": 0,
        "closed_titles": 0,
        "reconciliations": 0,
        "bank_movements": 0,
        "operational_document_links": 0,
        "import_batches": 0,
        "associated_audit_records": 0,
    }
    if date_columns:
        expressions = [f"MIN({_quote(name)}) AS min_{index}" for index, name in enumerate(date_columns)]
        expressions += [f"MAX({_quote(name)}) AS max_{index}" for index, name in enumerate(date_columns)]
        cursor.execute(f"SELECT {','.join(expressions)} FROM {_quote(table)}")
        values = list(_row_dict(cursor.fetchone(), cursor.description).values())
        minima = [str(value) for value in values[:len(date_columns)] if value not in (None, "")]
        maxima = [str(value) for value in values[len(date_columns):] if value not in (None, "")]
        result["minimum_date"] = min(minima) if minima else None
        result["maximum_date"] = max(maxima) if maxima else None
    if original:
        result["original_value"] = _sum(cursor, table, original)
    if paid:
        result["paid_value"] = _sum(cursor, table, paid)
    result["balance"] = str(Decimal(result["original_value"]) - Decimal(result["paid_value"]))
    if status and functional_class == "titulos_e_movimentos":
        cursor.execute(f"SELECT {_quote(status)} FROM {_quote(table)}")
        statuses = [str(_row_dict(row, cursor.description)[status] or "").strip().lower() for row in cursor.fetchall()]
        result["closed_titles"] = sum(item in STATUS_CLOSED for item in statuses)
        result["open_titles"] = len(statuses) - result["closed_titles"]
    if functional_class == "lotes_importacao":
        result["import_batches"] = result["records"]
    if functional_class == "vinculos_e_idempotencia":
        result["operational_document_links"] = result["records"]
    lowered = table.lower()
    if "concili" in lowered:
        result["reconciliations"] = result["records"]
    if "banc" in lowered:
        result["bank_movements"] = result["records"]
    if table == "movimentacoes_financeiras" and "documento_id" in names:
        result["operational_document_links"] = _count(cursor, table, "WHERE documento_id IS NOT NULL AND TRIM(documento_id)<>''")
    return result


def _inventory(cursor, targets, schema):
    items = [
        _table_inventory(cursor, table, TARGET_TABLE_CLASSES[table], schema["columns"][table])
        for table in targets
    ]
    for item in items:
        item["sha256"] = _table_checksum(cursor, item["table"], schema["columns"][item["table"]])["sha256"]
    existing = set(schema["tables"])
    audit_count = _count(cursor, "movimentacoes_financeiras_auditoria") if "movimentacoes_financeiras_auditoria" in existing else 0
    movement_item = next((item for item in items if item["table"] == "movimentacoes_financeiras"), None)
    if movement_item:
        movement_item["associated_audit_records"] = audit_count
    totals = {
        "records": sum(item["records"] for item in items),
        "original_value": str(sum((Decimal(item["original_value"]) for item in items), Decimal("0"))),
        "paid_value": str(sum((Decimal(item["paid_value"]) for item in items), Decimal("0"))),
        "balance": str(sum((Decimal(item["balance"]) for item in items), Decimal("0"))),
        "open_titles": sum(item["open_titles"] for item in items),
        "closed_titles": sum(item["closed_titles"] for item in items),
        "reconciliations": sum(item["reconciliations"] for item in items),
        "bank_movements": sum(item["bank_movements"] for item in items),
        "operational_document_links": sum(item["operational_document_links"] for item in items),
        "import_batches": sum(item["import_batches"] for item in items),
        "associated_audit_records": audit_count,
    }
    by_class = {}
    for item in items:
        bucket = by_class.setdefault(item["functional_class"], {"records": 0, "tables": []})
        bucket["records"] += item["records"]
        bucket["tables"].append(item["table"])
    return {"tables": items, "functional_classes": by_class, "totals": totals}


def _table_checksum(cursor, table, columns, excluded_columns=()):
    excluded = set(excluded_columns)
    names = [item["name"] for item in columns if item["name"] not in excluded]
    if not names:
        return {"records": _count(cursor, table), "sha256": _sha({"records_only": _count(cursor, table)})}
    pk = [item["name"] for item in sorted(columns, key=lambda col: col.get("pk") or 0) if item.get("pk")]
    order = [name for name in pk if name in names] or names
    cursor.execute(
        f"SELECT {','.join(_quote(name) for name in names)} FROM {_quote(table)} "
        f"ORDER BY {','.join(_quote(name) for name in order)}"
    )
    digest = hashlib.sha256()
    count = 0
    while True:
        rows = cursor.fetchmany(500)
        if not rows:
            break
        for row in rows:
            digest.update(_canonical(_row_dict(row, cursor.description)).encode("utf-8"))
            digest.update(b"\n")
            count += 1
    return {"records": count, "sha256": digest.hexdigest()}


def _preservation_snapshot(cursor, schema, ignored_columns=None):
    existing = set(schema["tables"])
    merged_ignored = {
        table: set(columns)
        for table, columns in PRESERVATION_VOLATILE_COLUMNS.items()
    }
    for table, columns in (ignored_columns or {}).items():
        merged_ignored.setdefault(table, set()).update(columns)
    groups = {}
    for group, (exact, prefixes) in PRESERVATION_GROUPS.items():
        tables = sorted({
            table for table in existing
            if table in exact or any(table.startswith(prefix) for prefix in prefixes)
        } - set(TARGET_TABLE_CLASSES) - {AUDIT_TABLE})
        details = {
            table: _table_checksum(cursor, table, schema["columns"][table], merged_ignored.get(table, ()))
            for table in tables
        }
        groups[group] = {
            "tables": details,
            "records": sum(item["records"] for item in details.values()),
            "sha256": _sha(details),
        }
    return groups


def _database_identity():
    if DATABASE_URL:
        parsed = urlparse(DATABASE_URL)
        return {"backend": "postgresql", "host": parsed.hostname, "port": parsed.port, "database": parsed.path.lstrip("/")}
    return {"backend": "sqlite", "file": str(Path(DB_NAME).resolve())}


def _environment_name():
    if os.getenv("RENDER"):
        return "production-render"
    return os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "local"


def _commit_id():
    for key in ("RENDER_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"):
        if os.getenv(key):
            return os.getenv(key)
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True,
            text=True, timeout=10, cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()
    except Exception:
        return "unknown"


def _state_hash(schema_hash, inventory, preservation):
    return _sha({"schema_hash": schema_hash, "inventory": inventory, "preservation": preservation})


def build_dry_run(cursor=None):
    own_connection = cursor is None
    conn = conectar() if own_connection else None
    cursor = cursor or conn.cursor()
    try:
        schema, targets, order, detach, blockers = _discover(cursor)
        schema_hash = _sha(schema)
        inventory = _inventory(cursor, targets, schema)
        ignored_columns = {}
        for link in detach:
            ignored_columns.setdefault(link["child_table"], set()).add(link["child_column"])
        preservation = _preservation_snapshot(cursor, schema, ignored_columns)
        report = {
            "report_version": REPORT_VERSION,
            "operation": "RESET_FINANCEIRO_FRIGODATTA",
            "mode": "dry-run",
            "generated_at": _now_iso(),
            "environment": _environment_name(),
            "commit": _commit_id(),
            "database": _database_identity(),
            "schema_hash": schema_hash,
            "state_hash": _state_hash(schema_hash, inventory, preservation),
            "target_tables": targets,
            "delete_order": order,
            "operational_links_to_detach": detach,
            "preserved_financial_tables": sorted(set(schema["tables"]) & PRESERVED_FINANCIAL_TABLES),
            "protected_operational_tables": sorted(set(schema["tables"]) & PROTECTED_OPERATIONAL_TABLES),
            "inventory_before": inventory,
            "preservation_before": preservation,
            "blockers": blockers,
            "executable": not blockers,
        }
        report["dry_run_hash"] = _sha(report)
        return report
    finally:
        if own_connection:
            conn.close()


def write_report(report, path):
    destination = Path(path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(destination)


def load_verified_dry_run(path):
    source = Path(path).resolve()
    if not source.is_file():
        raise ResetSafetyError(f"Relatorio de dry-run nao encontrado: {source}")
    report = json.loads(source.read_text(encoding="utf-8"))
    expected = report.pop("dry_run_hash", None)
    actual = _sha(report)
    report["dry_run_hash"] = expected
    if not expected or expected != actual:
        raise ResetSafetyError("Hash interno do relatorio de dry-run invalido.")
    if report.get("report_version") != REPORT_VERSION or report.get("operation") != "RESET_FINANCEIRO_FRIGODATTA":
        raise ResetSafetyError("Relatorio de dry-run incompativel.")
    if not report.get("executable") or report.get("blockers"):
        raise ResetSafetyError("Dry-run possui condicoes de parada.")
    return report


def _backup_sqlite(backup_dir):
    source = Path(DB_NAME).resolve()
    if not source.is_file():
        raise ResetSafetyError(f"Banco SQLite nao encontrado: {source}")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = Path(backup_dir).resolve() / f"frigodatta_finance_reset_{stamp}_{uuid.uuid4().hex[:8]}.sqlite3"
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = None
    dst = None
    try:
        src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(destination)
        src.backup(dst)
        check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise ResetSafetyError(f"Backup SQLite falhou na verificacao de integridade: {check}")
    except Exception:
        if dst is not None:
            dst.close()
            dst = None
        if src is not None:
            src.close()
            src = None
        if destination.exists():
            destination.unlink()
        raise
    finally:
        if dst is not None:
            dst.close()
        if src is not None:
            src.close()
    return destination, {"verification": "PRAGMA integrity_check=ok"}


def _backup_postgres(backup_dir):
    pg_dump = shutil.which("pg_dump")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_restore:
        raise ResetSafetyError("pg_dump e pg_restore sao obrigatorios para backup restauravel em PostgreSQL.")
    parsed = urlparse(DATABASE_URL)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = Path(backup_dir).resolve() / f"frigodatta_finance_reset_{stamp}_{uuid.uuid4().hex[:8]}.dump"
    destination.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PGPASSWORD"] = unquote(parsed.password or "")
    command = [
        pg_dump, "--format=custom", "--no-owner", "--no-acl",
        "--host", parsed.hostname or "localhost", "--port", str(parsed.port or 5432),
        "--username", unquote(parsed.username or ""), "--dbname", parsed.path.lstrip("/"),
        "--file", str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, env=env, timeout=1800)
        verification = subprocess.run(
            [pg_restore, "--list", str(destination)], check=True, capture_output=True,
            text=True, timeout=120,
        )
    except Exception:
        if destination.exists():
            destination.unlink()
        raise
    if not verification.stdout.strip():
        raise ResetSafetyError("pg_restore nao reconheceu objetos no backup.")
    return destination, {"verification": "pg_restore --list=ok", "objects_listed": len(verification.stdout.splitlines())}


def create_full_backup(backup_dir):
    destination, verification = _backup_postgres(backup_dir) if DATABASE_URL else _backup_sqlite(backup_dir)
    manifest = {
        "backup_id": destination.stem,
        "created_at": _now_iso(),
        "database": _database_identity(),
        "file": str(destination),
        "size_bytes": destination.stat().st_size,
        "sha256": _file_sha(destination),
        **verification,
    }
    manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_file"] = str(manifest_path)
    return manifest


def _ensure_audit_table(cursor):
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
            id {id_type}, evento_id TEXT NOT NULL UNIQUE,
            executado_em {timestamp_type} NOT NULL,
            executor TEXT NOT NULL, commit_id TEXT NOT NULL,
            ambiente TEXT NOT NULL, motivo TEXT NOT NULL,
            backup_id TEXT NOT NULL, backup_sha256 TEXT NOT NULL,
            dry_run_hash TEXT NOT NULL UNIQUE,
            inventario_antes TEXT NOT NULL, inventario_depois TEXT NOT NULL,
            preservacao_antes TEXT NOT NULL, preservacao_depois TEXT NOT NULL,
            resultado TEXT NOT NULL, relatorio_final TEXT NOT NULL
        )
    """)


def _lock_for_reset(cursor, tables, detach):
    if DATABASE_URL:
        lock_tables = sorted(set(tables) | {item["child_table"] for item in detach})
        if lock_tables:
            cursor.execute("LOCK TABLE " + ",".join(_quote(table) for table in lock_tables) + " IN ACCESS EXCLUSIVE MODE")
    else:
        cursor.execute("BEGIN IMMEDIATE")


def _validate_no_orphans(cursor):
    if DATABASE_URL:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        return []
    cursor.execute("PRAGMA foreign_key_check")
    return [list(row) for row in cursor.fetchall()]


def _assert_preserved(before, after):
    differences = {}
    for group in before:
        if before[group] != after.get(group):
            differences[group] = {"before": before[group], "after": after.get(group)}
    if differences:
        raise ResetSafetyError("Divergencia nos modulos preservados: " + ", ".join(sorted(differences)))


def execute_reset(*, confirmation, dry_run_report, backup_dir, reason, executor="CLI administrativo", fail_after_table=None):
    if confirmation != CONFIRMATION_TOKEN:
        raise ResetSafetyError(f"Confirmacao invalida. Use --confirm {CONFIRMATION_TOKEN}.")
    if not str(reason or "").strip():
        raise ResetSafetyError("Motivo auditavel obrigatorio.")
    approved = load_verified_dry_run(dry_run_report)

    approval_mismatches = []
    for field, current_value in (
        ("database", _database_identity()),
        ("environment", _environment_name()),
        ("commit", _commit_id()),
    ):
        if approved.get(field) != current_value:
            approval_mismatches.append(field)
    if approval_mismatches:
        raise ResetSafetyError(
            "Dry-run pertence a outro contexto de execucao: " + ", ".join(approval_mismatches) + "."
        )

    current = build_dry_run()
    if current["blockers"] or current["state_hash"] != approved["state_hash"]:
        raise ResetSafetyError("Estado do banco divergiu do dry-run aprovado; gere novo relatorio.")
    if current["inventory_before"]["totals"]["records"] == 0:
        return {
            "result": "ALREADY_ZERO", "dry_run_hash": approved["dry_run_hash"],
            "inventory_before": current["inventory_before"], "inventory_after": current["inventory_before"],
            "preservation_before": current["preservation_before"], "preservation_after": current["preservation_before"],
        }

    backup = create_full_backup(backup_dir)
    conn = conectar()
    cursor = conn.cursor()
    try:
        _lock_for_reset(cursor, current["target_tables"], current["operational_links_to_detach"])
        locked = build_dry_run(cursor)
        if locked["blockers"] or locked["state_hash"] != approved["state_hash"]:
            raise ResetSafetyError("Estado mudou entre backup e bloqueio transacional; reset abortado.")

        before_inventory = locked["inventory_before"]
        before_preservation = locked["preservation_before"]
        for link in locked["operational_links_to_detach"]:
            cursor.execute(
                f"UPDATE {_quote(link['child_table'])} SET {_quote(link['child_column'])}=NULL "
                f"WHERE {_quote(link['child_column'])} IS NOT NULL"
            )
        deleted = []
        for table in locked["delete_order"]:
            cursor.execute(f"DELETE FROM {_quote(table)}")
            deleted.append({"table": table, "records": int(cursor.rowcount if cursor.rowcount >= 0 else 0)})
            if fail_after_table and table == fail_after_table:
                raise RuntimeError("Falha intermediaria injetada para teste de rollback.")

        schema_after, targets_after, _, _, blockers_after = _discover(cursor)
        if blockers_after:
            raise ResetSafetyError("Dependencias financeiras desconhecidas surgiram durante a transacao.")
        after_inventory = _inventory(cursor, targets_after, schema_after)
        ignored_columns = {}
        for link in locked["operational_links_to_detach"]:
            ignored_columns.setdefault(link["child_table"], set()).add(link["child_column"])
        after_preservation = _preservation_snapshot(cursor, schema_after, ignored_columns)
        _assert_preserved(before_preservation, after_preservation)
        if after_inventory["totals"]["records"] != 0:
            raise ResetSafetyError("Validacao final encontrou registros financeiros residuais.")
        orphans = _validate_no_orphans(cursor)
        if orphans:
            raise ResetSafetyError(f"Validacao final encontrou chaves estrangeiras invalidas: {orphans[:10]}")

        _ensure_audit_table(cursor)
        final_report = {
            "result": "SUCCESS", "completed_at": _now_iso(), "deleted": deleted,
            "detached_operational_links": locked["operational_links_to_detach"],
            "cache_invalidation": "Nenhum cache persistente financeiro identificado; caches de relatorio sao locais por requisicao.",
            "orphans": [], "financial_imports_enabled": False,
        }
        event_id = str(uuid.uuid4())
        cursor.execute(q(f"""
            INSERT INTO {AUDIT_TABLE} (
                evento_id,executado_em,executor,commit_id,ambiente,motivo,
                backup_id,backup_sha256,dry_run_hash,inventario_antes,inventario_depois,
                preservacao_antes,preservacao_depois,resultado,relatorio_final
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """), (
            event_id, _now_iso(), executor, _commit_id(), _environment_name(), reason.strip(),
            backup["backup_id"], backup["sha256"], approved["dry_run_hash"],
            _canonical(before_inventory), _canonical(after_inventory),
            _canonical(before_preservation), _canonical(after_preservation),
            "SUCCESS", _canonical(final_report),
        ))
        conn.commit()
        return {
            **final_report, "audit_event_id": event_id, "backup": backup,
            "dry_run_hash": approved["dry_run_hash"],
            "inventory_before": before_inventory, "inventory_after": after_inventory,
            "preservation_before": before_preservation, "preservation_after": after_preservation,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def financial_imports_blocked():
    """Importacoes antigas ficam desabilitadas depois do reset bem-sucedido."""
    conn = conectar()
    cursor = conn.cursor()
    try:
        if AUDIT_TABLE not in set(_tables(cursor)):
            return False
        cursor.execute(f"SELECT COUNT(*) AS total FROM {AUDIT_TABLE} WHERE resultado='SUCCESS'")
        return int(_row_dict(cursor.fetchone(), cursor.description)["total"] or 0) > 0
    finally:
        conn.close()


def require_financial_imports_enabled():
    if financial_imports_blocked():
        raise ResetSafetyError(
            "Importacoes financeiras permanecem desabilitadas apos o reset P0; "
            "aguarde a nova integracao Sankhya -> FrigoDatta."
        )
