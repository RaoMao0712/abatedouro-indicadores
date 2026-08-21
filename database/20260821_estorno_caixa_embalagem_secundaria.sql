BEGIN;

ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS estornada_em TIMESTAMP;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS estornada_por TEXT;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS estorno_motivo TEXT;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS estorno_evento_id INTEGER;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS versao INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS usuario_pesagem TEXT;

ALTER TABLE estoque_produto_intermediario ADD COLUMN IF NOT EXISTS caixa_id INTEGER;
ALTER TABLE estoque_produto_intermediario ADD COLUMN IF NOT EXISTS movimento_origem_id INTEGER;
ALTER TABLE estoque_produto_intermediario ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE estoque_eventos ADD COLUMN IF NOT EXISTS evento_origem_id INTEGER;

CREATE TABLE IF NOT EXISTS embalagem_secundaria_estornos (
    id SERIAL PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('CAIXA', 'LOTE', 'OP')),
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
    criado_em TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_estorno_caixa_data
    ON embalagem_secundaria_estornos (caixa_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_estorno_op_data
    ON embalagem_secundaria_estornos (op_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_pi_caixa_tipo
    ON estoque_produto_intermediario (caixa_id, tipo);
CREATE UNIQUE INDEX IF NOT EXISTS uq_pi_estorno_idempotencia
    ON estoque_produto_intermediario (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS embalagem_secundaria_requisicoes (
    id SERIAL PRIMARY KEY,
    op_id INTEGER NOT NULL,
    acao TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    resultado_json TEXT NOT NULL,
    usuario TEXT,
    criado_em TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_req_emb_op_data
    ON embalagem_secundaria_requisicoes (op_id, criado_em);

CREATE TABLE IF NOT EXISTS embalagem_secundaria_conferencias (
    id SERIAL PRIMARY KEY,
    op_id INTEGER NOT NULL,
    usuario TEXT NOT NULL,
    perfil TEXT NOT NULL,
    confirmado_em TIMESTAMP NOT NULL,
    caixas_ativas INTEGER NOT NULL,
    caixas_estornadas INTEGER NOT NULL,
    total_bandejas TEXT NOT NULL,
    peso_bruto TEXT NOT NULL,
    peso_liquido TEXT NOT NULL,
    caixas_ativas_json TEXT NOT NULL,
    duplicidades_json TEXT NOT NULL,
    hash_conferencia TEXT NOT NULL,
    confirmada INTEGER NOT NULL DEFAULT 1 CHECK (confirmada IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_conf_emb_op_data
    ON embalagem_secundaria_conferencias (op_id, confirmado_em);

COMMIT;
