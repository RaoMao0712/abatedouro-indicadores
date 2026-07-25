-- Onda 0: migration aditiva e idempotente da trilha financeira (PostgreSQL).
-- Nao altera, reclassifica ou preenche movimentacoes existentes.
BEGIN;

CREATE TABLE IF NOT EXISTS movimentacoes_financeiras_auditoria (
    id SERIAL PRIMARY KEY,
    movimentacao_id INTEGER NOT NULL,
    acao TEXT NOT NULL,
    estado_anterior TEXT,
    estado_posterior TEXT,
    usuario_id INTEGER,
    usuario_nome TEXT NOT NULL,
    perfil TEXT NOT NULL,
    data_hora TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    justificativa TEXT,
    origem_acao TEXT NOT NULL,
    referencia_importacao TEXT
);

CREATE INDEX IF NOT EXISTS idx_mov_fin_auditoria_movimentacao_data
ON movimentacoes_financeiras_auditoria (movimentacao_id, data_hora, id);

COMMIT;
