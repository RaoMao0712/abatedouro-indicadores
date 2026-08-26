"""Disponibilidade oficial da Linha de Abate.

Este modulo concentra schema, validacoes, auditoria e calculo. Nenhuma rota ou
template deve reproduzir a formula temporal aqui implementada.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from database import DATABASE_URL, conectar, q


FUSO_MANAUS = ZoneInfo("America/Manaus")
CATEGORIAS_PAUSA = {
    "ALMOCO",
    "INTERVALO_CURTO",
    "LIMPEZA_PROGRAMADA",
    "MANUTENCAO_PREVENTIVA_PROGRAMADA",
}
SITUACOES = {"CALCULAVEL", "EM_ANDAMENTO", "NAO_CALCULAVEL", "INCONSISTENTE"}
NATUREZAS_PARADA_LINHA = {"NAO_PLANEJADA"}


def agora_manaus():
    return datetime.now(FUSO_MANAUS).replace(second=0, microsecond=0)


def _iso(valor):
    return valor.astimezone(FUSO_MANAUS).isoformat(timespec="minutes")


def _parse_data_hora(valor, *, data_base=None):
    if isinstance(valor, datetime):
        data_hora = valor
    else:
        texto = str(valor or "").strip()
        if not texto:
            return None
        if len(texto) == 5 and data_base:
            texto = f"{data_base}T{texto}"
        data_hora = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    if data_hora.tzinfo is None:
        data_hora = data_hora.replace(tzinfo=FUSO_MANAUS)
    return data_hora.astimezone(FUSO_MANAUS)


def _minutos(inicio, fim):
    return Decimal(str((fim - inicio).total_seconds())) / Decimal("60")


def _normalizar_janela(inicio, fim):
    inicio = _parse_data_hora(inicio)
    fim = _parse_data_hora(fim)
    if not inicio or not fim:
        raise ValueError("Informe inicio e termino programados da Linha de Abate.")
    if fim <= inicio and fim.date() == inicio.date():
        fim += timedelta(days=1)
    if fim <= inicio:
        raise ValueError("O termino programado deve ser posterior ao inicio programado.")
    if fim - inicio > timedelta(hours=24):
        raise ValueError("A janela programada da OP nao pode exceder 24 horas.")
    return inicio, fim


def _intervalo_pausa(pausa, janela_inicio):
    inicio = _parse_data_hora(pausa.get("inicio_previsto"), data_base=janela_inicio.date().isoformat())
    fim = _parse_data_hora(pausa.get("fim_previsto"), data_base=janela_inicio.date().isoformat())
    if not inicio or not fim:
        raise ValueError("Toda parada planejada deve ter inicio e termino previstos.")
    if inicio.date() == janela_inicio.date() and inicio < janela_inicio:
        inicio += timedelta(days=1)
        fim += timedelta(days=1)
    if fim <= inicio and fim.date() == inicio.date():
        fim += timedelta(days=1)
    return inicio, fim


def validar_programacao(inicio_programado, fim_programado, pausas=None):
    inicio, fim = _normalizar_janela(inicio_programado, fim_programado)
    normalizadas = []
    vistos = set()
    for pausa in pausas or []:
        categoria = str(pausa.get("categoria") or "").strip().upper()
        if categoria not in CATEGORIAS_PAUSA:
            raise ValueError("Categoria de parada planejada invalida.")
        pausa_inicio, pausa_fim = _intervalo_pausa(pausa, inicio)
        if pausa_fim <= pausa_inicio:
            raise ValueError("O termino da parada planejada deve ser posterior ao inicio.")
        if pausa_inicio < inicio or pausa_fim > fim:
            raise ValueError("A parada planejada deve estar dentro da janela programada.")
        chave = (categoria, pausa_inicio, pausa_fim)
        if chave in vistos:
            raise ValueError("Parada planejada duplicada.")
        vistos.add(chave)
        normalizadas.append({
            "categoria": categoria,
            "inicio_previsto": pausa_inicio,
            "fim_previsto": pausa_fim,
            "observacao": str(pausa.get("observacao") or "").strip(),
        })
    ordenadas = sorted(normalizadas, key=lambda item: item["inicio_previsto"])
    for anterior, atual in zip(ordenadas, ordenadas[1:]):
        if atual["inicio_previsto"] < anterior["fim_previsto"]:
            raise ValueError("Paradas planejadas nao podem se sobrepor.")
    total_pausas = sum((_minutos(p["inicio_previsto"], p["fim_previsto"]) for p in ordenadas), Decimal("0"))
    if _minutos(inicio, fim) - total_pausas <= 0:
        raise ValueError("O tempo planejado liquido deve ser maior que zero.")
    return inicio, fim, ordenadas


def _executar_alteracao(cursor, postgres_sql, sqlite_sql):
    try:
        cursor.execute(postgres_sql if DATABASE_URL else sqlite_sql)
    except sqlite3.OperationalError as erro:
        if DATABASE_URL or "duplicate column name" not in str(erro).lower():
            raise


def criar_tabelas_disponibilidade():
    conn = conectar()
    cursor = conn.cursor()
    id_type = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    try:
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS linha_abate_programacoes (
            id {id_type}, op_id INTEGER UNIQUE NOT NULL,
            inicio_programado TEXT NOT NULL, fim_programado TEXT NOT NULL,
            inicio_real TEXT, fim_real TEXT,
            inicio_registrado_por TEXT, inicio_registrado_por_id INTEGER,
            fim_registrado_por TEXT, fim_registrado_por_id INTEGER,
            criado_por TEXT NOT NULL, criado_por_id INTEGER,
            criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL,
            versao INTEGER NOT NULL DEFAULT 1
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS linha_abate_paradas_planejadas (
            id {id_type}, programacao_id INTEGER NOT NULL,
            categoria TEXT NOT NULL, inicio_previsto TEXT NOT NULL,
            fim_previsto TEXT NOT NULL, duracao_minutos INTEGER NOT NULL,
            observacao TEXT, ativa INTEGER NOT NULL DEFAULT 1,
            criado_por TEXT NOT NULL, criado_por_id INTEGER,
            criado_em TEXT NOT NULL, desativado_em TEXT, desativado_por TEXT
        )
        """)
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS linha_abate_auditoria (
            id {id_type}, op_id INTEGER NOT NULL, entidade TEXT NOT NULL,
            entidade_id INTEGER, acao TEXT NOT NULL,
            valor_anterior TEXT, valor_novo TEXT, justificativa TEXT,
            usuario TEXT NOT NULL, usuario_id INTEGER, perfil TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )
        """)
        for postgres_sql, sqlite_sql in [
            ("ALTER TABLE apontamentos_paradas ADD COLUMN IF NOT EXISTS afeta_linha_abate INTEGER", "ALTER TABLE apontamentos_paradas ADD COLUMN afeta_linha_abate INTEGER"),
            ("ALTER TABLE apontamentos_paradas ADD COLUMN IF NOT EXISTS natureza_disponibilidade TEXT", "ALTER TABLE apontamentos_paradas ADD COLUMN natureza_disponibilidade TEXT"),
            ("ALTER TABLE apontamentos_paradas ADD COLUMN IF NOT EXISTS classificacao_alterada_em TEXT", "ALTER TABLE apontamentos_paradas ADD COLUMN classificacao_alterada_em TEXT"),
            ("ALTER TABLE apontamentos_paradas ADD COLUMN IF NOT EXISTS classificacao_alterada_por TEXT", "ALTER TABLE apontamentos_paradas ADD COLUMN classificacao_alterada_por TEXT"),
            ("ALTER TABLE apontamentos_paradas ADD COLUMN IF NOT EXISTS classificacao_justificativa TEXT", "ALTER TABLE apontamentos_paradas ADD COLUMN classificacao_justificativa TEXT"),
            ("ALTER TABLE apontamentos_paradas ADD COLUMN IF NOT EXISTS registrado_por TEXT", "ALTER TABLE apontamentos_paradas ADD COLUMN registrado_por TEXT"),
            ("ALTER TABLE apontamentos_paradas ADD COLUMN IF NOT EXISTS registrado_por_id INTEGER", "ALTER TABLE apontamentos_paradas ADD COLUMN registrado_por_id INTEGER"),
        ]:
            _executar_alteracao(cursor, postgres_sql, sqlite_sql)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_linha_programacao_op ON linha_abate_programacoes(op_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_linha_pausas_programacao ON linha_abate_paradas_planejadas(programacao_id, ativa)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_linha_auditoria_op ON linha_abate_auditoria(op_id, criado_em)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_paradas_afeta_linha ON apontamentos_paradas(afeta_linha_abate, op_id, data)")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _identidade(usuario=None, usuario_id=None, perfil=None):
    return usuario or "Sistema", usuario_id, str(perfil or "sistema").lower()


def _auditar(cursor, op_id, entidade, entidade_id, acao, anterior, novo,
             justificativa, usuario, usuario_id, perfil, criado_em=None):
    cursor.execute(q("""
    INSERT INTO linha_abate_auditoria (
        op_id, entidade, entidade_id, acao, valor_anterior, valor_novo,
        justificativa, usuario, usuario_id, perfil, criado_em
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        op_id, entidade, entidade_id, acao,
        json.dumps(anterior, ensure_ascii=False, sort_keys=True) if anterior is not None else None,
        json.dumps(novo, ensure_ascii=False, sort_keys=True) if novo is not None else None,
        justificativa, usuario, usuario_id, perfil, criado_em or _iso(agora_manaus()),
    ))


