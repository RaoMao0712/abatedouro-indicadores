BEGIN;

ALTER TABLE embalagem_secundaria_requisicoes DROP COLUMN IF EXISTS ultimo_reenvio_em;
ALTER TABLE embalagem_secundaria_requisicoes DROP COLUMN IF EXISTS repeticoes;
ALTER TABLE embalagem_secundaria_conferencias DROP COLUMN IF EXISTS saldo_pendente;
ALTER TABLE embalagem_secundaria_conferencias DROP COLUMN IF EXISTS peso_tara;

COMMIT;
