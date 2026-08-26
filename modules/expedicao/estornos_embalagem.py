"""Estornos auditaveis da Embalagem Secundaria.

Os movimentos originais nunca sao apagados. Cada saida de PI e compensada por
uma entrada vinculada, enquanto a caixa permanece no historico como Estornada.
"""

from datetime import datetime
from decimal import Decimal
import json
import os

from database import DATABASE_URL, conectar, q, transaction


PERFIS_ESTORNO = {"admin", "pcp", "gerencia"}
STATUS_INATIVOS = {"CANCELADA", "CANCELADO", "ESTORNADA", "ESTORNADO"}
_SCHEMA_ESTORNOS_INICIALIZADO = False


def funcionalidade_estorno_habilitada():
    return os.getenv("SECONDARY_PACKAGING_BOX_REVERSAL_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on", "sim",
    }


def _agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _decimal(valor):
    return Decimal(str(valor or 0))


def _json(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


def _alterar(cursor, postgres_sql, sqlite_sql):
    try:
        cursor.execute(postgres_sql if DATABASE_URL else sqlite_sql)
    except Exception as erro:
        if DATABASE_URL:
            raise
        if "duplicate column" not in str(erro).lower():
            raise


def criar_tabelas_estornos_embalagem():
    """Estrutura aditiva; tambem existe como migration SQL versionada."""
    global _SCHEMA_ESTORNOS_INICIALIZADO
    if _SCHEMA_ESTORNOS_INICIALIZADO:
        return
    conn = conectar()
    cursor = conn.cursor()
    try:
        id_pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
        timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"
        _alterar(cursor,
            "ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS estornada_em TIMESTAMP",
            "ALTER TABLE pa_caixas ADD COLUMN estornada_em TEXT")
        for nome in ("estornada_por", "estorno_motivo"):
            _alterar(cursor,
                f"ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS {nome} TEXT",
                f"ALTER TABLE pa_caixas ADD COLUMN {nome} TEXT")
        _alterar(cursor,
            "ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS estorno_evento_id INTEGER",
            "ALTER TABLE pa_caixas ADD COLUMN estorno_evento_id INTEGER")
        _alterar(cursor,
            "ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS versao INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE pa_caixas ADD COLUMN versao INTEGER NOT NULL DEFAULT 0")

        for nome, tipo in (("caixa_id", "INTEGER"), ("movimento_origem_id", "INTEGER")):
            _alterar(cursor,
                f"ALTER TABLE estoque_produto_intermediario ADD COLUMN IF NOT EXISTS {nome} {tipo}",
                f"ALTER TABLE estoque_produto_intermediario ADD COLUMN {nome} {tipo}")
        _alterar(cursor,
            "ALTER TABLE estoque_produto_intermediario ADD COLUMN IF NOT EXISTS idempotency_key TEXT",
            "ALTER TABLE estoque_produto_intermediario ADD COLUMN idempotency_key TEXT")
        _alterar(cursor,
            "ALTER TABLE estoque_eventos ADD COLUMN IF NOT EXISTS evento_origem_id INTEGER",
            "ALTER TABLE estoque_eventos ADD COLUMN evento_origem_id INTEGER")
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
        CREATE TABLE IF NOT EXISTS embalagem_secundaria_estornos (
            id {id_pk},
            tipo TEXT NOT NULL,
            op_id INTEGER NOT NULL,
            caixa_id INTEGER,
            idempotency_key TEXT NOT NULL UNIQUE,
            usuario TEXT NOT NULL,
            perfil TEXT NOT NULL,
            justificativa TEXT NOT NULL,
            status_anterior TEXT,
            status_posterior TEXT,
            snapshot_json TEXT NOT NULL,
            movimentos_json TEXT NOT NULL,
            totais_antes_json TEXT NOT NULL,
            totais_depois_json TEXT NOT NULL,
            resultado_json TEXT NOT NULL,
            ip_origem TEXT,
            criado_em {timestamp_type} NOT NULL
        )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_estorno_caixa_data ON embalagem_secundaria_estornos(caixa_id, criado_em)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_estorno_op_data ON embalagem_secundaria_estornos(op_id, criado_em)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_pi_caixa_tipo ON estoque_produto_intermediario(caixa_id, tipo)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_pi_estorno_idempotencia ON estoque_produto_intermediario(idempotency_key) WHERE idempotency_key IS NOT NULL")
        conn.commit()
        _SCHEMA_ESTORNOS_INICIALIZADO = True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _bloqueio_sql():
    return " FOR UPDATE" if DATABASE_URL else ""


def _validar_entrada(usuario, perfil, justificativa, idempotency_key):
    if not funcionalidade_estorno_habilitada():
        raise PermissionError("O estorno da Embalagem Secundária está desativado.")
    if str(perfil or "").lower() not in PERFIS_ESTORNO:
        raise PermissionError("Seu perfil não possui permissão para estornar caixas da Embalagem Secundária.")
    if not str(usuario or "").strip():
        raise ValueError("Usuário responsável não identificado.")
    if not str(justificativa or "").strip():
        raise ValueError("Informe a justificativa do estorno.")
    if len(str(justificativa).strip()) < 5:
        raise ValueError("A justificativa do estorno deve ser objetiva e possuir ao menos 5 caracteres.")
    if not str(idempotency_key or "").strip():
        raise ValueError("Chave de idempotência obrigatória.")


def _totais_op(cursor, op_id):
    cursor.execute(q("""
        SELECT cx.id, comp.quantidade_bandejas, cx.peso_bruto, cx.peso_liquido
        FROM pa_caixa_composicao comp
        JOIN pa_caixas cx ON cx.id=comp.caixa_id
        WHERE comp.op_id=?
          AND UPPER(COALESCE(cx.status,'')) NOT IN ('CANCELADA','CANCELADO','ESTORNADA','ESTORNADO')
    """), (op_id,))
    linhas = cursor.fetchall()
    return {
        "caixas": len({int(linha["id"]) for linha in linhas}),
        "bandejas": str(sum((_decimal(linha["quantidade_bandejas"]) for linha in linhas), Decimal("0"))),
        "peso_bruto": str(sum((_decimal(linha["peso_bruto"]) for linha in linhas), Decimal("0"))),
        "peso_liquido": str(sum((_decimal(linha["peso_liquido"]) for linha in linhas), Decimal("0"))),
    }


def _resultado_idempotente(cursor, chave):
    cursor.execute(q("SELECT resultado_json FROM embalagem_secundaria_estornos WHERE idempotency_key=?"), (chave,))
    existente = cursor.fetchone()
    return json.loads(existente["resultado_json"]) if existente else None


def _carregar_contexto(cursor, op_id, caixa_id):
    cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + _bloqueio_sql()), (op_id,))
    op = cursor.fetchone()
    if not op:
        raise ValueError("OP não encontrada.")
    if str(op["status"] or "").upper() in STATUS_INATIVOS:
        raise ValueError("A OP já está estornada ou cancelada; nenhuma movimentação foi realizada.")

    cursor.execute(q("SELECT * FROM pa_caixas WHERE id=?" + _bloqueio_sql()), (caixa_id,))
    caixa = cursor.fetchone()
    if not caixa:
        raise ValueError("Caixa não encontrada.")
    cursor.execute(q("SELECT * FROM pa_caixa_composicao WHERE caixa_id=? ORDER BY id" + _bloqueio_sql()), (caixa_id,))
    composicoes = cursor.fetchall()
    ops = {int(item["op_id"]) for item in composicoes}
    if int(op_id) not in ops:
        raise ValueError("A caixa informada não pertence à OP selecionada.")
    if len(ops) != 1:
        raise ValueError("A caixa utiliza bandejas de múltiplas OPs e exige correção administrativa específica.")
    if str(caixa["status"] or "").upper() in STATUS_INATIVOS:
        raise ValueError("A caixa já foi estornada ou cancelada; nenhuma movimentação foi realizada.")
    return op, caixa, composicoes


