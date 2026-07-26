-- Onda 1: origem e governanca financeira (SQLite).
-- Migration estritamente aditiva, sem backfill ou alteracao economica.
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_importacao_lotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_nome TEXT NOT NULL,
    arquivo_hash TEXT NOT NULL,
    tipo_importador TEXT NOT NULL,
    modo_origem TEXT NOT NULL,
    usuario_id INTEGER,
    usuario_nome TEXT NOT NULL,
    iniciado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finalizado_em TEXT,
    status TEXT NOT NULL,
    quantidade_total INTEGER NOT NULL DEFAULT 0,
    importadas INTEGER NOT NULL DEFAULT 0,
    identicas INTEGER NOT NULL DEFAULT 0,
    conflitantes INTEGER NOT NULL DEFAULT 0,
    rejeitadas INTEGER NOT NULL DEFAULT 0,
    mensagem_final TEXT,
    metadados_tecnicos TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_origens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadados TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'ATIVA',
    auditoria_id INTEGER
);

CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_importacao_linhas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lote_id INTEGER NOT NULL,
    numero_linha INTEGER NOT NULL,
    hash_normalizado TEXT NOT NULL,
    status TEXT NOT NULL,
    movimentacao_id INTEGER,
    chave_encontrada TEXT,
    mensagem TEXT,
    campos_normalizados TEXT NOT NULL DEFAULT '{}',
    auditoria_id INTEGER,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_configuracao_corte (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    data_corte TEXT,
    ativo INTEGER NOT NULL DEFAULT 0,
    usuario_id INTEGER,
    usuario_nome TEXT,
    justificativa TEXT,
    ativado_em TEXT,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    historico_alteracoes TEXT NOT NULL DEFAULT '[]'
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mov_fin_origem_principal_ativa
ON movimentacoes_financeiras_origens (movimentacao_id)
WHERE papel = 'PRINCIPAL' AND status = 'ATIVA';

CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_movimentacao
ON movimentacoes_financeiras_origens (movimentacao_id, papel, status);
CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_modo
ON movimentacoes_financeiras_origens (modo, status);
CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_chave_externa
ON movimentacoes_financeiras_origens (chave_externa);
CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_lote
ON movimentacoes_financeiras_origens (lote_importacao_id);
CREATE INDEX IF NOT EXISTS idx_mov_fin_origem_idempotente
ON movimentacoes_financeiras_origens (chave_idempotente);
CREATE INDEX IF NOT EXISTS idx_mov_fin_lote_hash
ON movimentacoes_financeiras_importacao_lotes (arquivo_hash, tipo_importador);
CREATE INDEX IF NOT EXISTS idx_mov_fin_lote_status_data
ON movimentacoes_financeiras_importacao_lotes (status, iniciado_em);
CREATE INDEX IF NOT EXISTS idx_mov_fin_linha_lote_numero
ON movimentacoes_financeiras_importacao_linhas (lote_id, numero_linha);
CREATE INDEX IF NOT EXISTS idx_mov_fin_linha_status
ON movimentacoes_financeiras_importacao_linhas (status, criado_em);
CREATE INDEX IF NOT EXISTS idx_mov_fin_linha_movimentacao
ON movimentacoes_financeiras_importacao_linhas (movimentacao_id);

COMMIT;
