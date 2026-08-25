-- SQLite 3.35+: migration aditiva da P1.2.
ALTER TABLE expedicao_itens ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1;
ALTER TABLE expedicao_itens ADD COLUMN removido_em TEXT;
ALTER TABLE expedicao_itens ADD COLUMN removido_por TEXT;
ALTER TABLE expedicao_itens ADD COLUMN motivo_remocao TEXT;
CREATE INDEX IF NOT EXISTS idx_expedicao_itens_ativos
    ON expedicao_itens (expedicao_id, ativo, id);
