BEGIN;

ALTER TABLE embalagem_secundaria_requisicoes DROP COLUMN ultimo_reenvio_em;
ALTER TABLE embalagem_secundaria_requisicoes DROP COLUMN repeticoes;
ALTER TABLE embalagem_secundaria_conferencias DROP COLUMN saldo_pendente;
ALTER TABLE embalagem_secundaria_conferencias DROP COLUMN peso_tara;

COMMIT;