def _buscar_bloqueios(cursor, caixa):
    caixa_id = caixa["id"]
    bloqueios = []
    cursor.execute(q("""SELECT e.numero_romaneio,e.status FROM expedicao_itens i
        JOIN expedicoes e ON e.id=i.expedicao_id WHERE i.caixa_id=? ORDER BY e.id"""), (caixa_id,))
    for item in cursor.fetchall():
        bloqueios.append(f"A caixa está vinculada ao Romaneio nº {item['numero_romaneio']} ({item['status']}).")
    cursor.execute(q("SELECT tipo FROM pa_movimentacoes WHERE caixa_id=? ORDER BY id"), (caixa_id,))
    for item in cursor.fetchall():
        bloqueios.append(f"A caixa possui movimentação posterior de estoque: {item['tipo']}.")
    cursor.execute(q("SELECT id,status FROM pa_nao_conformes WHERE caixa_id=? ORDER BY id"), (caixa_id,))
    for item in cursor.fetchall():
        bloqueios.append(f"A caixa está vinculada ao Produto Não Conforme nº {item['id']} ({item['status']}).")
    cursor.execute(q("""SELECT acao FROM estoque_eventos WHERE caixa_id=?
        AND acao NOT IN ('FORMACAO_ESTOQUE','ESTORNO_CAIXA_EMBALAGEM') ORDER BY id"""), (caixa_id,))
    for item in cursor.fetchall():
        bloqueios.append(f"A caixa possui evento sucessor de estoque: {item['acao']}.")
    if caixa["reservado_expedicao_id"]:
        bloqueios.append(f"A caixa está reservada pelo romaneio interno #{caixa['reservado_expedicao_id']}.")
    if _decimal(caixa["quantidade_pacotes_reservados"]) > 0:
        bloqueios.append(f"A caixa possui {caixa['quantidade_pacotes_reservados']} unidades reservadas.")
    disponibilidade = str(caixa["disponibilidade"] or "PENDENTE_OP").upper()
    if disponibilidade not in {"PENDENTE_OP", "DISPONIVEL"}:
        bloqueios.append(f"A caixa está na situação operacional {disponibilidade}.")
    return list(dict.fromkeys(bloqueios))


