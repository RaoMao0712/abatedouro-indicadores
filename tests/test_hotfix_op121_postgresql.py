"""Regressão PostgreSQL do encerramento da OP 121 (Galinha Inteira)."""

import json
import os
from urllib.parse import urlparse

import pytest


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL ausente; suíte PostgreSQL-only",
)

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

    from flask import Flask, session

    from database import conectar, q
    from modules.expedicao.estoque_service import criar_tabelas_estoque_confiavel
    from modules.expedicao.services import (
        criar_tabelas_expedicao,
        criar_tabelas_estoque_pi_pa,
        registrar_apontamento_embalagem_primaria,
    )
    from modules.producao.operacoes_op import criar_tabelas_operacoes_op
    from modules.qualidade.produtos_nao_conformes import criar_tabelas_pa_nao_conforme

    app = Flask(__name__)
    app.secret_key = "teste-postgresql-op121"


def setup_module():
    if not TEST_DATABASE_URL:
        return
    nome_banco = urlparse(TEST_DATABASE_URL).path.lstrip("/").lower()
    if "test" not in nome_banco:
        raise RuntimeError("TEST_DATABASE_URL deve apontar para banco descartável identificado como teste.")
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute("DROP SCHEMA public CASCADE")
        cursor.execute("CREATE SCHEMA public")
        cursor.execute("""
        CREATE TABLE ordens_producao (
            id SERIAL PRIMARY KEY,
            data DATE NOT NULL,
            fornecedor TEXT NOT NULL,
            gta TEXT,
            nota_fiscal TEXT,
            quantidade_aves INTEGER NOT NULL,
            mortes_antes_pendura INTEGER DEFAULT 0,
            peso_vivo NUMERIC NOT NULL,
            peso_medio NUMERIC NOT NULL,
            observacoes TEXT,
            status TEXT DEFAULT 'Aberta',
            sku TEXT DEFAULT 'Galinha Cortada',
            estoque_classificacao TEXT DEFAULT 'POS_MARCO',
            estoque_marco_id INTEGER,
            bloqueada_administrativamente BOOLEAN DEFAULT FALSE,
            versao_operacional INTEGER DEFAULT 0
        )
        """)
        cursor.execute("""
        CREATE TABLE apontamentos_producao (
            id SERIAL PRIMARY KEY, op_id INTEGER NOT NULL, data DATE,
            setor TEXT, quantidade NUMERIC DEFAULT 0, unidade TEXT NOT NULL,
            observacoes TEXT, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            vigente INTEGER DEFAULT 1, invalidado_em TIMESTAMP, invalidado_por TEXT
        )
        """)
        cursor.execute("""
        CREATE TABLE apontamentos_descartes (
            id SERIAL PRIMARY KEY, op_id INTEGER NOT NULL, data DATE,
            setor TEXT, motivo TEXT, categoria TEXT,
            quantidade NUMERIC DEFAULT 0, unidade TEXT, observacoes TEXT,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()
    finally:
        conn.close()
    criar_tabelas_expedicao()
    criar_tabelas_estoque_pi_pa()
    criar_tabelas_estoque_confiavel()
    criar_tabelas_operacoes_op()
    criar_tabelas_pa_nao_conforme()


def _uma(sql, parametros=()):
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q(sql), parametros)
        return cursor.fetchone()
    finally:
        conn.close()


def test_op121_2000_menos_76_encerra_primaria_com_962_pacotes_v2_postgresql():
    conn = conectar()
    try:
        cursor = conn.cursor()
        cursor.execute(q("""
            INSERT INTO ordens_producao (
                data, fornecedor, quantidade_aves, mortes_antes_pendura,
                peso_vivo, peso_medio, status, sku
            ) VALUES ('2026-10-14', 'São Pedro Km 30', 2000, 0,
                      3080, 1.54, 'Aberta', 'Galinha Inteira')
            RETURNING id
        """))
        op_id = cursor.fetchone()["id"]
        cursor.execute(q("""
            INSERT INTO apontamentos_descartes (
                op_id, data, setor, motivo, categoria, quantidade, unidade
            ) VALUES (?, '2026-10-14', 'Recepção e Pendura',
                      'Morte na gaiola', 'Descarte', 3, 'aves')
        """), (op_id,))
        cursor.execute(q("""
            INSERT INTO apontamentos_descartes (
                op_id, data, setor, motivo, categoria, quantidade, unidade
            ) VALUES (?, '2026-10-14', 'Evisceração',
                      'Perdas OP 121', 'Descarte', 73, 'aves')
        """), (op_id,))
        conn.commit()
    finally:
        conn.close()

    op = _uma("SELECT * FROM ordens_producao WHERE id = ?", (op_id,))
    chave = f"HOTFIX-OP121-PG-{op_id}"
    with app.test_request_context("/"):
        session.update({"usuario_id": 1, "nome": "Teste OP 121", "perfil": "producao"})
        resultado = registrar_apontamento_embalagem_primaria(
            op, None, pacotes_1_ave=0, pacotes_2_aves=962,
            idempotency_key=chave,
        )
        repeticao = registrar_apontamento_embalagem_primaria(
            op, None, pacotes_1_ave=0, pacotes_2_aves=962,
            idempotency_key=chave,
        )

    apontamento = _uma(
        "SELECT * FROM embalagem_primaria_apontamentos WHERE op_id = ?", (op_id,)
    )
    posicao = _uma(
        "SELECT * FROM pa_caixas WHERE codigo_caixa = ?",
        (f"GI-PCT-OP-{op_id:05d}-V2",),
    )
    entrada = _uma("""
        SELECT COUNT(*) total, COALESCE(SUM(quantidade_bandejas), 0) quantidade
        FROM estoque_produto_intermediario
        WHERE op_id = ? AND tipo = 'ENTRADA_EMBALAGEM_PRIMARIA'
    """, (op_id,))
    livro = _uma("""
        SELECT
          COALESCE(SUM(CASE WHEN tipo='ENTRADA_EMBALAGEM_PRIMARIA'
                            THEN quantidade_bandejas
                            WHEN tipo='SAIDA_REVERSAO_EMBALAGEM_PRIMARIA'
                            THEN -quantidade_bandejas ELSE 0 END),0) primaria_liquida,
          COALESCE(SUM(CASE WHEN tipo LIKE 'ENTRADA%%' THEN quantidade_bandejas
                            WHEN tipo LIKE 'SAIDA%%' THEN -quantidade_bandejas
                            ELSE quantidade_bandejas END),0) saldo
        FROM estoque_produto_intermediario WHERE op_id = ?
    """, (op_id,))
    auditoria = _uma("""
        SELECT preflight_json FROM op_operacoes_auditoria
        WHERE op_id = ? AND tipo = 'ENCERRAMENTO_OP'
    """, (op_id,))
    preflight = json.loads(auditoria["preflight_json"])

    assert apontamento["quantidade_bandejas"] == 1924
    assert apontamento["pacotes_v1"] == 0
    assert apontamento["pacotes_v2"] == 962
    assert apontamento["total_galinhas"] == 1924
    assert posicao["quantidade_pacotes"] == 962
    assert posicao["quantidade_galinhas"] == 1924
    assert entrada["total"] == 1
    assert entrada["quantidade"] == 1924
    assert livro["primaria_liquida"] == 1924
    assert livro["saldo"] == 0
    assert preflight["bandejas_primaria"] == 1924
    assert preflight["bandejas_consumidas"] == 1924
    assert preflight["saldo_pi"] == 0
    assert preflight["permitido"] is True
    assert resultado["status_posterior"] == "Encerrada"
    assert repeticao["ja_encerrada"] is True
    assert _uma("SELECT status FROM ordens_producao WHERE id = ?", (op_id,))["status"] == "Encerrada"
    assert _uma("""
        SELECT COUNT(*) total FROM estoque_produto_intermediario
        WHERE op_id = ? AND tipo = 'SAIDA_EMBALAGEM_SECUNDARIA'
    """, (op_id,))["total"] == 0
    assert _uma("""
        SELECT COUNT(*) total FROM embalagem_secundaria_conferencias WHERE op_id = ?
    """, (op_id,))["total"] == 0
