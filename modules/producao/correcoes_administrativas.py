"""Correções administrativas auditáveis de ordens de produção encerradas."""

from datetime import datetime
import math

from database import DATABASE_URL, conectar, q
from database.migrations import executar_alteracao_segura


PERFIS_AUTORIZADOS = {"admin", "gerencia"}
CAMPO_PESO_ENTRADA = "peso_vivo"


def _parse_peso_decimal(valor):
    """Aceita decimal com vírgula pt-BR ou ponto, sem aceitar texto não numérico."""
    if valor is None:
        return None

    texto = str(valor).strip().replace(" ", "")
    if not texto:
        return None

    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")

    try:
        numero = float(texto)
    except (TypeError, ValueError):
        return None

    return numero if math.isfinite(numero) else None


def criar_tabelas_correcoes_administrativas_op():
    """Cria estruturas aditivas, preservando integralmente as OPs existentes."""
    conn = conectar()
    cursor = conn.cursor()

    if DATABASE_URL:
        cursor.execute(
            "ALTER TABLE ordens_producao "
            "ADD COLUMN IF NOT EXISTS bloqueada_administrativamente "
            "BOOLEAN NOT NULL DEFAULT FALSE"
        )
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS correcoes_administrativas_op (
            id SERIAL PRIMARY KEY,
            op_id INTEGER NOT NULL,
            numero_op INTEGER NOT NULL,
            usuario_id INTEGER,
            usuario_nome TEXT NOT NULL,
            perfil TEXT NOT NULL,
            campo_alterado TEXT NOT NULL,
            valor_anterior REAL NOT NULL,
            novo_valor REAL NOT NULL,
            motivo TEXT NOT NULL,
            observacoes TEXT,
            origem_sessao TEXT,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tentativas_correcao_administrativa_op (
            id SERIAL PRIMARY KEY,
            op_id INTEGER,
            numero_op INTEGER,
            usuario_id INTEGER,
            usuario_nome TEXT,
            perfil TEXT,
            campo_solicitado TEXT NOT NULL,
            valor_anterior REAL,
            valor_solicitado REAL,
            motivo TEXT,
            observacoes TEXT,
            origem_sessao TEXT,
            motivo_negacao TEXT NOT NULL,
            criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_correcoes_administrativas_op_op
        ON correcoes_administrativas_op (op_id, criado_em DESC)
        """)
    else:
        executar_alteracao_segura(
            cursor,
            conn,
            "ALTER TABLE ordens_producao "
            "ADD COLUMN bloqueada_administrativamente INTEGER NOT NULL DEFAULT 0",
        )
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS correcoes_administrativas_op (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER NOT NULL,
            numero_op INTEGER NOT NULL,
            usuario_id INTEGER,
            usuario_nome TEXT NOT NULL,
            perfil TEXT NOT NULL,
            campo_alterado TEXT NOT NULL,
            valor_anterior REAL NOT NULL,
            novo_valor REAL NOT NULL,
            motivo TEXT NOT NULL,
            observacoes TEXT,
            origem_sessao TEXT,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tentativas_correcao_administrativa_op (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_id INTEGER,
            numero_op INTEGER,
            usuario_id INTEGER,
            usuario_nome TEXT,
            perfil TEXT,
            campo_solicitado TEXT NOT NULL,
            valor_anterior REAL,
            valor_solicitado REAL,
            motivo TEXT,
            observacoes TEXT,
            origem_sessao TEXT,
            motivo_negacao TEXT NOT NULL,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """)
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_correcoes_administrativas_op_op
        ON correcoes_administrativas_op (op_id, criado_em DESC)
        """)
    conn.commit()
    conn.close()


def buscar_correcoes_op(op_id):
    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("""
        SELECT *
        FROM correcoes_administrativas_op
        WHERE op_id = ?
        ORDER BY criado_em DESC, id DESC
    """), (op_id,))
    correcoes = cursor.fetchall()
    conn.close()
    return correcoes


def _registrar_tentativa_negada(
    conn,
    *,
    op_id,
    op,
    usuario,
    perfil,
    novo_valor,
    motivo,
    observacoes,
    origem,
    negacao,
):
    cursor = conn.cursor()
    cursor.execute(q("""
        INSERT INTO tentativas_correcao_administrativa_op (
            op_id, numero_op, usuario_id, usuario_nome, perfil,
            campo_solicitado, valor_anterior, valor_solicitado, motivo,
            observacoes, origem_sessao, motivo_negacao
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """), (
        op_id,
        op["id"] if op else op_id,
        usuario.get("id"),
        usuario.get("nome") or "Usuário não identificado",
        perfil or "",
        CAMPO_PESO_ENTRADA,
        op["peso_vivo"] if op else None,
        novo_valor,
        motivo,
        observacoes,
        origem,
        negacao,
    ))
    conn.commit()


def corrigir_peso_entrada_op(
    op_id,
    novo_valor,
    motivo,
    observacoes,
    *,
    usuario,
    perfil,
    origem,
):
    """Altera somente peso_vivo e grava auditoria na mesma transação."""
    peso_corrigido = _parse_peso_decimal(novo_valor)

    motivo = str(motivo or "").strip()
    observacoes = str(observacoes or "").strip()
    perfil = str(perfil or "").strip().lower()

    conn = conectar()
    cursor = conn.cursor()
    cursor.execute(q("SELECT * FROM ordens_producao WHERE id = ?"), (op_id,))
    op = cursor.fetchone()

    negacao = None
    if not op:
        negacao = "OP não encontrada."
    elif perfil not in PERFIS_AUTORIZADOS:
        negacao = "Perfil sem permissão para correção administrativa."
    elif str(op["status"] or "").strip().lower() == "cancelada":
        negacao = "OP cancelada não pode ser corrigida."
    elif bool(op["bloqueada_administrativamente"]):
        negacao = "OP bloqueada administrativamente não pode ser corrigida."
    elif op["status"] != "Encerrada":
        negacao = "Somente OP encerrada pode receber correção administrativa."
    elif peso_corrigido is None or peso_corrigido <= 0:
        negacao = "O Peso de Entrada Corrigido deve ser maior que zero."
    elif not motivo:
        negacao = "O motivo da correção é obrigatório."

    if negacao:
        _registrar_tentativa_negada(
            conn,
            op_id=op_id,
            op=op,
            usuario=usuario,
            perfil=perfil,
            novo_valor=peso_corrigido,
            motivo=motivo,
            observacoes=observacoes,
            origem=origem,
            negacao=negacao,
        )
        conn.close()
        raise ValueError(negacao)

    valor_anterior = float(op["peso_vivo"])
    if peso_corrigido == valor_anterior:
        negacao = "O novo Peso de Entrada deve ser diferente do valor atual."
        _registrar_tentativa_negada(
            conn,
            op_id=op_id,
            op=op,
            usuario=usuario,
            perfil=perfil,
            novo_valor=peso_corrigido,
            motivo=motivo,
            observacoes=observacoes,
            origem=origem,
            negacao=negacao,
        )
        conn.close()
        raise ValueError(negacao)

    try:
        cursor.execute(q("""
            UPDATE ordens_producao
            SET peso_vivo = ?
            WHERE id = ?
              AND status = 'Encerrada'
              AND peso_vivo = ?
              AND NOT bloqueada_administrativamente
        """), (peso_corrigido, op_id, valor_anterior))
        if cursor.rowcount != 1:
            raise ValueError("A OP mudou de estado durante a correção.")

        cursor.execute(q("""
            INSERT INTO correcoes_administrativas_op (
                op_id, numero_op, usuario_id, usuario_nome, perfil,
                campo_alterado, valor_anterior, novo_valor, motivo,
                observacoes, origem_sessao, criado_em
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """), (
            op_id,
            op_id,
            usuario.get("id"),
            usuario.get("nome") or "Usuário não identificado",
            perfil,
            CAMPO_PESO_ENTRADA,
            valor_anterior,
            peso_corrigido,
            motivo,
            observacoes,
            origem,
            datetime.now().isoformat(sep=" ", timespec="seconds"),
        ))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    conn.close()
    return {
        "op_id": op_id,
        "valor_anterior": valor_anterior,
        "novo_valor": peso_corrigido,
    }
