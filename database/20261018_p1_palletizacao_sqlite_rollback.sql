BEGIN;
DROP TRIGGER IF EXISTS trg_pallet_codigo_imutavel;
DROP TRIGGER IF EXISTS trg_pallet_eventos_delete_append_only;
DROP TRIGGER IF EXISTS trg_pallet_eventos_update_append_only;
DROP TABLE IF EXISTS pallet_caixas_atuais;
DROP TABLE IF EXISTS pallet_caixa_eventos;
DROP TABLE IF EXISTS pallets;
DROP TABLE IF EXISTS pallet_codigo_sequencia;
COMMIT;
