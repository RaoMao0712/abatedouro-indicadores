BEGIN;
DROP INDEX IF EXISTS idx_apontamentos_mao_obra_parceiro;
ALTER TABLE apontamentos_mao_obra DROP COLUMN natureza_vinculo;
ALTER TABLE apontamentos_mao_obra DROP COLUMN parceiro_nome_snapshot;
ALTER TABLE apontamentos_mao_obra DROP COLUMN parceiro_id;
DROP TABLE parceiro_eventos;
DROP TABLE parceiro_papeis;
DROP TABLE parceiros;
COMMIT;