def _movimentos_pi_originais(cursor, op_id, caixa_id, composicoes):
    cursor.execute(q("""SELECT * FROM estoque_produto_intermediario
        WHERE op_id=? AND tipo='SAIDA_EMBALAGEM_SECUNDARIA'
          AND (caixa_id=? OR (caixa_id IS NULL AND observacoes LIKE ?)) ORDER BY id"""),
        (op_id, caixa_id, f"%caixa PA #{caixa_id}.%"))
    movimentos = cursor.fetchall()
    esperado = sum((_decimal(item["quantidade_bandejas"]) for item in composicoes), Decimal("0"))
    encontrado = sum((_decimal(item["quantidade_bandejas"]) for item in movimentos), Decimal("0"))
    if not movimentos or encontrado != esperado:
        raise ValueError(
            f"Os movimentos originais de PI da caixa não estão íntegros: esperado {esperado}, encontrado {encontrado}."
        )
    return movimentos


def _inserir_evento_estoque(cursor, caixa, justificativa, chave, usuario, perfil,
                            evento_origem_id=None):
    cursor.execute(q("""INSERT INTO estoque_eventos(
        caixa_id,acao,situacao_anterior,situacao_nova,condicao_anterior,condicao_nova,
        quantidade,peso,justificativa,observacao,usuario,perfil,criado_em,idempotency_key,evento_origem_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?, ?,?,?,?)"""),
        (caixa["id"], "ESTORNO_CAIXA_EMBALAGEM", caixa["disponibilidade"], "ESTORNADO",
         caixa["condicao"], caixa["condicao"], 1, str(_decimal(caixa["peso_liquido"])),
         justificativa, "Reversão lógica da formação de PA.", usuario, perfil,
         _agora(), chave, evento_origem_id))


