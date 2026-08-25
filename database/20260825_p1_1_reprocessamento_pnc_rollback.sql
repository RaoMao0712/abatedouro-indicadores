BEGIN;
DROP INDEX IF EXISTS idx_pnc_reprocessamento_registro;
DROP TABLE IF EXISTS pnc_reprocessamentos;
-- As colunas galinhas_bloqueadas e pacotes_bloqueados são compartilhadas com
-- o romaneio de descarte e, por segurança, não são removidas no rollback.
COMMIT;
