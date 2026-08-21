BEGIN;

DROP INDEX IF EXISTS uq_pi_estorno_idempotencia;
DROP INDEX IF EXISTS idx_pi_caixa_tipo;
DROP INDEX IF EXISTS idx_estorno_op_data;
DROP INDEX IF EXISTS idx_estorno_caixa_data;
DROP TABLE IF EXISTS embalagem_secundaria_estornos;

ALTER TABLE estoque_eventos DROP COLUMN IF EXISTS evento_origem_id;
ALTER TABLE estoque_produto_intermediario DROP COLUMN IF EXISTS idempotency_key;
ALTER TABLE estoque_produto_intermediario DROP COLUMN IF EXISTS movimento_origem_id;
ALTER TABLE estoque_produto_intermediario DROP COLUMN IF EXISTS caixa_id;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS versao;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS estorno_evento_id;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS estorno_motivo;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS estornada_por;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS estornada_em;

COMMIT;
