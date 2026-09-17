BEGIN;

DROP INDEX IF EXISTS uq_retrabalho_eventos_idem;
DROP INDEX IF EXISTS idx_retrabalho_eventos_rt;
DROP TABLE IF EXISTS retrabalho_eventos;
DROP INDEX IF EXISTS idx_retrabalho_saidas_rt;
DROP TABLE IF EXISTS retrabalho_saidas;
DROP INDEX IF EXISTS idx_retrabalho_origens_rt;
DROP TABLE IF EXISTS retrabalho_origens;
DROP TABLE IF EXISTS retrabalhos;

COMMIT;
