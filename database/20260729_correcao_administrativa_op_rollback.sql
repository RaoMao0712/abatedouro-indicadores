BEGIN;

DROP TABLE IF EXISTS tentativas_correcao_administrativa_op;
DROP TABLE IF EXISTS correcoes_administrativas_op;
ALTER TABLE ordens_producao DROP COLUMN IF EXISTS bloqueada_administrativamente;

COMMIT;
