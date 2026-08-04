BEGIN;

ALTER TABLE pa_nao_conforme_solicitacoes
    ADD COLUMN IF NOT EXISTS solicitado_por_id INTEGER;
ALTER TABLE pa_nao_conforme_solicitacoes
    ADD COLUMN IF NOT EXISTS decidido_por_id INTEGER;

COMMIT;
