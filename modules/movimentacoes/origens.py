"""Origem e governança aditivas das movimentações financeiras."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from database import DATABASE_URL, conectar, q


LEGADO_IMPORTADO = "LEGADO_IMPORTADO"
IMPORTACAO_FINANCEIRA = "IMPORTACAO_FINANCEIRA"
MANUAL_CONTROLADO = "MANUAL_CONTROLADO"
OPERACIONAL = "OPERACIONAL"
SANKHYA = "SANKHYA"

MODOS_ORIGEM = (
    LEGADO_IMPORTADO,
    IMPORTACAO_FINANCEIRA,
    MANUAL_CONTROLADO,
    OPERACIONAL,
    SANKHYA,
)
MODOS_ORIGEM_PERSISTIVEIS = (
    IMPORTACAO_FINANCEIRA,
    MANUAL_CONTROLADO,
    OPERACIONAL,
    SANKHYA,
)
ROTULOS_MODOS_ORIGEM = {
    LEGADO_IMPORTADO: "Legado",
    IMPORTACAO_FINANCEIRA: "Importação",
    MANUAL_CONTROLADO: "Manual",
    OPERACIONAL: "Operacional",
    SANKHYA: "Sankhya",
}

PAPEL_ORIGEM_PRINCIPAL = "PRINCIPAL"
STATUS_ORIGEM_ATIVA = "ATIVA"
STATUS_ORIGEM_CANCELADA = "CANCELADA"

STATUS_LOTE_PROCESSANDO = "PROCESSANDO"
STATUS_LOTE_CONCLUIDO = "CONCLUÍDO"
STATUS_LOTE_CONFLITOS = "CONCLUÍDO_COM_CONFLITOS"
STATUS_LOTE_FALHOU = "FALHOU"
STATUS_LOTE_CANCELADO = "CANCELADO"

STATUS_LINHA_IMPORTADA = "IMPORTADA"
STATUS_LINHA_IDENTICA = "IDÊNTICA"
STATUS_LINHA_CONFLITANTE = "CONFLITANTE"
STATUS_LINHA_REJEITADA = "REJEITADA"

METADADOS_ORIGEM_PERMITIDOS = {
    "justificativa",
    "referencia_evidencia",
    "tipo_importador",
    "origem_importacao",
    "arquivo_hash",
    "parcela",
    "total_parcelas",
}


def _json_controlado(valor, chaves_permitidas=None):
    if not valor:
        return "{}"
    if not isinstance(valor, dict):
        raise ValueError("Metadados devem ser informados como dicionário.")
    if chaves_permitidas is not None:
        valor = {
            chave: conteudo
            for chave, conteudo in valor.items()
            if chave in chaves_permitidas
        }
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, default=str)


def sanitizar_nome_arquivo(nome):
    nome_base = Path(str(nome or "arquivo.xlsx").replace("\\", "/")).name
    nome_base = re.sub(r"[^A-Za-z0-9._ -]+", "_", nome_base).strip(" .")
    return nome_base[:180] or "arquivo.xlsx"


def hash_sha256(conteudo):
    return hashlib.sha256(conteudo).hexdigest()


def hash_normalizado(dados):
    serializado = json.dumps(
        dados or {},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(serializado.encode("utf-8")).hexdigest()


def criar_tabelas_governanca_financeira(cursor=None):
    """Cria apenas estruturas; não materializa origem para dados históricos."""
    conexao_propria = cursor is None
    conn = conectar() if conexao_propria else None
    cursor = cursor or conn.cursor()
    id_pk = "SERIAL PRIMARY KEY" if DATABASE_URL else "INTEGER PRIMARY KEY AUTOINCREMENT"
    timestamp_type = "TIMESTAMP" if DATABASE_URL else "TEXT"

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_importacao_lotes (
        id {id_pk},
        arquivo_nome TEXT NOT NULL,
        arquivo_hash TEXT NOT NULL,
        tipo_importador TEXT NOT NULL,
        modo_origem TEXT NOT NULL,
        usuario_id INTEGER,
        usuario_nome TEXT NOT NULL,
        iniciado_em {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finalizado_em {timestamp_type},
        status TEXT NOT NULL,
        quantidade_total INTEGER NOT NULL DEFAULT 0,
        importadas INTEGER NOT NULL DEFAULT 0,
        identicas INTEGER NOT NULL DEFAULT 0,
        conflitantes INTEGER NOT NULL DEFAULT 0,
        rejeitadas INTEGER NOT NULL DEFAULT 0,
        mensagem_final TEXT,
        metadados_tecnicos TEXT NOT NULL DEFAULT '{{}}'
    )
    """)

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_origens (
        id {id_pk},
        movimentacao_id INTEGER NOT NULL,
        papel TEXT NOT NULL,
        modo TEXT NOT NULL,
        sistema_origem TEXT NOT NULL,
        modulo_origem TEXT,
        tipo_evento TEXT NOT NULL,
        evento_id_interno TEXT,
        chave_externa TEXT,
        chave_idempotente TEXT,
        lote_importacao_id INTEGER,
        linha_arquivo INTEGER,
        usuario_id INTEGER,
        usuario_nome TEXT NOT NULL,
        criado_em {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
        metadados TEXT NOT NULL DEFAULT '{{}}',
        status TEXT NOT NULL DEFAULT 'ATIVA',
        auditoria_id INTEGER
    )
    """)

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_importacao_linhas (
        id {id_pk},
        lote_id INTEGER NOT NULL,
        numero_linha INTEGER NOT NULL,
        hash_normalizado TEXT NOT NULL,
        status TEXT NOT NULL,
        movimentacao_id INTEGER,
        chave_encontrada TEXT,
        mensagem TEXT,
        campos_normalizados TEXT NOT NULL DEFAULT '{{}}',
        auditoria_id INTEGER,
        criado_em {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_configuracao_corte (
        id {id_pk},
        data_corte TEXT,
        ativo INTEGER NOT NULL DEFAULT 0,
        usuario_id INTEGER,
        usuario_nome TEXT,
        justificativa TEXT,
        ativado_em {timestamp_type},
        atualizado_em {timestamp_type} NOT NULL DEFAULT CURRENT_TIMESTAMP,
        historico_alteracoes TEXT NOT NULL DEFAULT '[]'
    )
    """)

    indices = [
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mov_fin_origem_principal_ativa
        ON movimentacoes_financeiras_origens (movimentacao_id)
        WHERE papel = 'PRINCIPAL' AND status = 'ATIVA'
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_movimentacao
        ON movimentacoes_financeiras_origens (movimentacao_id, papel, status)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_modo
        ON movimentacoes_financeiras_origens (modo, status)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_chave_externa
        ON movimentacoes_financeiras_origens (chave_externa)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_lote
        ON movimentacoes_financeiras_origens (lote_importacao_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_idempotente
        ON movimentacoes_financeiras_origens (chave_idempotente)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_lote_hash
        ON movimentacoes_financeiras_importacao_lotes (arquivo_hash, tipo_importador)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_lote_status_data
        ON movimentacoes_financeiras_importacao_lotes (status, iniciado_em)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_linha_lote_numero
        ON movimentacoes_financeiras_importacao_linhas (lote_id, numero_linha)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_linha_status
        ON movimentacoes_financeiras_importacao_linhas (status, criado_em)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_mov_fin_linha_movimentacao
        ON movimentacoes_financeiras_importacao_linhas (movimentacao_id)
        """,
    ]
    for comando in indices:
        cursor.execute(comando)

    if conexao_propria:
        conn.commit()
        conn.close()


def registrar_origem_principal_cursor(
    cursor,
    movimentacao_id,
    modo,
    sistema_origem,
    tipo_evento,
    usuario_id,
    usuario_nome,
    modulo_origem=None,
    evento_id_interno=None,
    chave_externa=None,
    chave_idempotente=None,
    lote_importacao_id=None,
    linha_arquivo=None,
    metadados=None,
    auditoria_id=None,
):
    if modo not in MODOS_ORIGEM_PERSISTIVEIS:
        raise ValueError("Modo de origem persistente inválido.")
    if not movimentacao_id:
        raise ValueError("Movimentação obrigatória para registrar origem.")
    if not str(sistema_origem or "").strip() or not str(tipo_evento or "").strip():
        raise ValueError("Sistema e tipo do evento de origem são obrigatórios.")
    if not usuario_id or not str(usuario_nome or "").strip():
        raise ValueError("Usuário autenticado é obrigatório para registrar origem.")

    cursor.execute(q("""
    SELECT id
    FROM movimentacoes_financeiras_origens
    WHERE movimentacao_id = ?
      AND papel = ?
      AND status = ?
    """), (movimentacao_id, PAPEL_ORIGEM_PRINCIPAL, STATUS_ORIGEM_ATIVA))
    if cursor.fetchone():
        raise ValueError("A movimentação já possui origem principal ativa.")

    cursor.execute(q("""
    INSERT INTO movimentacoes_financeiras_origens (
        movimentacao_id, papel, modo, sistema_origem, modulo_origem,
        tipo_evento, evento_id_interno, chave_externa, chave_idempotente,
        lote_importacao_id, linha_arquivo, usuario_id, usuario_nome,
        metadados, status, auditoria_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        movimentacao_id,
        PAPEL_ORIGEM_PRINCIPAL,
        modo,
        str(sistema_origem).strip(),
        str(modulo_origem or "").strip() or None,
        str(tipo_evento).strip(),
        str(evento_id_interno or "").strip() or None,
        str(chave_externa or "").strip() or None,
        str(chave_idempotente or "").strip() or None,
        lote_importacao_id,
        linha_arquivo,
        usuario_id,
        str(usuario_nome).strip(),
        _json_controlado(metadados, METADADOS_ORIGEM_PERMITIDOS),
        STATUS_ORIGEM_ATIVA,
        auditoria_id,
    ))
    if DATABASE_URL:
        cursor.execute("SELECT LASTVAL() AS id")
        return cursor.fetchone()["id"]
    return cursor.lastrowid


def vincular_auditoria_origem_cursor(cursor, origem_id, auditoria_id):
    cursor.execute(q("""
    UPDATE movimentacoes_financeiras_origens
    SET auditoria_id = ?
    WHERE id = ?
    """), (auditoria_id, origem_id))


def criar_lote_importacao_cursor(
    cursor,
    arquivo_nome,
    arquivo_hash,
    tipo_importador,
    usuario_id,
    usuario_nome,
    metadados_tecnicos=None,
):
    if not usuario_id or not str(usuario_nome or "").strip():
        raise ValueError("Usuário autenticado é obrigatório para importar.")
    cursor.execute(q("""
    INSERT INTO movimentacoes_financeiras_importacao_lotes (
        arquivo_nome, arquivo_hash, tipo_importador, modo_origem,
        usuario_id, usuario_nome, status, metadados_tecnicos
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        sanitizar_nome_arquivo(arquivo_nome),
        arquivo_hash,
        tipo_importador,
        IMPORTACAO_FINANCEIRA,
        usuario_id,
        str(usuario_nome).strip(),
        STATUS_LOTE_PROCESSANDO,
        _json_controlado(metadados_tecnicos),
    ))
    if DATABASE_URL:
        cursor.execute("SELECT LASTVAL() AS id")
        return cursor.fetchone()["id"]
    return cursor.lastrowid


def finalizar_lote_importacao_cursor(
    cursor,
    lote_id,
    quantidade_total,
    importadas,
    identicas,
    conflitantes,
    rejeitadas,
    mensagem_final,
):
    status = (
        STATUS_LOTE_CONFLITOS
        if conflitantes or rejeitadas
        else STATUS_LOTE_CONCLUIDO
    )
    cursor.execute(q("""
    UPDATE movimentacoes_financeiras_importacao_lotes
    SET finalizado_em = ?,
        status = ?,
        quantidade_total = ?,
        importadas = ?,
        identicas = ?,
        conflitantes = ?,
        rejeitadas = ?,
        mensagem_final = ?
    WHERE id = ?
    """), (
        datetime.now().isoformat(timespec="seconds"),
        status,
        quantidade_total,
        importadas,
        identicas,
        conflitantes,
        rejeitadas,
        str(mensagem_final or "").strip(),
        lote_id,
    ))
    return status


def falhar_lote_importacao_cursor(cursor, lote_id, quantidade_total, mensagem_final):
    cursor.execute(q("""
    UPDATE movimentacoes_financeiras_importacao_lotes
    SET finalizado_em = ?,
        status = ?,
        quantidade_total = ?,
        mensagem_final = ?
    WHERE id = ?
    """), (
        datetime.now().isoformat(timespec="seconds"),
        STATUS_LOTE_FALHOU,
        quantidade_total,
        str(mensagem_final or "Falha integral da importação").strip()[:1000],
        lote_id,
    ))


def registrar_linha_importacao_cursor(
    cursor,
    lote_id,
    numero_linha,
    hash_linha,
    status,
    movimentacao_id=None,
    chave_encontrada=None,
    mensagem=None,
    campos_normalizados=None,
    auditoria_id=None,
):
    if status not in {
        STATUS_LINHA_IMPORTADA,
        STATUS_LINHA_IDENTICA,
        STATUS_LINHA_CONFLITANTE,
        STATUS_LINHA_REJEITADA,
    }:
        raise ValueError("Status de linha de importação inválido.")
    cursor.execute(q("""
    INSERT INTO movimentacoes_financeiras_importacao_linhas (
        lote_id, numero_linha, hash_normalizado, status,
        movimentacao_id, chave_encontrada, mensagem,
        campos_normalizados, auditoria_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        lote_id,
        numero_linha,
        hash_linha,
        status,
        movimentacao_id,
        str(chave_encontrada or "").strip() or None,
        str(mensagem or "").strip() or None,
        _json_controlado(campos_normalizados),
        auditoria_id,
    ))


def resolver_modo_origem_leitura(item):
    modo = (item.get("modo_origem") if hasattr(item, "get") else None) or LEGADO_IMPORTADO
    return modo if modo in MODOS_ORIGEM else LEGADO_IMPORTADO


def aplicar_origem_leitura(item):
    item_dict = item if isinstance(item, dict) else dict(item)
    modo = resolver_modo_origem_leitura(item_dict)
    item_dict["modo_origem"] = modo
    item_dict["origem_rotulo"] = ROTULOS_MODOS_ORIGEM[modo]
    item_dict["origem_classe"] = modo.lower().replace("_", "-")
    item_dict["origem_persistida"] = bool(item_dict.get("origem_id"))
    return item_dict


def buscar_origem_principal_movimentacao(movimentacao_id):
    criar_tabelas_governanca_financeira()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
    SELECT
        o.*,
        l.arquivo_nome AS lote_arquivo_nome,
        l.arquivo_hash AS lote_arquivo_hash,
        l.status AS lote_status
    FROM movimentacoes_financeiras_origens o
    LEFT JOIN movimentacoes_financeiras_importacao_lotes l
      ON l.id = o.lote_importacao_id
    WHERE o.movimentacao_id = ?
      AND o.papel = ?
      AND o.status = ?
    """), (movimentacao_id, PAPEL_ORIGEM_PRINCIPAL, STATUS_ORIGEM_ATIVA))
    origem = cursor.fetchone()
    conn.close()
    if origem:
        origem_dict = dict(origem)
        origem_dict["origem_id"] = origem_dict["id"]
        origem_dict["modo_origem"] = origem_dict["modo"]
        try:
            metadados = json.loads(origem_dict.get("metadados") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadados = {}
        origem_dict["justificativa_origem"] = metadados.get("justificativa", "")
        origem_dict["referencia_evidencia"] = metadados.get("referencia_evidencia", "")
        return aplicar_origem_leitura(origem_dict)
    return {
        "origem_id": None,
        "movimentacao_id": movimentacao_id,
        "papel": PAPEL_ORIGEM_PRINCIPAL,
        "modo": LEGADO_IMPORTADO,
        "modo_origem": LEGADO_IMPORTADO,
        "origem_rotulo": ROTULOS_MODOS_ORIGEM[LEGADO_IMPORTADO],
        "origem_classe": "legado-importado",
        "origem_persistida": False,
        "sistema_origem": "FrigoDatta legado",
        "tipo_evento": "REGISTRO_HISTORICO",
    }


def listar_modos_origem_usados():
    criar_tabelas_governanca_financeira()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT modo, COUNT(*) AS quantidade
    FROM movimentacoes_financeiras_origens
    WHERE papel = 'PRINCIPAL' AND status = 'ATIVA'
    GROUP BY modo
    ORDER BY modo
    """)
    modos = [
        {
            "valor": item["modo"],
            "rotulo": ROTULOS_MODOS_ORIGEM.get(item["modo"], item["modo"]),
            "quantidade": int(item["quantidade"] or 0),
        }
        for item in cursor.fetchall()
        if item["modo"] in MODOS_ORIGEM
    ]
    cursor.execute("""
    SELECT COUNT(*) AS quantidade
    FROM movimentacoes_financeiras m
    LEFT JOIN movimentacoes_financeiras_origens o
      ON o.movimentacao_id = m.id
     AND o.papel = 'PRINCIPAL'
     AND o.status = 'ATIVA'
    WHERE o.id IS NULL
    """)
    legado = int(cursor.fetchone()["quantidade"] or 0)
    conn.close()
    if legado:
        modos.insert(0, {
            "valor": LEGADO_IMPORTADO,
            "rotulo": ROTULOS_MODOS_ORIGEM[LEGADO_IMPORTADO],
            "quantidade": legado,
        })
    return modos


def buscar_configuracao_corte():
    criar_tabelas_governanca_financeira()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT *
    FROM movimentacoes_financeiras_configuracao_corte
    ORDER BY id DESC
    LIMIT 1
    """)
    configuracao = cursor.fetchone()
    conn.close()
    if configuracao:
        resultado = dict(configuracao)
        resultado["situacao"] = "Ativada" if resultado.get("ativo") else "Não ativada"
        return resultado
    return {
        "id": None,
        "data_corte": None,
        "ativo": 0,
        "usuario_id": None,
        "usuario_nome": None,
        "justificativa": None,
        "ativado_em": None,
        "situacao": "Não ativada",
        "persistida": False,
    }


def montar_contexto_governanca_financeira():
    criar_tabelas_governanca_financeira()
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT
        COALESCE(o.modo, 'LEGADO_IMPORTADO') AS modo,
        COUNT(*) AS quantidade
    FROM movimentacoes_financeiras m
    LEFT JOIN movimentacoes_financeiras_origens o
      ON o.movimentacao_id = m.id
     AND o.papel = 'PRINCIPAL'
     AND o.status = 'ATIVA'
    GROUP BY COALESCE(o.modo, 'LEGADO_IMPORTADO')
    ORDER BY modo
    """)
    totais_modo = [
        {
            "modo": item["modo"],
            "rotulo": ROTULOS_MODOS_ORIGEM.get(item["modo"], item["modo"]),
            "quantidade": int(item["quantidade"] or 0),
        }
        for item in cursor.fetchall()
    ]

    cursor.execute("""
    SELECT *
    FROM movimentacoes_financeiras_importacao_lotes
    ORDER BY iniciado_em DESC, id DESC
    LIMIT 20
    """)
    lotes = [dict(item) for item in cursor.fetchall()]

    cursor.execute(q("""
    SELECT
        li.*,
        lo.arquivo_nome,
        lo.tipo_importador
    FROM movimentacoes_financeiras_importacao_linhas li
    JOIN movimentacoes_financeiras_importacao_lotes lo ON lo.id = li.lote_id
    WHERE li.status IN (?, ?)
    ORDER BY li.criado_em DESC, li.id DESC
    LIMIT 50
    """), (STATUS_LINHA_CONFLITANTE, STATUS_LINHA_REJEITADA))
    linhas_atencao = [dict(item) for item in cursor.fetchall()]

    cursor.execute(q("""
    SELECT
        m.id,
        m.data_documento,
        m.descricao,
        m.valor,
        m.status,
        o.usuario_nome,
        o.criado_em,
        o.metadados
    FROM movimentacoes_financeiras_origens o
    JOIN movimentacoes_financeiras m ON m.id = o.movimentacao_id
    WHERE o.modo = ?
      AND o.papel = ?
      AND o.status = ?
    ORDER BY o.criado_em DESC, o.id DESC
    LIMIT 50
    """), (MANUAL_CONTROLADO, PAPEL_ORIGEM_PRINCIPAL, STATUS_ORIGEM_ATIVA))
    manuais = [dict(item) for item in cursor.fetchall()]
    conn.close()

    for item in manuais:
        try:
            metadados = json.loads(item.get("metadados") or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            metadados = {}
        item["justificativa_origem"] = metadados.get("justificativa", "")
        item["referencia_evidencia"] = metadados.get("referencia_evidencia", "")

    return {
        "totais_modo": totais_modo,
        "lotes": lotes,
        "linhas_atencao": linhas_atencao,
        "manuais": manuais,
        "configuracao_corte": buscar_configuracao_corte(),
        "total_legado": next(
            (
                item["quantidade"]
                for item in totais_modo
                if item["modo"] == LEGADO_IMPORTADO
            ),
            0,
        ),
    }
