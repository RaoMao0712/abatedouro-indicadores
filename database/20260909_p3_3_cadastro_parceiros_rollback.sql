BEGIN;
DROP INDEX IF EXISTS idx_apontamentos_mao_obra_parceiro;
ALTER TABLE apontamentos_mao_obra DROP COLUMN IF EXISTS natureza_vinculo;
ALTER TABLE apontamentos_mao_obra DROP COLUMN IF EXISTS parceiro_nome_snapshot;
ALTER TABLE apontamentos_mao_obra DROP COLUMN IF EXISTS parceiro_id;
DROP TABLE IF EXISTS parceiro_eventos;
DROP TABLE IF EXISTS parceiro_papeis;
DROP TABLE IF EXISTS parceiros;
COMMIT;
