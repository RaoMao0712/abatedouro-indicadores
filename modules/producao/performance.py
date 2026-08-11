"""Performance oficial da Linha de Abate.

Este modulo concentra governanca da velocidade, snapshots, contagem confirmada,
reprocessos e formula. Disponibilidade permanece como unica fonte temporal.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from database import DATABASE_URL, conectar, q
from .disponibilidade import calcular_disponibilidade


FUSO_MANAUS = ZoneInfo("America/Manaus")
LINHA_ABATE = "LINHA_ABATE"
STATUS_VELOCIDADE = {"PROPOSTA", "APROVADA", "ATIVA", "ENCERRADA", "REJEITADA"}
SITUACOES = {"CALCULAVEL", "EM_ANDAMENTO", "NAO_CALCULAVEL", "INCONSISTENTE"}


def agora_manaus():
    return datetime.now(FUSO_MANAUS).replace(microsecond=0)


def _iso(valor=None):
    valor = valor or agora_manaus()
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=FUSO_MANAUS)
    return valor.astimezone(FUSO_MANAUS).isoformat(timespec="seconds")


def _decimal(valor, nome, *, permitir_zero=False):
    if valor is None or str(valor).strip() == "":
        raise ValueError(f"Informe {nome}.")
    try:
        numero = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{nome.capitalize()} invalida.") from exc
    if numero < 0 or (numero == 0 and not permitir_zero):
        regra = "maior ou igual a zero" if permitir_zero else "maior que zero"
        raise ValueError(f"{nome.capitalize()} deve ser {regra}.")
    return numero


def _decimal_armazenado(valor):
    try:
        return Decimal(str(valor))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _data(valor, nome):
    try:
        return date.fromisoformat(str(valor or "").strip())
    except ValueError as exc:
        raise ValueError(f"Informe {nome} valida.") from exc


def _identidade(usuario=None, usuario_id=None, perfil=None):
    return usuario or "Sistema", usuario_id, str(perfil or "sistema").lower()


def _pk():
    return "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"


@contextmanager
def _transacao():
    conn = conectar()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def criar_tabelas_performance():
    conn = conectar()
    cursor = conn.cursor()
    pk = _pk()
    try:
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS linha_abate_velocidades_ideais (
            id {pk}, linha TEXT NOT NULL DEFAULT '{LINHA_ABATE}',
            configuracao TEXT NOT NULL, sku TEXT,
            velocidade_aves_hora TEXT NOT NULL,
            vigencia_inicio TEXT NOT NULL, vigencia_fim TEXT,
            status TEXT NOT NULL DEFAULT 'PROPOSTA',
            justificativa_tecnica TEXT NOT NULL,
            proposto_por TEXT NOT NULL, proposto_por_id INTEGER, proposto_em TEXT NOT NULL,
            aprovado_por TEXT, aprovado_por_id INTEGER, aprovado_em TEXT,
            rejeitado_por TEXT, rejeitado_por_id INTEGER, rejeitado_em TEXT,
            encerrado_por TEXT, encerrado_por_id INTEGER, encerrado_em TEXT,
            justificativa_decisao TEXT, ativo_logico INTEGER NOT NULL DEFAULT 1,
            versao INTEGER NOT NULL DEFAULT 1,
            CHECK (status IN ('PROPOSTA','APROVADA','ATIVA','ENCERRADA','REJEITADA'))
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS linha_performance_snapshots_op (
            id {pk}, op_id INTEGER NOT NULL, velocidade_id INTEGER NOT NULL,
            linha TEXT NOT NULL, configuracao TEXT NOT NULL, sku TEXT,
            velocidade_aves_hora TEXT NOT NULL,
            vigencia_inicio TEXT NOT NULL, vigencia_fim TEXT,
            resolvido_em TEXT NOT NULL, resolvido_por TEXT NOT NULL,
            resolvido_por_id INTEGER, versao INTEGER NOT NULL DEFAULT 1,
            atual INTEGER NOT NULL DEFAULT 1, justificativa_correcao TEXT
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS linha_performance_contagens (
            id {pk}, op_id INTEGER NOT NULL,
            aves_recebidas TEXT NOT NULL, mortes_antes_pendura TEXT NOT NULL,
            aves_processadas TEXT NOT NULL, origem_calculo TEXT NOT NULL,
            confirmado_por TEXT NOT NULL, confirmado_por_id INTEGER,
            confirmado_em TEXT NOT NULL, observacao TEXT,
            versao INTEGER NOT NULL DEFAULT 1, atual INTEGER NOT NULL DEFAULT 1,
            justificativa_correcao TEXT
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS linha_performance_reprocessos (
            id {pk}, op_id INTEGER NOT NULL, quantidade_aves TEXT NOT NULL,
            atravessou_linha INTEGER NOT NULL, data_hora TEXT NOT NULL,
            motivo TEXT NOT NULL, usuario TEXT NOT NULL, usuario_id INTEGER,
            execucao_original TEXT NOT NULL, chave_idempotencia TEXT,
            ativo_logico INTEGER NOT NULL DEFAULT 1,
            CHECK (atravessou_linha IN (0,1))
        )""")
        cursor.execute(f"""CREATE TABLE IF NOT EXISTS linha_performance_auditoria (
            id {pk}, op_id INTEGER, entidade TEXT NOT NULL, entidade_id INTEGER,
            acao TEXT NOT NULL, valor_anterior TEXT, valor_novo TEXT,
            justificativa TEXT, usuario TEXT NOT NULL, usuario_id INTEGER,
            perfil TEXT NOT NULL, criado_em TEXT NOT NULL
        )""")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_velocidade_resolucao ON linha_abate_velocidades_ideais(linha,sku,configuracao,status,vigencia_inicio,vigencia_fim)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_performance_snapshot_op ON linha_performance_snapshots_op(op_id,atual)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_performance_contagem_op ON linha_performance_contagens(op_id,atual)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_performance_reprocesso_op ON linha_performance_reprocessos(op_id,atravessou_linha,ativo_logico)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_performance_auditoria ON linha_performance_auditoria(op_id,criado_em)")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_performance_reprocesso_chave ON linha_performance_reprocessos(op_id,chave_idempotencia) WHERE chave_idempotencia IS NOT NULL")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _auditar(cursor, entidade, entidade_id, acao, anterior, novo, justificativa,
             usuario, usuario_id, perfil, *, op_id=None, criado_em=None):
    cursor.execute(q("""INSERT INTO linha_performance_auditoria
        (op_id,entidade,entidade_id,acao,valor_anterior,valor_novo,justificativa,
         usuario,usuario_id,perfil,criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?)"""), (
        op_id, entidade, entidade_id, acao,
        json.dumps(anterior, ensure_ascii=False, sort_keys=True, default=str) if anterior is not None else None,
        json.dumps(novo, ensure_ascii=False, sort_keys=True, default=str) if novo is not None else None,
        str(justificativa or "").strip() or None, usuario, usuario_id, perfil,
        criado_em or _iso(),
    ))