def _estornar_caixa_cursor(cursor, op_id, caixa_id, usuario, perfil, justificativa,
                           idempotency_key, ip_origem=None, ajustar_op=True):
    op, caixa, composicoes = _carregar_contexto(cursor, op_id, caixa_id)
    bloqueios = _buscar_bloqueios(cursor, caixa)
    if bloqueios:
        raise ValueError("Estorno bloqueado: " + " ".join(bloqueios))
    movimentos = _movimentos_pi_originais(cursor, op_id, caixa_id, composicoes)
    antes = _totais_op(cursor, op_id)
    status_anterior = op["status"]
    agora = _agora()

    reversoes = []
    for movimento in movimentos:
        chave_mov = f"{idempotency_key}:PI:{movimento['id']}"
        cursor.execute(q("""INSERT INTO estoque_produto_intermediario(
            data_movimentacao,tipo,op_id,sku,quantidade_bandejas,origem,observacoes,
            caixa_id,movimento_origem_id,idempotency_key)
            VALUES(?,?,?,?,?,?,?,?,?,?)"""),
            (agora[:10], "ENTRADA_ESTORNO_CAIXA", op_id, movimento["sku"],
             str(_decimal(movimento["quantidade_bandejas"])), "Estorno Embalagem Secundária",
             f"Reversão do movimento PI #{movimento['id']} da caixa PA #{caixa_id}.",
             caixa_id, movimento["id"], chave_mov))
        reversoes.append({"original": movimento["id"], "idempotency_key": chave_mov,
                          "bandejas": str(_decimal(movimento["quantidade_bandejas"]))})

    cursor.execute(q("SELECT id FROM estoque_eventos WHERE caixa_id=? AND acao='FORMACAO_ESTOQUE' ORDER BY id DESC LIMIT 1"), (caixa_id,))
    formacao = cursor.fetchone()
    cursor.execute(q("""UPDATE pa_caixas SET status='Estornada', estoque_operacional=0,
        disponibilidade='ESTORNADO', reservado_expedicao_id=NULL, estornada_em=?,
        estornada_por=?, estorno_motivo=?, versao=COALESCE(versao,0)+1
        WHERE id=? AND UPPER(COALESCE(status,'')) NOT IN ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO')"""),
        (agora, usuario, justificativa.strip(), caixa_id))
    if cursor.rowcount != 1:
        raise ValueError("A caixa foi alterada concorrentemente; atualize a tela e tente novamente.")
    from modules.label_printing.services import invalidar_jobs_caixa_cursor
    invalidar_jobs_caixa_cursor(cursor, caixa_id)

    status_posterior = status_anterior
    if ajustar_op and str(status_anterior) == "Encerrada":
        status_posterior = "Aberta"
        cursor.execute(q("UPDATE ordens_producao SET status=? WHERE id=? AND status='Encerrada'"), (status_posterior, op_id))
        if cursor.rowcount != 1:
            raise ValueError("A OP foi alterada concorrentemente; o estorno foi cancelado.")
        cursor.execute(q("""UPDATE apontamentos_producao SET vigente=0,invalidado_em=?,invalidado_por=?
            WHERE op_id=? AND COALESCE(vigente,1)=1 AND (
            observacoes LIKE 'Gerado automaticamente no encerramento da OP%%'
            OR observacoes LIKE 'Produção final informada no encerramento da OP%%'
            OR observacoes LIKE 'Kg final produzido informado no encerramento da OP%%')"""), (_agora(), usuario, op_id))

    depois = _totais_op(cursor, op_id)
    snapshot = {chave: caixa[chave] for chave in (
        "id", "codigo_caixa", "sku", "data_fabricacao", "data_validade", "peso_bruto",
        "peso_liquido", "peso_tara", "quantidade_bandejas", "status", "disponibilidade")}
    for campo in ("peso_bruto", "peso_liquido", "peso_tara", "quantidade_bandejas"):
        snapshot[campo] = str(_decimal(snapshot[campo]))
    resultado = {"sucesso": True, "caixa_id": caixa_id, "codigo_caixa": caixa["codigo_caixa"],
                 "op_id": op_id, "status_op_anterior": status_anterior,
                 "status_op_posterior": status_posterior, "totais_antes": antes,
                 "totais_depois": depois, "movimentos_revertidos": reversoes}
    sql_auditoria = """INSERT INTO embalagem_secundaria_estornos(
        tipo,op_id,caixa_id,idempotency_key,usuario,perfil,justificativa,status_anterior,
        status_posterior,snapshot_json,movimentos_json,totais_antes_json,totais_depois_json,
        resultado_json,ip_origem,criado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    if DATABASE_URL:
        sql_auditoria += " RETURNING id"
    cursor.execute(q(sql_auditoria),
        ("CAIXA", op_id, caixa_id, idempotency_key, usuario, perfil, justificativa.strip(),
         status_anterior, status_posterior, _json(snapshot), _json(reversoes), _json(antes),
         _json(depois), _json(resultado), ip_origem, agora))
    evento_id = cursor.fetchone()["id"] if DATABASE_URL else cursor.lastrowid
    cursor.execute(q("UPDATE pa_caixas SET estorno_evento_id=? WHERE id=?"), (evento_id, caixa_id))
    _inserir_evento_estoque(cursor, caixa, justificativa, f"ESTORNO-PA-{caixa_id}", usuario, perfil,
                            formacao["id"] if formacao else None)
    return resultado


def estornar_caixa_embalagem_secundaria(op_id, caixa_id, *, usuario, perfil,
                                        justificativa, idempotency_key, ip_origem=None):
    _validar_entrada(usuario, perfil, justificativa, idempotency_key)
    criar_tabelas_estornos_embalagem()
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            return existente
        return _estornar_caixa_cursor(cursor, int(op_id), int(caixa_id), usuario, perfil,
                                      justificativa, idempotency_key, ip_origem)


def estornar_caixas_embalagem_secundaria_em_lote(op_id, caixa_ids, *, usuario, perfil,
                                                  justificativa, idempotency_key,
                                                  ip_origem=None):
    """Estorna um conjunto explicito de caixas em uma unica transacao."""
    _validar_entrada(usuario, perfil, justificativa, idempotency_key)
    try:
        ids = [int(item) for item in caixa_ids]
    except (TypeError, ValueError):
        raise ValueError("A seleção contém uma caixa inválida.")
    if not ids:
        raise ValueError("Selecione ao menos uma caixa para estornar.")
    if len(ids) != len(set(ids)):
        raise ValueError("A mesma caixa foi informada mais de uma vez.")
    ids = sorted(ids)
    criar_tabelas_estornos_embalagem()
    with transaction() as conn:
        cursor = conn.cursor()
        existente = _resultado_idempotente(cursor, idempotency_key)
        if existente:
            return existente
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?" + _bloqueio_sql()), (op_id,))
        op = cursor.fetchone()
        if not op:
            raise ValueError("OP não encontrada.")
        # Preflight integral antes da primeira mutacao.
        caixas = []
        for caixa_id in ids:
            _, caixa, composicoes = _carregar_contexto(cursor, op_id, caixa_id)
            bloqueios = _buscar_bloqueios(cursor, caixa)
            if bloqueios:
                raise ValueError(f"A caixa {caixa['codigo_caixa']} bloqueou o lote: " + " ".join(bloqueios))
            _movimentos_pi_originais(cursor, op_id, caixa_id, composicoes)
            caixas.append(caixa)
        antes = _totais_op(cursor, op_id)
        resultados = []
        for indice, caixa_id in enumerate(ids, start=1):
            resultados.append(_estornar_caixa_cursor(
                cursor, op_id, caixa_id, usuario, perfil, justificativa,
                f"{idempotency_key}:CAIXA:{indice}", ip_origem, ajustar_op=False))
        status_posterior = op["status"]
        if str(op["status"] or "") == "Encerrada":
            status_posterior = "Aberta"
            cursor.execute(q("UPDATE ordens_producao SET status='Aberta' WHERE id=? AND status='Encerrada'"), (op_id,))
            if cursor.rowcount != 1:
                raise ValueError("A OP foi alterada concorrentemente; o lote foi cancelado.")
            cursor.execute(q("""UPDATE apontamentos_producao SET vigente=0,invalidado_em=?,invalidado_por=?
                WHERE op_id=? AND COALESCE(vigente,1)=1 AND (
                observacoes LIKE 'Gerado automaticamente no encerramento da OP%%'
                OR observacoes LIKE 'Produção final informada no encerramento da OP%%'
                OR observacoes LIKE 'Kg final produzido informado no encerramento da OP%%')"""), (_agora(), usuario, op_id))
        depois = _totais_op(cursor, op_id)
        resultado = {
            "sucesso": True, "op_id": int(op_id), "caixas_estornadas": len(ids),
            "caixa_ids": ids, "status_op_anterior": op["status"],
            "status_op_posterior": status_posterior, "totais_antes": antes,
            "totais_depois": depois, "caixas": resultados,
            "impacto": {
                "bandejas": str(_decimal(antes["bandejas"]) - _decimal(depois["bandejas"])),
                "peso_bruto": str(_decimal(antes["peso_bruto"]) - _decimal(depois["peso_bruto"])),
                "peso_liquido": str(_decimal(antes["peso_liquido"]) - _decimal(depois["peso_liquido"])),
            },
        }
        cursor.execute(q("""INSERT INTO embalagem_secundaria_estornos(
            tipo,op_id,caixa_id,idempotency_key,usuario,perfil,justificativa,status_anterior,
            status_posterior,snapshot_json,movimentos_json,totais_antes_json,totais_depois_json,
            resultado_json,ip_origem,criado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
            ("LOTE", op_id, None, idempotency_key, usuario, perfil, justificativa.strip(),
             op["status"], status_posterior, _json({"caixa_ids": ids}), _json(resultados),
             _json(antes), _json(depois), _json(resultado), ip_origem, _agora()))
        return resultado


