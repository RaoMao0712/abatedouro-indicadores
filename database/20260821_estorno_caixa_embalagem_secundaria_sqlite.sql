BEGIN;
ALTER TABLE pa_caixas ADD COLUMN estornada_em TEXT;
ALTER TABLE pa_caixas ADD COLUMN estornada_por TEXT;
ALTER TABLE pa_caixas ADD COLUMN estorno_motivo TEXT;
ALTER TABLE pa_caixas ADD COLUMN estorno_evento_id INTEGER;
ALTER TABLE pa_caixas ADD COLUMN versao INTEGER NOT NULL DEFAULT 0;
ALTER TABLE estoque_produto_intermediario ADD COLUMN caixa_id INTEGER;
ALTER TABLE estoque_produto_intermediario ADD COLUMN movimento_origem_id INTEGER;
ALTER TABLE estoque_produto_intermediario ADD COLUMN idempotency_key TEXT;
ALTER TABLE estoque_eventos ADD COLUMN evento_origem_id INTEGER;
CREATE TABLE embalagem_secundaria_estornos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, op_id INTEGER NOT NULL,
    caixa_id INTEGER, idempotency_key TEXT NOT NULL UNIQUE, usuario TEXT NOT NULL,
    perfil TEXT NOT NULL, justificativa TEXT NOT NULL, status_anterior TEXT,
    status_posterior TEXT, snapshot_json TEXT NOT NULL, movimentos_json TEXT NOT NULL,
    totais_antes_json TEXT NOT NULL, totais_depois_json TEXT NOT NULL,
    resultado_json TEXT NOT NULL, ip_origem TEXT, criado_em TEXT NOT NULL
);
CREATE INDEX idx_estorno_caixa_data ON embalagem_secundaria_estornos(caixa_id, criado_em);
CREATE INDEX idx_estorno_op_data ON embalagem_secundaria_estornos(op_id, criado_em);
CREATE INDEX idx_pi_caixa_tipo ON estoque_produto_intermediario(caixa_id, tipo);
CREATE UNIQUE INDEX uq_pi_estorno_idempotencia ON estoque_produto_intermediario(idempotency_key)
    WHERE idempotency_key IS NOT NULL;
COMMIT;
