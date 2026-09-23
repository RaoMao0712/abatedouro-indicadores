BEGIN;
ALTER TABLE sku_versoes ADD COLUMN codigo TEXT;
ALTER TABLE sku_versoes ADD COLUMN apresentacao TEXT;
ALTER TABLE sku_versoes ADD COLUMN parametros_json TEXT NOT NULL DEFAULT '{}';
COMMIT;