def _inserir_id(cursor, sql, parametros):
    if DATABASE_URL:
        cursor.execute(q(sql + " RETURNING id"), parametros)
        return cursor.fetchone()["id"]
    cursor.execute(sql, parametros)
    return cursor.lastrowid


def propor_velocidade(configuracao, sku, velocidade_aves_hora, vigencia_inicio,
                       justificativa_tecnica, *, usuario=None, usuario_id=None,
                       perfil=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil not in {"pcp", "gerencia", "admin"}:
        raise PermissionError("Somente PCP, Gerencia ou Administrador podem propor velocidade.")
    configuracao = str(configuracao or "").strip()
    sku = str(sku or "").strip() or None
    justificativa_tecnica = str(justificativa_tecnica or "").strip()
    velocidade = _decimal(velocidade_aves_hora, "velocidade ideal")
    inicio = _data(vigencia_inicio, "inicio da vigencia")
    if not configuracao or not justificativa_tecnica:
        raise ValueError("Informe configuracao e justificativa tecnica.")
    momento = _iso()
    with _transacao() as conn:
        cursor = conn.cursor()
        velocidade_id = _inserir_id(cursor, """INSERT INTO linha_abate_velocidades_ideais
            (linha,configuracao,sku,velocidade_aves_hora,vigencia_inicio,status,
             justificativa_tecnica,proposto_por,proposto_por_id,proposto_em)
            VALUES (?,?,?,?,?,'PROPOSTA',?,?,?,?)""", (
            LINHA_ABATE, configuracao, sku, str(velocidade), inicio.isoformat(),
            justificativa_tecnica, usuario, usuario_id, momento,
        ))
        _auditar(cursor, "VELOCIDADE", velocidade_id, "PROPOSTA", None,
                 {"configuracao": configuracao, "sku": sku,
                  "velocidade_aves_hora": str(velocidade), "vigencia_inicio": inicio.isoformat()},
                 justificativa_tecnica, usuario, usuario_id, perfil)
        return velocidade_id


def _buscar_velocidade(cursor, velocidade_id):
    cursor.execute(q("SELECT * FROM linha_abate_velocidades_ideais WHERE id=? AND ativo_logico=1"), (velocidade_id,))
    return cursor.fetchone()


def decidir_velocidade(velocidade_id, acao, justificativa, *, usuario=None,
                       usuario_id=None, perfil=None, vigencia_fim=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil != "admin":
        raise PermissionError("Somente Administrador pode decidir ou encerrar velocidades.")
    justificativa = str(justificativa or "").strip()
    if not justificativa:
        raise ValueError("A justificativa da decisao e obrigatoria.")
    acao = str(acao or "").strip().upper()
    if acao not in {"APROVAR", "REJEITAR", "ATIVAR", "ENCERRAR"}:
        raise ValueError("Acao de velocidade invalida.")
    with _transacao() as conn:
        cursor = conn.cursor()
        atual = _buscar_velocidade(cursor, velocidade_id)
        if not atual:
            raise ValueError("Velocidade nao encontrada.")
        status_atual = atual["status"]
        momento = _iso()
        if acao == "APROVAR":
            if status_atual != "PROPOSTA":
                raise ValueError("Somente proposta pode ser aprovada.")
            _decimal(atual["velocidade_aves_hora"], "velocidade ideal")
            _data(atual["vigencia_inicio"], "inicio da vigencia")
            novo_status = "APROVADA"
            campos = ("status=?,aprovado_por=?,aprovado_por_id=?,aprovado_em=?,justificativa_decisao=?",
                      (novo_status, usuario, usuario_id, momento, justificativa))
        elif acao == "REJEITAR":
            if status_atual not in {"PROPOSTA", "APROVADA"}:
                raise ValueError("Somente proposta ou aprovada pode ser rejeitada.")
            novo_status = "REJEITADA"
            campos = ("status=?,rejeitado_por=?,rejeitado_por_id=?,rejeitado_em=?,justificativa_decisao=?",
                      (novo_status, usuario, usuario_id, momento, justificativa))
        elif acao == "ATIVAR":
            if status_atual != "APROVADA":
                raise ValueError("Somente velocidade aprovada pode ser ativada.")
            inicio = atual["vigencia_inicio"]
            fim = atual["vigencia_fim"]
            cursor.execute(q("""SELECT id FROM linha_abate_velocidades_ideais
                WHERE id<>? AND ativo_logico=1 AND status='ATIVA' AND linha=?
                  AND configuracao=? AND COALESCE(sku,'')=COALESCE(?, '')
                  AND vigencia_inicio <= COALESCE(?, '9999-12-31')
                  AND COALESCE(vigencia_fim,'9999-12-31') >= ?"""),
                (velocidade_id, atual["linha"], atual["configuracao"], atual["sku"], fim, inicio))
            if cursor.fetchone():
                raise ValueError("Existe vigencia ativa sobreposta para a mesma combinacao.")
            novo_status = "ATIVA"
            campos = ("status=?,justificativa_decisao=?", (novo_status, justificativa))
        else:
            if status_atual != "ATIVA":
                raise ValueError("Somente velocidade ativa pode ter vigencia encerrada.")
            fim_data = _data(vigencia_fim or date.today().isoformat(), "termino da vigencia")
            inicio_data = _data(atual["vigencia_inicio"], "inicio da vigencia")
            if fim_data < inicio_data:
                raise ValueError("Termino da vigencia nao pode anteceder o inicio.")
            if fim_data < date.today():
                raise ValueError("Vigencia passada nao pode ser alterada retroativamente.")
            novo_status = "ENCERRADA"
            campos = ("status=?,vigencia_fim=?,encerrado_por=?,encerrado_por_id=?,encerrado_em=?,justificativa_decisao=?",
                      (novo_status, fim_data.isoformat(), usuario, usuario_id, momento, justificativa))
        cursor.execute(q(f"UPDATE linha_abate_velocidades_ideais SET {campos[0]},versao=versao+1 WHERE id=?"), (*campos[1], velocidade_id))
        _auditar(cursor, "VELOCIDADE", velocidade_id, acao, {"status": status_atual},
                 {"status": novo_status}, justificativa, usuario, usuario_id, perfil)
        return novo_status


def listar_velocidades(filtros=None):
    filtros = filtros or {}
    condicoes = ["ativo_logico=1"]
    parametros = []
    for campo in ("status", "configuracao", "sku"):
        if filtros.get(campo):
            condicoes.append(f"{campo}=?")
            parametros.append(filtros[campo])
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(f"SELECT * FROM linha_abate_velocidades_ideais WHERE {' AND '.join(condicoes)} ORDER BY vigencia_inicio DESC,id DESC"), tuple(parametros))
        return cursor.fetchall()
    finally:
        conn.close()


def listar_skus_operacionais():
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT sku FROM ordens_producao WHERE COALESCE(TRIM(sku),'')<>'' ORDER BY sku")
        return [item["sku"] for item in cursor.fetchall()]
    finally:
        conn.close()


def _op_e_programacao(cursor, op_id):
    cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?"), (op_id,))
    op = cursor.fetchone()
    cursor.execute(q("SELECT * FROM linha_abate_programacoes WHERE op_id=?"), (op_id,))
    return op, cursor.fetchone()


def resolver_velocidade_op(cursor, op, programacao):
    if not op or not programacao:
        return None, "OP sem programacao oficial da Linha de Abate."
    data_referencia = str(programacao["inicio_programado"] or op["data"])[:10]
    cursor.execute(q("""SELECT * FROM linha_abate_velocidades_ideais
        WHERE linha=? AND status='ATIVA' AND ativo_logico=1
          AND vigencia_inicio<=? AND COALESCE(vigencia_fim,'9999-12-31')>=?
          AND (sku=? OR sku IS NULL OR TRIM(sku)='')
        ORDER BY CASE WHEN sku=? THEN 0 ELSE 1 END,id DESC"""),
        (LINHA_ABATE, data_referencia, data_referencia, op["sku"], op["sku"]))
    candidatas = cursor.fetchall()
    if not candidatas:
        return None, "Nao existe velocidade ideal ativa e vigente para a configuracao da OP."
    melhor_prioridade = 0 if str(candidatas[0]["sku"] or "").strip() else 1
    melhores = [item for item in candidatas if (0 if str(item["sku"] or "").strip() else 1) == melhor_prioridade]
    configuracoes = {item["configuracao"] for item in melhores}
    if len(melhores) > 1 or len(configuracoes) > 1:
        return None, "Mais de uma configuracao/velocidade e aplicavel; segmente a OP antes do calculo."
    return melhores[0], None


def preparar_snapshot_inicio(op_id, *, usuario=None, usuario_id=None, perfil=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil not in {"producao", "admin"}:
        raise PermissionError("Somente Producao ou Administrador podem preparar o snapshot da OP.")
    with _transacao() as conn:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM linha_performance_snapshots_op WHERE op_id=? AND atual=1 ORDER BY id DESC"), (op_id,))
        existentes = cursor.fetchall()
        if existentes:
            return existentes[0]["id"]
        op, programacao = _op_e_programacao(cursor, op_id)
        if not op:
            raise ValueError("OP nao encontrada.")
        if str(op["status"] or "").lower() in {"cancelada", "cancelado"}:
            raise ValueError("OP cancelada nao pode receber snapshot de Performance.")
        if programacao and programacao["inicio_real"]:
            raise ValueError("OP ja iniciada sem snapshot nao pode receber preenchimento retroativo.")
        velocidade, motivo = resolver_velocidade_op(cursor, op, programacao)
        if not velocidade:
            raise ValueError(motivo)
        momento = _iso()
        snapshot_id = _inserir_id(cursor, """INSERT INTO linha_performance_snapshots_op
            (op_id,velocidade_id,linha,configuracao,sku,velocidade_aves_hora,
             vigencia_inicio,vigencia_fim,resolvido_em,resolvido_por,resolvido_por_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
            op_id, velocidade["id"], velocidade["linha"], velocidade["configuracao"],
            velocidade["sku"], velocidade["velocidade_aves_hora"],
            velocidade["vigencia_inicio"], velocidade["vigencia_fim"], momento,
            usuario, usuario_id,
        ))
        _auditar(cursor, "SNAPSHOT", snapshot_id, "RESOLUCAO_SNAPSHOT", None,
                 {"velocidade_id": velocidade["id"], "velocidade_aves_hora": velocidade["velocidade_aves_hora"]},
                 None, usuario, usuario_id, perfil, op_id=op_id)
        return snapshot_id


def corrigir_snapshot(op_id, velocidade_id, justificativa, *, usuario=None,
                      usuario_id=None, perfil=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil != "admin":
        raise PermissionError("Somente Administrador pode corrigir snapshot de Performance.")
    justificativa = str(justificativa or "").strip()
    if not justificativa:
        raise ValueError("A justificativa da correcao e obrigatoria.")
    with _transacao() as conn:
        cursor = conn.cursor()
        op, programacao = _op_e_programacao(cursor, op_id)
        if not op:
            raise ValueError("OP nao encontrada.")
        cursor.execute(q("SELECT * FROM linha_performance_snapshots_op WHERE op_id=? AND atual=1 ORDER BY id DESC"), (op_id,))
        anterior = cursor.fetchone()
        velocidade = _buscar_velocidade(cursor, velocidade_id)
        if not velocidade or velocidade["status"] != "ATIVA":
            raise ValueError("Selecione uma velocidade ativa.")
        data_referencia = str((programacao["inicio_programado"] if programacao else op["data"]) or "")[:10]
        sku_velocidade = str(velocidade["sku"] or "").strip()
        if sku_velocidade and sku_velocidade != str(op["sku"] or "").strip():
            raise ValueError("A velocidade selecionada nao corresponde ao SKU/processo da OP.")
        if (velocidade["vigencia_inicio"] > data_referencia
                or str(velocidade["vigencia_fim"] or "9999-12-31") < data_referencia):
            raise ValueError("A velocidade selecionada nao estava vigente para a OP.")
        versao = int(anterior["versao"] if anterior else 0) + 1
        cursor.execute(q("UPDATE linha_performance_snapshots_op SET atual=0 WHERE op_id=? AND atual=1"), (op_id,))
        snapshot_id = _inserir_id(cursor, """INSERT INTO linha_performance_snapshots_op
            (op_id,velocidade_id,linha,configuracao,sku,velocidade_aves_hora,
             vigencia_inicio,vigencia_fim,resolvido_em,resolvido_por,resolvido_por_id,
             versao,justificativa_correcao) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            op_id, velocidade["id"], velocidade["linha"], velocidade["configuracao"],
            velocidade["sku"], velocidade["velocidade_aves_hora"],
            velocidade["vigencia_inicio"], velocidade["vigencia_fim"], _iso(),
            usuario, usuario_id, versao, justificativa,
        ))
        _auditar(cursor, "SNAPSHOT", snapshot_id, "CORRECAO_SNAPSHOT",
                 dict(anterior) if anterior else None, {"velocidade_id": velocidade_id, "versao": versao},
                 justificativa, usuario, usuario_id, perfil, op_id=op_id)
        return snapshot_id


def sugerir_contagem(op_id, *, conn=None):
    propria = conn is None
    conn = conn or conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT quantidade_aves,mortes_antes_pendura FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        if not op or op["quantidade_aves"] is None:
            return None
        recebidas = Decimal(str(op["quantidade_aves"]))
        mortes_legado = Decimal(str(op["mortes_antes_pendura"] or 0))
        cursor.execute(q("""SELECT COALESCE(SUM(quantidade),0) AS total
            FROM apontamentos_descartes WHERE op_id=?
              AND LOWER(TRIM(COALESCE(motivo,'')))='morte na gaiola'
              AND LOWER(TRIM(COALESCE(unidade,''))) IN ('aves','ave','unidade','unidades')"""), (op_id,))
        mortes_descartes = Decimal(str(cursor.fetchone()["total"] or 0))
        mortes = mortes_legado + mortes_descartes
        if recebidas < 0 or mortes < 0 or mortes > recebidas:
            return {"inconsistente": True, "aves_recebidas": recebidas,
                    "mortes_antes_pendura": mortes, "aves_processadas": None}
        return {"inconsistente": False, "aves_recebidas": recebidas,
                "mortes_antes_pendura": mortes, "aves_processadas": recebidas - mortes,
                "origem_calculo": "OP_QUANTIDADE_AVES + MORTE_NA_GAIOLA"}
    finally:
        if propria:
            conn.close()


def confirmar_contagem(op_id, aves_recebidas, mortes_antes_pendura, aves_processadas,
                       observacao=None, justificativa=None, *, usuario=None,
                       usuario_id=None, perfil=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil not in {"producao", "admin"}:
        raise PermissionError("Somente Producao ou Administrador podem confirmar a contagem.")
    recebidas = _decimal(aves_recebidas, "aves recebidas", permitir_zero=True)
    mortes = _decimal(mortes_antes_pendura, "mortes antes da pendura", permitir_zero=True)
    processadas = _decimal(aves_processadas, "aves processadas", permitir_zero=True)
    with _transacao() as conn:
        cursor = conn.cursor()
        sugestao = sugerir_contagem(op_id, conn=conn)
        if not sugestao or sugestao.get("inconsistente"):
            raise ValueError("A fonte operacional da contagem esta ausente ou inconsistente.")
        if (recebidas != sugestao["aves_recebidas"] or mortes != sugestao["mortes_antes_pendura"]
                or processadas != recebidas - mortes):
            raise ValueError("A contagem confirmada deve corresponder a fonte oficial rastreavel da OP.")
        cursor.execute(q("SELECT * FROM linha_performance_contagens WHERE op_id=? AND atual=1 ORDER BY id DESC"), (op_id,))
        anterior = cursor.fetchone()
        novo_valores = (str(recebidas), str(mortes), str(processadas))
        if anterior and tuple(str(anterior[c]) for c in ("aves_recebidas", "mortes_antes_pendura", "aves_processadas")) == novo_valores:
            return anterior["id"]
        if anterior:
            if perfil != "admin":
                raise PermissionError("Somente Administrador pode corrigir contagem ja confirmada.")
            if not str(justificativa or "").strip():
                raise ValueError("A justificativa da correcao e obrigatoria.")
        versao = int(anterior["versao"] if anterior else 0) + 1
        cursor.execute(q("UPDATE linha_performance_contagens SET atual=0 WHERE op_id=? AND atual=1"), (op_id,))
        contagem_id = _inserir_id(cursor, """INSERT INTO linha_performance_contagens
            (op_id,aves_recebidas,mortes_antes_pendura,aves_processadas,origem_calculo,
             confirmado_por,confirmado_por_id,confirmado_em,observacao,versao,
             justificativa_correcao) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
            op_id, *novo_valores, sugestao["origem_calculo"], usuario, usuario_id,
            _iso(), str(observacao or "").strip() or None, versao,
            str(justificativa or "").strip() or None,
        ))
        _auditar(cursor, "CONTAGEM", contagem_id,
                 "CORRECAO_CONTAGEM" if anterior else "CONFIRMACAO_CONTAGEM",
                 dict(anterior) if anterior else None,
                 {"aves_recebidas": str(recebidas), "mortes_antes_pendura": str(mortes),
                  "aves_processadas": str(processadas), "versao": versao},
                 justificativa, usuario, usuario_id, perfil, op_id=op_id)
        return contagem_id


def registrar_reprocesso(op_id, quantidade_aves, atravessou_linha, data_hora, motivo,
                         execucao_original, chave_idempotencia=None, *, usuario=None,
                         usuario_id=None, perfil=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil not in {"producao", "admin"}:
        raise PermissionError("Somente Producao ou Administrador podem registrar reprocesso.")
    quantidade = _decimal(quantidade_aves, "quantidade de aves")
    cruzou = str(atravessou_linha or "").strip().lower() in {"1", "sim", "true"}
    motivo = str(motivo or "").strip()
    execucao_original = str(execucao_original or "").strip()
    if not motivo or not execucao_original:
        raise ValueError("Informe motivo e execucao original do evento.")
    try:
        momento = datetime.fromisoformat(str(data_hora or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Informe data e hora validas para o reprocesso.") from exc
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=FUSO_MANAUS)
    chave = str(chave_idempotencia or "").strip() or None
    with _transacao() as conn:
        cursor = conn.cursor()
        if chave:
            cursor.execute(q("SELECT id FROM linha_performance_reprocessos WHERE op_id=? AND chave_idempotencia=?"), (op_id, chave))
            existente = cursor.fetchone()
            if existente:
                return existente["id"]
        evento_id = _inserir_id(cursor, """INSERT INTO linha_performance_reprocessos
            (op_id,quantidade_aves,atravessou_linha,data_hora,motivo,usuario,usuario_id,
             execucao_original,chave_idempotencia) VALUES (?,?,?,?,?,?,?,?,?)""", (
            op_id, str(quantidade), 1 if cruzou else 0, _iso(momento), motivo,
            usuario, usuario_id, execucao_original, chave,
        ))
        _auditar(cursor, "REPROCESSO", evento_id, "REGISTRO_REPROCESSO", None,
                 {"quantidade_aves": str(quantidade), "atravessou_linha": cruzou,
                  "execucao_original": execucao_original}, motivo, usuario, usuario_id,
                 perfil, op_id=op_id)
        return evento_id


def invalidar_por_reabertura(op_id, *, cursor, usuario=None, usuario_id=None,
                             perfil=None, justificativa="OP reaberta"):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    cursor.execute(q("SELECT * FROM linha_performance_snapshots_op WHERE op_id=? AND atual=1"), (op_id,))
    snapshots = cursor.fetchall()
    cursor.execute(q("SELECT * FROM linha_performance_contagens WHERE op_id=? AND atual=1"), (op_id,))
    contagens = cursor.fetchall()
    cursor.execute(q("UPDATE linha_performance_snapshots_op SET atual=0 WHERE op_id=? AND atual=1"), (op_id,))
    cursor.execute(q("UPDATE linha_performance_contagens SET atual=0 WHERE op_id=? AND atual=1"), (op_id,))
    if snapshots or contagens:
        _auditar(cursor, "OP", op_id, "INVALIDACAO_REABERTURA",
                 {"snapshots": [item["id"] for item in snapshots],
                  "contagens": [item["id"] for item in contagens]},
                 {"snapshot_atual": None, "contagem_atual": None}, justificativa,
                 usuario, usuario_id, perfil, op_id=op_id)


def calcular_performance(op_id, *, conn=None, disponibilidade=None):
    propria = conn is None
    conn = conn or conectar()
    motivos = []
    alertas = []
    inconsistencias = []
    base = {
        "situacao": "NAO_CALCULAVEL", "aves_recebidas": None,
        "mortes_antes_pendura": None, "aves_processadas": None,
        "reprocessos_validos": None, "quantidade_total_considerada": None,
        "velocidade_ideal_aves_hora": None, "configuracao": None,
        "sku": None, "origem_velocidade_id": None, "vigencia_inicio": None,
        "vigencia_fim": None, "snapshot_versao": None,
        "snapshot_situacao": "AUSENTE",
        "tempo_operacional_minutos": None, "producao_teorica": None,
        "performance": None, "alertas": alertas,
        "inconsistencias": inconsistencias, "motivos": motivos,
    }
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        if not op:
            motivos.append("OP nao encontrada.")
            return base
        if str(op["status"] or "").strip().lower() in {"cancelada", "cancelado"}:
            motivos.append("OP cancelada nao produz Performance calculavel.")
            return base
        cursor.execute(q("SELECT * FROM linha_performance_snapshots_op WHERE op_id=? AND atual=1 ORDER BY id DESC"), (op_id,))
        snapshots = cursor.fetchall()
        if len(snapshots) == 1:
            snapshot_previo = snapshots[0]
            velocidade_previa = _decimal_armazenado(snapshot_previo["velocidade_aves_hora"])
            base.update({
                "velocidade_ideal_aves_hora": velocidade_previa,
                "configuracao": snapshot_previo["configuracao"], "sku": snapshot_previo["sku"],
                "origem_velocidade_id": snapshot_previo["velocidade_id"],
                "vigencia_inicio": snapshot_previo["vigencia_inicio"],
                "vigencia_fim": snapshot_previo["vigencia_fim"],
                "snapshot_versao": snapshot_previo["versao"],
                "snapshot_situacao": "PRESERVADO",
            })
        elif not snapshots:
            cursor.execute(q("SELECT * FROM linha_abate_programacoes WHERE op_id=?"), (op_id,))
            programacao = cursor.fetchone()
            if programacao and not programacao["inicio_real"]:
                candidata, motivo_referencia = resolver_velocidade_op(cursor, op, programacao)
                if candidata:
                    velocidade_candidata = _decimal_armazenado(candidata["velocidade_aves_hora"])
                    base.update({
                        "velocidade_ideal_aves_hora": velocidade_candidata,
                        "configuracao": candidata["configuracao"], "sku": candidata["sku"],
                        "origem_velocidade_id": candidata["id"],
                        "vigencia_inicio": candidata["vigencia_inicio"],
                        "vigencia_fim": candidata["vigencia_fim"],
                        "snapshot_situacao": "PENDENTE_DO_INICIO",
                    })
                    alertas.append("Referencia valida encontrada; o snapshot sera preservado no inicio da Linha.")
                else:
                    base["snapshot_situacao"] = "SEM_REFERENCIA_VALIDA"
                    motivos.append(motivo_referencia)
            elif programacao and programacao["inicio_real"]:
                base["snapshot_situacao"] = "AUSENTE_HISTORICA"
        disponibilidade = disponibilidade or calcular_disponibilidade(op_id, conn=conn)
        base["tempo_operacional_minutos"] = disponibilidade.get("tempo_operacional_minutos")
        situacao_disp = disponibilidade.get("situacao")
        if situacao_disp == "EM_ANDAMENTO":
            base["situacao"] = "EM_ANDAMENTO"
            motivos.append("A Linha de Abate esta em andamento; nao ha percentual provisiorio.")
            return base
        if situacao_disp == "INCONSISTENTE":
            base["situacao"] = "INCONSISTENTE"
            inconsistencias.append({"codigo": "DISPONIBILIDADE_INCONSISTENTE"})
            motivos.append("Regularize a Disponibilidade antes de calcular a Performance.")
            return base
        if situacao_disp != "CALCULAVEL":
            motivos.append("A Disponibilidade ainda nao esta calculavel.")
            return base
        tempo = disponibilidade.get("tempo_operacional_minutos")
        if tempo is None:
            inconsistencias.append({"codigo": "TEMPO_OPERACIONAL_AUSENTE"})
            base["situacao"] = "INCONSISTENTE"
            motivos.append("Tempo operacional ausente apesar da Disponibilidade calculavel.")
            return base
        tempo = Decimal(str(tempo))
        if tempo <= 0:
            inconsistencias.append({"codigo": "TEMPO_OPERACIONAL_NAO_POSITIVO"})
            base["situacao"] = "INCONSISTENTE"
            motivos.append("Tempo operacional deve ser maior que zero.")
            return base
        if str(op["status"] or "") != "Encerrada":
            motivos.append("A OP precisa estar encerrada para confirmar o resultado oficial.")
            return base
        if not snapshots:
            motivos.append("OP sem snapshot de velocidade; nao e permitido backfill automatico.")
            return base
        if len(snapshots) != 1 or len({item["configuracao"] for item in snapshots}) != 1:
            motivos.append("Multiplas configuracoes sem segmentacao de tempo e quantidade.")
            return base
        snapshot = snapshots[0]
        velocidade = _decimal_armazenado(snapshot["velocidade_aves_hora"])
        base.update({
            "velocidade_ideal_aves_hora": velocidade,
            "configuracao": snapshot["configuracao"], "sku": snapshot["sku"],
            "origem_velocidade_id": snapshot["velocidade_id"],
            "vigencia_inicio": snapshot["vigencia_inicio"],
            "vigencia_fim": snapshot["vigencia_fim"],
            "snapshot_versao": snapshot["versao"],
            "snapshot_situacao": "PRESERVADO",
        })
        if velocidade is None or velocidade <= 0:
            inconsistencias.append({"codigo": "VELOCIDADE_NAO_POSITIVA"})
            base["situacao"] = "INCONSISTENTE"
            motivos.append("Snapshot possui velocidade ideal invalida.")
            return base
        cursor.execute(q("SELECT * FROM linha_performance_contagens WHERE op_id=? AND atual=1 ORDER BY id DESC"), (op_id,))
        contagens = cursor.fetchall()
        if not contagens:
            motivos.append("A contagem oficial de aves processadas ainda nao foi confirmada.")
            return base
        if len(contagens) != 1:
            base["situacao"] = "INCONSISTENTE"
            inconsistencias.append({"codigo": "MULTIPLAS_CONTAGENS_ATUAIS"})
            return base
        contagem = contagens[0]
        recebidas = _decimal_armazenado(contagem["aves_recebidas"])
        mortes = _decimal_armazenado(contagem["mortes_antes_pendura"])
        processadas = _decimal_armazenado(contagem["aves_processadas"])
        if (recebidas is None or mortes is None or processadas is None
                or recebidas < 0 or mortes < 0 or processadas < 0
                or mortes > recebidas or processadas != recebidas - mortes):
            base["situacao"] = "INCONSISTENTE"
            inconsistencias.append({"codigo": "CONTAGEM_OFICIAL_INVALIDA"})
            motivos.append("A contagem oficial armazenada esta inconsistente.")
            return base
        cursor.execute(q("""SELECT COALESCE(SUM(CASE WHEN atravessou_linha=1 AND ativo_logico=1
            THEN CAST(quantidade_aves AS DECIMAL) ELSE 0 END),0) AS total
            FROM linha_performance_reprocessos WHERE op_id=?"""), (op_id,))
        reprocessos = Decimal(str(cursor.fetchone()["total"] or 0))
        total = processadas + reprocessos
        teorica = velocidade * tempo / Decimal("60")
        percentual = total / teorica * Decimal("100")
        base.update({
            "aves_recebidas": recebidas, "mortes_antes_pendura": mortes,
            "aves_processadas": processadas, "reprocessos_validos": reprocessos,
            "quantidade_total_considerada": total,
            "tempo_operacional_minutos": tempo, "producao_teorica": teorica,
            "performance": percentual, "situacao": "CALCULAVEL",
        })
        if total == 0:
            alertas.append("Contagem zero foi explicitamente confirmada para a OP.")
        if percentual > Decimal("100"):
            alertas.append(
                "Performance acima de 100% foi preservada. Revise velocidade aprovada, "
                "contagem, tempo operacional ou mudanca de configuracao; a referencia "
                "nao foi recalibrada automaticamente."
            )
        return base
    finally:
        if propria:
            conn.close()


def historico_performance(op_id):
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM linha_performance_auditoria WHERE op_id=? ORDER BY criado_em DESC,id DESC"), (op_id,))
        return cursor.fetchall()
    finally:
        conn.close()