def pausas_do_form(form):
    if not hasattr(form, "getlist"):
        return form.get("pausas", []) or []
    categorias = form.getlist("pausa_categoria")
    inicios = form.getlist("pausa_inicio")
    fins = form.getlist("pausa_fim")
    observacoes = form.getlist("pausa_observacao")
    pausas = []
    for indice, categoria in enumerate(categorias):
        if not str(categoria or "").strip() and not str(inicios[indice] if indice < len(inicios) else "").strip():
            continue
        pausas.append({
            "categoria": categoria,
            "inicio_previsto": inicios[indice] if indice < len(inicios) else "",
            "fim_previsto": fins[indice] if indice < len(fins) else "",
            "observacao": observacoes[indice] if indice < len(observacoes) else "",
        })
    return pausas


def salvar_programacao(op_id, inicio_programado, fim_programado, pausas, *,
                       usuario=None, usuario_id=None, perfil=None, justificativa=None,
                       conn=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil not in {"pcp", "admin"}:
        raise PermissionError("Somente PCP ou Administrador podem programar a Linha de Abate.")
    inicio, fim, pausas = validar_programacao(inicio_programado, fim_programado, pausas)
    propria = conn is None
    conn = conn or conectar()
    cursor = conn.cursor()
    try:
        cursor.execute(q("SELECT * FROM linha_abate_programacoes WHERE op_id=?"), (op_id,))
        atual = cursor.fetchone()
        agora = _iso(agora_manaus())
        novo = {"inicio_programado": _iso(inicio), "fim_programado": _iso(fim), "pausas": [
            {"categoria": p["categoria"], "inicio_previsto": _iso(p["inicio_previsto"]),
             "fim_previsto": _iso(p["fim_previsto"]), "observacao": p["observacao"]}
            for p in pausas
        ]}
        anterior = None
        if atual:
            cursor.execute(q("SELECT categoria,inicio_previsto,fim_previsto,observacao FROM linha_abate_paradas_planejadas WHERE programacao_id=? AND ativa=1 ORDER BY inicio_previsto"), (atual["id"],))
            anterior = {"inicio_programado": atual["inicio_programado"], "fim_programado": atual["fim_programado"], "pausas": [dict(x) for x in cursor.fetchall()]}
            if anterior == novo:
                return atual["id"]
            if atual["inicio_real"]:
                if perfil != "admin":
                    raise PermissionError("Apos o inicio real, somente Administrador pode alterar a programacao.")
                if not str(justificativa or "").strip():
                    raise ValueError("A justificativa e obrigatoria para alterar a programacao apos o inicio.")
                preventivas = [
                    pausa for pausa in pausas
                    if pausa["categoria"] == "MANUTENCAO_PREVENTIVA_PROGRAMADA"
                ]
                if preventivas:
                    cursor.execute(q("SELECT * FROM apontamentos_paradas WHERE op_id=?"), (op_id,))
                    for parada in cursor.fetchall():
                        foi_corretiva = (
                            str(parada["manutencao_aberta"] or "").strip().lower() == "sim"
                            or "corretiv" in str(parada["motivo"] or "").lower()
                        )
                        intervalo = _intervalo_parada(parada, inicio)
                        if foi_corretiva and intervalo and any(
                            max(intervalo[0], pausa["inicio_previsto"])
                            < min(intervalo[1], pausa["fim_previsto"])
                            for pausa in preventivas
                        ):
                            raise ValueError(
                                "Manutencao corretiva registrada nao pode ser transformada "
                                "em parada preventiva programada."
                            )
            cursor.execute(q("UPDATE linha_abate_programacoes SET inicio_programado=?,fim_programado=?,atualizado_em=?,versao=versao+1 WHERE id=?"), (_iso(inicio), _iso(fim), agora, atual["id"]))
            cursor.execute(q("UPDATE linha_abate_paradas_planejadas SET ativa=0,desativado_em=?,desativado_por=? WHERE programacao_id=? AND ativa=1"), (agora, usuario, atual["id"]))
            programacao_id = atual["id"]
            acao = "ALTERACAO_PROGRAMACAO"
        else:
            sql = """INSERT INTO linha_abate_programacoes (op_id,inicio_programado,fim_programado,criado_por,criado_por_id,criado_em,atualizado_em) VALUES (?,?,?,?,?,?,?)"""
            params = (op_id, _iso(inicio), _iso(fim), usuario, usuario_id, agora, agora)
            if DATABASE_URL:
                cursor.execute(q(sql + " RETURNING id"), params)
                programacao_id = cursor.fetchone()["id"]
            else:
                cursor.execute(sql, params)
                programacao_id = cursor.lastrowid
            acao = "CRIACAO_PROGRAMACAO"
        for pausa in pausas:
            cursor.execute(q("""INSERT INTO linha_abate_paradas_planejadas
                (programacao_id,categoria,inicio_previsto,fim_previsto,duracao_minutos,observacao,criado_por,criado_por_id,criado_em)
                VALUES (?,?,?,?,?,?,?,?,?)"""), (
                programacao_id, pausa["categoria"], _iso(pausa["inicio_previsto"]),
                _iso(pausa["fim_previsto"]), int(_minutos(pausa["inicio_previsto"], pausa["fim_previsto"])),
                pausa["observacao"], usuario, usuario_id, agora,
            ))
        _auditar(cursor, op_id, "PROGRAMACAO", programacao_id, acao, anterior, novo,
                 str(justificativa or "").strip() or None, usuario, usuario_id, perfil, agora)
        if propria:
            conn.commit()
        return programacao_id
    except Exception:
        if propria:
            conn.rollback()
        raise
    finally:
        if propria:
            conn.close()


def obter_programacao(op_id, conn=None):
    propria = conn is None
    conn = conn or conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT * FROM linha_abate_programacoes WHERE op_id=?"), (op_id,))
        programacao = cursor.fetchone()
        if not programacao:
            return None, []
        cursor.execute(q("SELECT * FROM linha_abate_paradas_planejadas WHERE programacao_id=? AND ativa=1 ORDER BY inicio_previsto,id"), (programacao["id"],))
        return programacao, cursor.fetchall()
    finally:
        if propria:
            conn.close()


def registrar_inicio_linha(op_id, *, usuario=None, usuario_id=None, perfil=None, agora=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil not in {"producao", "admin"}:
        raise PermissionError("Somente Producao ou Administrador podem iniciar a Linha de Abate.")
    momento = _parse_data_hora(agora or agora_manaus())
    with _transacao() as (conn, cursor):
        cursor.execute(q("SELECT * FROM linha_abate_programacoes WHERE op_id=?"), (op_id,))
        programacao = cursor.fetchone()
        if not programacao:
            raise ValueError("A OP precisa de programacao antes do inicio da Linha de Abate.")
        if programacao["inicio_real"]:
            return programacao["inicio_real"]
        cursor.execute(q("UPDATE linha_abate_programacoes SET inicio_real=?,inicio_registrado_por=?,inicio_registrado_por_id=?,atualizado_em=?,versao=versao+1 WHERE id=? AND inicio_real IS NULL"), (_iso(momento), usuario, usuario_id, _iso(momento), programacao["id"]))
        if cursor.rowcount != 1:
            cursor.execute(q("SELECT inicio_real FROM linha_abate_programacoes WHERE id=?"), (programacao["id"],))
            return cursor.fetchone()["inicio_real"]
        _auditar(cursor, op_id, "MEDICAO", programacao["id"], "INICIO_LINHA", None,
                 {"inicio_real": _iso(momento)}, None, usuario, usuario_id, perfil, _iso(momento))
        return _iso(momento)


def registrar_fim_linha(op_id, *, usuario=None, usuario_id=None, perfil=None, agora=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil not in {"producao", "admin"}:
        raise PermissionError("Somente Producao ou Administrador podem encerrar a medicao da Linha de Abate.")
    momento = _parse_data_hora(agora or agora_manaus())
    with _transacao() as (conn, cursor):
        cursor.execute(q("SELECT * FROM linha_abate_programacoes WHERE op_id=?"), (op_id,))
        programacao = cursor.fetchone()
        if not programacao or not programacao["inicio_real"]:
            raise ValueError("Nao e permitido encerrar a Linha sem inicio real.")
        if programacao["fim_real"]:
            return programacao["fim_real"]
        inicio = _parse_data_hora(programacao["inicio_real"])
        if momento < inicio:
            raise ValueError("O termino real nao pode ser anterior ao inicio real.")
        cursor.execute(q("UPDATE linha_abate_programacoes SET fim_real=?,fim_registrado_por=?,fim_registrado_por_id=?,atualizado_em=?,versao=versao+1 WHERE id=? AND fim_real IS NULL"), (_iso(momento), usuario, usuario_id, _iso(momento), programacao["id"]))
        if cursor.rowcount != 1:
            cursor.execute(q("SELECT fim_real FROM linha_abate_programacoes WHERE id=?"), (programacao["id"],))
            return cursor.fetchone()["fim_real"]
        _auditar(cursor, op_id, "MEDICAO", programacao["id"], "FIM_LINHA", None,
                 {"fim_real": _iso(momento)}, None, usuario, usuario_id, perfil, _iso(momento))
        return _iso(momento)


class _transacao:
    def __enter__(self):
        self.conn = conectar()
        self.cursor = self.conn.cursor()
        return self.conn, self.cursor

    def __exit__(self, tipo, valor, traceback):
        try:
            if tipo:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.conn.close()


def corrigir_medicao(op_id, inicio_real, fim_real, justificativa, *, usuario=None,
                     usuario_id=None, perfil=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil != "admin":
        raise PermissionError("Somente Administrador pode corrigir a medicao da Linha de Abate.")
    if not str(justificativa or "").strip():
        raise ValueError("A justificativa da correcao e obrigatoria.")
    inicio = _parse_data_hora(inicio_real)
    fim = _parse_data_hora(fim_real) if fim_real else None
    if not inicio or (fim and fim < inicio):
        raise ValueError("Informe horarios reais validos.")
    with _transacao() as (conn, cursor):
        cursor.execute(q("SELECT * FROM linha_abate_programacoes WHERE op_id=?"), (op_id,))
        atual = cursor.fetchone()
        if not atual:
            raise ValueError("Programacao da Linha nao encontrada.")
        anterior = {"inicio_real": atual["inicio_real"], "fim_real": atual["fim_real"]}
        novo = {"inicio_real": _iso(inicio), "fim_real": _iso(fim) if fim else None}
        agora = _iso(agora_manaus())
        cursor.execute(q("UPDATE linha_abate_programacoes SET inicio_real=?,fim_real=?,atualizado_em=?,versao=versao+1 WHERE id=?"), (novo["inicio_real"], novo["fim_real"], agora, atual["id"]))
        _auditar(cursor, op_id, "MEDICAO", atual["id"], "CORRECAO_MEDICAO", anterior,
                 novo, justificativa, usuario, usuario_id, perfil, agora)


def reclassificar_parada(parada_id, afeta_linha, justificativa, *, usuario=None,
                         usuario_id=None, perfil=None):
    usuario, usuario_id, perfil = _identidade(usuario, usuario_id, perfil)
    if perfil != "admin":
        raise PermissionError("Somente Administrador pode reclassificar parada da Linha de Abate.")
    if not str(justificativa or "").strip():
        raise ValueError("A justificativa da reclassificacao e obrigatoria.")
    valor_normalizado = str(afeta_linha or "").strip().lower()
    if valor_normalizado not in {"1", "sim", "true", "0", "nao", "não", "false"}:
        raise ValueError("Informe se a parada afetou ou nao a Linha de Abate.")
    novo_valor = 1 if valor_normalizado in {"1", "sim", "true"} else 0
    with _transacao() as (conn, cursor):
        cursor.execute(q("SELECT * FROM apontamentos_paradas WHERE id=?"), (parada_id,))
        parada = cursor.fetchone()
        if not parada:
            raise ValueError("Parada nao encontrada.")
        agora = _iso(agora_manaus())
        cursor.execute(q("""UPDATE apontamentos_paradas SET afeta_linha_abate=?,natureza_disponibilidade='NAO_PLANEJADA',classificacao_alterada_em=?,classificacao_alterada_por=?,classificacao_justificativa=? WHERE id=?"""), (novo_valor, agora, usuario, justificativa, parada_id))
        _auditar(cursor, parada["op_id"], "PARADA", parada_id, "RECLASSIFICACAO_PARADA",
                 {"afeta_linha_abate": parada["afeta_linha_abate"]},
                 {"afeta_linha_abate": novo_valor}, justificativa,
                 usuario, usuario_id, perfil, agora)


def _unir_intervalos(intervalos):
    resultado = []
    for inicio, fim in sorted((i, f) for i, f in intervalos if i < f):
        if not resultado or inicio > resultado[-1][1]:
            resultado.append([inicio, fim])
        else:
            resultado[-1][1] = max(resultado[-1][1], fim)
    return [(i, f) for i, f in resultado]


def _recortar(intervalo, janela):
    inicio = max(intervalo[0], janela[0])
    fim = min(intervalo[1], janela[1])
    return (inicio, fim) if inicio < fim else None


def _subtrair(intervalos, exclusoes):
    resultado = list(intervalos)
    for ex_inicio, ex_fim in _unir_intervalos(exclusoes):
        novos = []
        for inicio, fim in resultado:
            if ex_fim <= inicio or ex_inicio >= fim:
                novos.append((inicio, fim))
                continue
            if inicio < ex_inicio:
                novos.append((inicio, ex_inicio))
            if ex_fim < fim:
                novos.append((ex_fim, fim))
        resultado = novos
    return resultado


def _intervalo_parada(parada, janela_inicio):
    chaves = set(parada.keys())
    data = parada["data"] if "data" in chaves else None
    data_fim = parada["data_fim"] if "data_fim" in chaves else None
    inicio = _parse_data_hora(parada["hora_inicio"], data_base=data or janela_inicio.date().isoformat())
    fim = _parse_data_hora(parada["hora_fim"], data_base=data_fim or data or janela_inicio.date().isoformat())
    if not inicio or not fim:
        return None
    if fim <= inicio and (not data_fim or data_fim == data):
        fim += timedelta(days=1)
    return (inicio, fim) if fim > inicio else None


def _parada_intercepta_janela(parada, janela):
    """Decide relevancia temporal sem presumir o impacto operacional."""
    try:
        intervalo = _intervalo_parada(parada, janela[0])
    except (TypeError, ValueError):
        intervalo = None
    if intervalo:
        return _recortar(intervalo, janela) is not None

    chaves = set(parada.keys())
    data = parada["data"] if "data" in chaves else None
    try:
        inicio = _parse_data_hora(
            parada["hora_inicio"],
            data_base=data or janela[0].date().isoformat(),
        )
    except (TypeError, ValueError):
        inicio = None

    if inicio:
        # Sem termino valido, a parada permanece aberta a partir do inicio.
        return inicio < janela[1]

    # Um registro sem horario dentro dos dias da medicao nao pode ser provado
    # como externo; por seguranca de dominio ele exige regularizacao.
    try:
        data_registro = datetime.fromisoformat(str(data)).date()
    except (TypeError, ValueError):
        return False
    return janela[0].date() <= data_registro <= janela[1].date()


def calcular_disponibilidade(op_id, *, agora=None, conn=None):
    propria = conn is None
    conn = conn or conectar()
    motivos = []
    alertas = []
    inconsistencias = []
    try:
        cursor = conn.cursor()
        cursor.execute(q("SELECT status FROM ordens_producao WHERE id=?"), (op_id,))
        op = cursor.fetchone()
        status_op = str(op["status"] or "").upper() if op else ""
        op_em_andamento = bool(
            op and status_op not in {
                "ENCERRADA", "ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO",
            }
        )
        op_historica = status_op in {"ESTORNADA", "ESTORNADO", "CANCELADA", "CANCELADO"}
        programacao, pausas = obter_programacao(op_id, conn=conn)
        base = {
            "inicio_programado": None, "fim_programado": None,
            "duracao_bruta_minutos": None, "paradas_planejadas_minutos": None,
            "tempo_planejado_liquido_minutos": None, "inicio_real": None,
            "fim_real": None, "atraso_inicio_minutos": None,
            "encerramento_antecipado_minutos": None,
            "paradas_nao_planejadas_minutos": None,
            "tempo_operacional_minutos": None, "disponibilidade": None,
            "situacao": "NAO_CALCULAVEL", "motivos": motivos, "alertas": alertas,
            "inconsistencias": inconsistencias,
            "pausas_planejadas": pausas, "auditoria": [], "status_op": status_op,
        }
        if not op:
            motivos.append("OP nao encontrada.")
            return base
        if not programacao:
            if op_em_andamento:
                base["situacao"] = "EM_ANDAMENTO"
                motivos.append("OP em andamento sem programacao oficial da Linha de Abate.")
            else:
                motivos.append("OP sem programacao oficial da Linha de Abate.")
            return base
        try:
            inicio_p = _parse_data_hora(programacao["inicio_programado"])
            fim_p = _parse_data_hora(programacao["fim_programado"])
            if not inicio_p or not fim_p or fim_p <= inicio_p:
                raise ValueError
        except (TypeError, ValueError):
            base["situacao"] = "INCONSISTENTE"
            motivos.append("Janela programada invalida.")
            return base
        intervalos_pausa = []
        for pausa in pausas:
            try:
                intervalo = (_parse_data_hora(pausa["inicio_previsto"]), _parse_data_hora(pausa["fim_previsto"]))
                recortado = _recortar(intervalo, (inicio_p, fim_p))
                if not recortado or recortado != intervalo:
                    alertas.append(f"Parada planejada #{pausa['id']} fora da janela.")
                    continue
                intervalos_pausa.append(intervalo)
            except Exception:
                alertas.append(f"Parada planejada #{pausa['id']} invalida.")
        intervalos_pausa = _unir_intervalos(intervalos_pausa)
        bruto = _minutos(inicio_p, fim_p)
        planejadas = sum((_minutos(i, f) for i, f in intervalos_pausa), Decimal("0"))
        liquido = bruto - planejadas
        base.update({
            "inicio_programado": programacao["inicio_programado"], "fim_programado": programacao["fim_programado"],
            "duracao_bruta_minutos": bruto, "paradas_planejadas_minutos": planejadas,
            "tempo_planejado_liquido_minutos": liquido,
            "inicio_real": programacao["inicio_real"], "fim_real": programacao["fim_real"],
        })
        if liquido <= 0:
            base["situacao"] = "INCONSISTENTE"
            motivos.append("Tempo planejado liquido igual ou inferior a zero.")
            return base
        inicio_r = _parse_data_hora(programacao["inicio_real"])
        fim_r = _parse_data_hora(programacao["fim_real"])
        if not inicio_r:
            if op_em_andamento:
                base["situacao"] = "EM_ANDAMENTO"
                motivos.append("OP programada ainda sem inicio real; medicao da Linha de Abate em andamento.")
            else:
                motivos.append("Inicio real da Linha de Abate ainda nao registrado.")
            return base
        if not fim_r:
            base["situacao"] = "EM_ANDAMENTO"
            motivos.append("Medicao da Linha de Abate em andamento.")
            return base
        if fim_r < inicio_r:
            base["situacao"] = "INCONSISTENTE"
            motivos.append("Termino real anterior ao inicio real.")
            return base
        atraso_intervalo = _recortar((inicio_p, min(inicio_r, fim_p)), (inicio_p, fim_p)) if inicio_r > inicio_p else None
        antecipado_intervalo = _recortar((max(fim_r, inicio_p), fim_p), (inicio_p, fim_p)) if fim_r < fim_p else None
        cursor.execute(q("SELECT * FROM apontamentos_paradas WHERE op_id=?"), (op_id,))
        paradas = cursor.fetchall()
        perdas = []
        parada_aberta_em_andamento = False
        for parada in paradas:
            if not _parada_intercepta_janela(parada, (inicio_p, fim_p)):
                continue

            if parada["afeta_linha_abate"] is None:
                inconsistencias.append({
                    "codigo": "PARADA_SEM_CLASSIFICACAO_IMPACTO",
                    "parada_id": parada["id"],
                })
                alertas.append(
                    f"Parada #{parada['id']} intercepta a janela e esta pendente de "
                    "classificacao de impacto na Linha de Abate. Regularize por "
                    "reclassificacao administrativa com justificativa e auditoria."
                )
                continue
            if int(parada["afeta_linha_abate"] or 0) != 1:
                continue

            natureza = str(parada["natureza_disponibilidade"] or "").strip().upper()
            natureza_valida = natureza in NATUREZAS_PARADA_LINHA
            if not natureza_valida:
                inconsistencias.append({
                    "codigo": "PARADA_COM_NATUREZA_INVALIDA",
                    "parada_id": parada["id"],
                })
                alertas.append(
                    f"Parada #{parada['id']} afeta a Linha de Abate, mas possui natureza "
                    "de disponibilidade ausente ou invalida. Regularize por reclassificacao "
                    "administrativa com justificativa e auditoria."
                )

            try:
                intervalo = _intervalo_parada(parada, inicio_p)
            except (TypeError, ValueError):
                intervalo = None
            if not intervalo:
                if op_em_andamento and not parada["hora_fim"]:
                    parada_aberta_em_andamento = True
                    alertas.append(f"Parada #{parada['id']} que afeta a linha permanece aberta; medicao em andamento.")
                else:
                    inconsistencias.append({
                        "codigo": "PARADA_ABERTA_OU_INTERVALO_INVALIDO",
                        "parada_id": parada["id"],
                    })
                    alertas.append(f"Parada #{parada['id']} que afeta a linha esta aberta ou possui horario invalido.")
                continue
            if natureza_valida:
                recortado = _recortar(intervalo, (inicio_p, fim_p))
                if recortado:
                    perdas.append(recortado)
        atrasos_liquidos = _subtrair([atraso_intervalo] if atraso_intervalo else [], intervalos_pausa)
        antecipados_liquidos = _subtrair([antecipado_intervalo] if antecipado_intervalo else [], intervalos_pausa)
        paradas_liquidas = _subtrair(perdas, intervalos_pausa)
        perdas_unidas = _unir_intervalos(atrasos_liquidos + antecipados_liquidos + paradas_liquidas)
        perda_total = sum((_minutos(i, f) for i, f in perdas_unidas), Decimal("0"))
        operacional = max(Decimal("0"), liquido - perda_total)
        disponibilidade = operacional / liquido * Decimal("100")
        if disponibilidade < 0 or disponibilidade > 100:
            inconsistencias.append({"codigo": "DISPONIBILIDADE_FORA_DOS_LIMITES"})
            alertas.append("Disponibilidade fora do intervalo de 0% a 100%; revise a programacao e os tempos.")
        inconsistente = bool(inconsistencias)
        base.update({
            "atraso_inicio_minutos": sum((_minutos(i, f) for i, f in atrasos_liquidos), Decimal("0")),
            "encerramento_antecipado_minutos": sum((_minutos(i, f) for i, f in antecipados_liquidos), Decimal("0")),
            "paradas_nao_planejadas_minutos": sum((_minutos(i, f) for i, f in _unir_intervalos(paradas_liquidas)), Decimal("0")),
            "tempo_operacional_minutos": None if inconsistente else operacional,
            "disponibilidade": None if inconsistente else disponibilidade,
            "situacao": "INCONSISTENTE" if inconsistente else "CALCULAVEL",
        })
        if op_historica:
            base.update({
                "tempo_operacional_minutos": None, "disponibilidade": None,
                "situacao": "NAO_CALCULAVEL",
            })
            motivos.append("OP estornada/cancelada mantida somente no historico, sem indicador vigente.")
        elif op_em_andamento and not inconsistente:
            base.update({"disponibilidade": None, "situacao": "EM_ANDAMENTO"})
            motivos.append(
                "Parada da linha em andamento; percentual final nao publicado."
                if parada_aberta_em_andamento
                else "OP em andamento; a Disponibilidade final nao e publicada."
            )
        cursor.execute(q("SELECT * FROM linha_abate_auditoria WHERE op_id=? ORDER BY criado_em DESC,id DESC"), (op_id,))
        base["auditoria"] = cursor.fetchall()
        return base
    finally:
        if propria:
            conn.close()


def consultar_historico_paradas(filtros=None):
    filtros = filtros or {}
    condicoes = ["1=1"]
    parametros = []
    if filtros.get("inicio"):
        condicoes.append("p.data >= ?"); parametros.append(filtros["inicio"])
    if filtros.get("fim"):
        condicoes.append("p.data <= ?"); parametros.append(filtros["fim"])
    if filtros.get("op"):
        try:
            condicoes.append("p.op_id = ?"); parametros.append(int(filtros["op"]))
        except ValueError:
            condicoes.append("1=0")
    if filtros.get("status"):
        condicoes.append("CASE WHEN o.id IS NULL THEN 'ORFA' ELSE COALESCE(o.status,'Aberta') END = ?"); parametros.append(filtros["status"])
    for campo in ("setor", "motivo"):
        if filtros.get(campo):
            condicoes.append(f"p.{campo} = ?"); parametros.append(filtros[campo])
    if filtros.get("equipamento"):
        condicoes.append("COALESCE(p.equipamento,'') LIKE ?"); parametros.append(f"%{filtros['equipamento']}%")
    if filtros.get("situacao") == "ABERTA":
        condicoes.append("COALESCE(p.hora_fim,'') = ''")
    elif filtros.get("situacao") == "ENCERRADA":
        condicoes.append("COALESCE(p.hora_fim,'') <> ''")
    if filtros.get("afeta") == "SIM":
        condicoes.append("p.afeta_linha_abate = 1")
    elif filtros.get("afeta") == "NAO":
        condicoes.append("p.afeta_linha_abate = 0")
    elif filtros.get("afeta") == "NAO_CLASSIFICADA":
        condicoes.append("p.afeta_linha_abate IS NULL")
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(f"""SELECT p.*,o.status AS op_status,
            CASE WHEN o.id IS NULL THEN 1 ELSE 0 END AS registro_orfao
            FROM apontamentos_paradas p LEFT JOIN ordens_producao o ON o.id=p.op_id
            WHERE {' AND '.join(condicoes)} ORDER BY p.data DESC,p.hora_inicio DESC,p.id DESC"""), tuple(parametros))
        return cursor.fetchall()
    finally:
        conn.close()
