BEGIN;

DROP INDEX IF EXISTS idx_apontamentos_producao_vigente;
DROP INDEX IF EXISTS idx_op_operacoes_data;
DROP TABLE IF EXISTS op_operacoes_auditoria;
ALTER TABLE apontamentos_producao DROP COLUMN invalidado_por;
ALTER TABLE apontamentos_producao DROP COLUMN invalidado_em;
ALTER TABLE apontamentos_producao DROP COLUMN vigente;
ALTER TABLE ordens_producao DROP COLUMN versao_operacional;

COMMIT;
