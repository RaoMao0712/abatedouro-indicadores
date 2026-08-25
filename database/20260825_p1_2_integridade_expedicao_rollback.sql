-- Execute somente após confirmar que não existem itens inativos que precisem permanecer auditáveis.
DROP INDEX IF EXISTS idx_expedicao_itens_ativos;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS motivo_remocao;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS removido_por;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS removido_em;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS ativo;
