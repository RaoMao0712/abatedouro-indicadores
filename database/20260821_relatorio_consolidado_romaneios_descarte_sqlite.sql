BEGIN;
CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_status_saida
    ON pnc_romaneios_descarte(status, saida_fisica_em);
CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_lancamento_status
    ON pnc_romaneios_descarte(status, lancado_em);
CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_emissao_status
    ON pnc_romaneios_descarte(status, criado_em);
CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_destino
    ON pnc_romaneios_descarte(destino);
CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_item_classificacao
    ON pnc_romaneio_descarte_itens(produto, apresentacao, motivo);
COMMIT;
