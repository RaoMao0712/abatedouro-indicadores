BEGIN;
ALTER TABLE sku_versoes DROP COLUMN parametros_json;
ALTER TABLE sku_versoes DROP COLUMN apresentacao;
ALTER TABLE sku_versoes DROP COLUMN codigo;
COMMIT;
