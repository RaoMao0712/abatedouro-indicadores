-- P1.2: preserva itens removidos de romaneios abertos sem hard delete.
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS ativo INTEGER NOT NULL DEFAULT 1;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS removido_em TEXT;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS removido_por TEXT;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS motivo_remocao TEXT;
CREATE INDEX IF NOT EXISTS idx_expedicao_itens_ativos
    ON expedicao_itens (expedicao_id, ativo, id);
