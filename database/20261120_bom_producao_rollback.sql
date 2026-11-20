BEGIN;

DROP TRIGGER trg_bom_item ON bom_item;
DROP TRIGGER trg_bom_versao ON bom;
DROP FUNCTION proteger_item_bom();
DROP FUNCTION proteger_versao_bom();
DROP INDEX uq_bom_ativa_produto;
DROP INDEX ix_bom_vigencia;
ALTER TABLE bom DROP CONSTRAINT bom_status_check;
UPDATE bom SET status = 'PUBLICADA' WHERE status = 'ATIVA';
ALTER TABLE bom ADD COLUMN ativa BOOLEAN NOT NULL DEFAULT FALSE;
UPDATE bom SET ativa = (status = 'PUBLICADA');
ALTER TABLE bom ADD CONSTRAINT bom_status_check CHECK (status IN ('RASCUNHO', 'PUBLICADA', 'INATIVA'));
ALTER TABLE bom ADD CONSTRAINT bom_ativa_check CHECK (ativa = (status = 'PUBLICADA'));
CREATE INDEX ix_bom_vigencia ON bom (produto_id, ativa, data_inicio_vigencia);
ALTER TABLE bom ADD CONSTRAINT ex_bom_vigencia
EXCLUDE USING gist (
    int8range(produto_id::bigint, produto_id::bigint, '[]') WITH =,
    daterange(data_inicio_vigencia, data_fim_vigencia, '[]') WITH &&
) WHERE (status <> 'RASCUNHO');

COMMIT;
