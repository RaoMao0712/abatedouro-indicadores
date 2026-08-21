BEGIN;
DROP INDEX IF EXISTS idx_pnc_rom_descarte_item_classificacao;
DROP INDEX IF EXISTS idx_pnc_rom_descarte_destino;
DROP INDEX IF EXISTS idx_pnc_rom_descarte_emissao_status;
DROP INDEX IF EXISTS idx_pnc_rom_descarte_lancamento_status;
DROP INDEX IF EXISTS idx_pnc_rom_descarte_status_saida;
COMMIT;
