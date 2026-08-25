BEGIN;

ALTER TABLE embalagem_secundaria_conferencias
    ADD COLUMN peso_tara TEXT NOT NULL DEFAULT '0';

ALTER TABLE embalagem_secundaria_conferencias
    ADD COLUMN saldo_pendente TEXT NOT NULL DEFAULT '0';

ALTER TABLE embalagem_secundaria_requisicoes
    ADD COLUMN repeticoes INTEGER NOT NULL DEFAULT 0;

ALTER TABLE embalagem_secundaria_requisicoes
    ADD COLUMN ultimo_reenvio_em TEXT;

COMMIT;