def estornar_op_embalagem_secundaria(op_id, *, usuario, perfil, justificativa,
                                     idempotency_key, ip_origem=None):
    _validar_entrada(usuario, perfil, justificativa, idempotency_key)
    criar_tabelas_estornos_embalagem()
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
            raise ValueError("A OP já está estornada ou cancelada; nenhuma movimentação foi realizada.")
        cursor.execute(q("""SELECT cx.id FROM pa_caixas cx JOIN pa_caixa_composicao c ON c.caixa_id=cx.id
            WHERE c.op_id=? AND UPPER(COALESCE(cx.status,'')) NOT IN
            ('ESTORNADA','ESTORNADO','CANCELADA','CANCELADO') ORDER BY cx.id""" + _bloqueio_sql()), (op_id,))
        caixas_ids = [item["id"] for item in cursor.fetchall()]

        # Preflight completo antes da primeira mutacao garante mensagem e atomicidade previsiveis.
        for caixa_id in caixas_ids:
            _, caixa, composicoes = _carregar_contexto(cursor, op_id, caixa_id)
            bloqueios = _buscar_bloqueios(cursor, caixa)
            if bloqueios:
                raise ValueError(f"A OP não pode ser estornada por causa da caixa {caixa['codigo_caixa']}: " + " ".join(bloqueios))
            _movimentos_pi_originais(cursor, op_id, caixa_id, composicoes)

        antes = _totais_op(cursor, op_id)
        resultados = []
        for indice, caixa_id in enumerate(caixas_ids, start=1):
            resultados.append(_estornar_caixa_cursor(
                cursor, op_id, caixa_id, usuario, perfil, justificativa,
                f"{idempotency_key}:CAIXA:{indice}", ip_origem, ajustar_op=False))
        cursor.execute(q("UPDATE ordens_producao SET status='Estornada' WHERE id=?"), (op_id,))
        cursor.execute(q("""UPDATE apontamentos_producao SET vigente=0,invalidado_em=?,invalidado_por=?
            WHERE op_id=? AND COALESCE(vigente,1)=1 AND (
            observacoes LIKE 'Gerado automaticamente no encerramento da OP%%'
            OR observacoes LIKE 'Produção final informada no encerramento da OP%%'
            OR observacoes LIKE 'Kg final produzido informado no encerramento da OP%%')"""), (_agora(), usuario, op_id))
        depois = _totais_op(cursor, op_id)
        resultado = {"sucesso": True, "op_id": op_id, "caixas_estornadas": len(resultados),
                     "status_op_anterior": op["status"], "status_op_posterior": "Estornada",
                     "totais_antes": antes, "totais_depois": depois, "caixas": resultados}
        cursor.execute(q("""INSERT INTO embalagem_secundaria_estornos(
            tipo,op_id,caixa_id,idempotency_key,usuario,perfil,justificativa,status_anterior,
            status_posterior,snapshot_json,movimentos_json,totais_antes_json,totais_depois_json,
            resultado_json,ip_origem,criado_em) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""),
            ("OP", op_id, None, idempotency_key, usuario, perfil, justificativa.strip(),
             op["status"], "Estornada", _json({"op_id": op_id, "caixas": caixas_ids}),
             _json(resultados), _json(antes), _json(depois), _json(resultado), ip_origem, _agora()))
        return resultado
