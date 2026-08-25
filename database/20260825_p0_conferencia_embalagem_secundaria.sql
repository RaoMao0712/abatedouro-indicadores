BEGIN;

ALTER TABLE embalagem_secundaria_conferencias
    ADD COLUMN IF NOT EXISTS peso_tara TEXT NOT NULL DEFAULT '0';

ALTER TABLE embalagem_secundaria_conferencias
    ADD COLUMN IF NOT EXISTS saldo_pendente TEXT NOT NULL DEFAULT '0';

ALTER TABLE embalagem_secundaria_requisicoes
    ADD COLUMN IF NOT EXISTS repeticoes INTEGER NOT NULL DEFAULT 0;

ALTER TABLE embalagem_secundaria_requisicoes
    ADD COLUMN IF NOT EXISTS ultimo_reenvio_em TIMESTAMP;

COMMIT;
