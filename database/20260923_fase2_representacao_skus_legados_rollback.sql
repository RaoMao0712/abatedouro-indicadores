BEGIN;
ALTER TABLE sku_versoes DROP COLUMN IF EXISTS parametros_json;
ALTER TABLE sku_versoes DROP COLUMN IF EXISTS apresentacao;
ALTER TABLE sku_versoes DROP COLUMN IF EXISTS codigo;
COMMIT;
