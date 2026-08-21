BEGIN;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS galinhas_bloqueadas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS pacotes_bloqueados INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conforme_solicitacoes ADD COLUMN IF NOT EXISTS romaneio_descarte_id INTEGER;
CREATE TABLE IF NOT EXISTS pnc_romaneios_descarte (
 id SERIAL PRIMARY KEY, numero TEXT NOT NULL UNIQUE, pa_nao_conforme_id INTEGER NOT NULL REFERENCES pa_nao_conformes(id),
 status TEXT NOT NULL CHECK(status IN ('RASCUNHO','CANCELADO','CONFIRMADO','ESTORNADO')), idempotency_key TEXT NOT NULL UNIQUE,
 saida_fisica_em TIMESTAMP NOT NULL, lancado_em TIMESTAMP NOT NULL, saida_ja_realizada INTEGER NOT NULL DEFAULT 0 CHECK(saida_ja_realizada IN (0,1)),
 destino TEXT NOT NULL, motorista TEXT NOT NULL, motorista_cpf TEXT, placa TEXT NOT NULL, responsavel_entrega TEXT NOT NULL,
 responsavel_recebimento TEXT, observacoes TEXT, referencia_manual TEXT, usuario_emissor TEXT NOT NULL, perfil_emissor TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, justificativa_estorno TEXT, estornado_por TEXT, estornado_em TIMESTAMP, criado_em TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS pnc_romaneio_descarte_itens (
 id SERIAL PRIMARY KEY, romaneio_id INTEGER NOT NULL UNIQUE REFERENCES pnc_romaneios_descarte(id), pa_nao_conforme_id INTEGER NOT NULL REFERENCES pa_nao_conformes(id),
 produto TEXT NOT NULL, apresentacao TEXT, motivo TEXT, caixas INTEGER NOT NULL DEFAULT 0 CHECK(caixas>=0), bandejas INTEGER NOT NULL DEFAULT 0 CHECK(bandejas>=0),
 galinhas INTEGER NOT NULL DEFAULT 0 CHECK(galinhas>=0), pacotes INTEGER NOT NULL DEFAULT 0 CHECK(pacotes>=0), peso_g BIGINT NOT NULL DEFAULT 0 CHECK(peso_g>=0), snapshot_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pnc_movimentos_descarte (
 id SERIAL PRIMARY KEY, pa_nao_conforme_id INTEGER NOT NULL REFERENCES pa_nao_conformes(id), romaneio_id INTEGER NOT NULL REFERENCES pnc_romaneios_descarte(id),
 movimento_origem_id INTEGER REFERENCES pnc_movimentos_descarte(id), tipo TEXT NOT NULL CHECK(tipo IN ('SAIDA_DESCARTE_PNC','ESTORNO_SAIDA_DESCARTE_PNC')),
 idempotency_key TEXT NOT NULL UNIQUE, produto TEXT NOT NULL, caixas INTEGER NOT NULL DEFAULT 0, bandejas INTEGER NOT NULL DEFAULT 0,
 galinhas INTEGER NOT NULL DEFAULT 0, pacotes INTEGER NOT NULL DEFAULT 0, peso_g BIGINT NOT NULL DEFAULT 0, usuario TEXT NOT NULL, perfil TEXT NOT NULL,
 saida_fisica_em TIMESTAMP NOT NULL, lancado_em TIMESTAMP NOT NULL, destino TEXT NOT NULL, justificativa TEXT NOT NULL, criado_em TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS pnc_romaneio_numeracoes (data_chave TEXT PRIMARY KEY, ultimo_numero INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_pnc ON pnc_romaneios_descarte(pa_nao_conforme_id,criado_em);
CREATE INDEX IF NOT EXISTS idx_pnc_rom_descarte_saida ON pnc_romaneios_descarte(saida_fisica_em,status);
CREATE INDEX IF NOT EXISTS idx_pnc_mov_descarte_pnc ON pnc_movimentos_descarte(pa_nao_conforme_id,criado_em);
CREATE OR REPLACE FUNCTION impedir_mutacao_pnc_descarte() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'Movimento/snapshot de descarte é imutável'; END; $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_pnc_movimentos_descarte_imutavel ON pnc_movimentos_descarte;
CREATE TRIGGER trg_pnc_movimentos_descarte_imutavel BEFORE UPDATE OR DELETE ON pnc_movimentos_descarte FOR EACH ROW EXECUTE FUNCTION impedir_mutacao_pnc_descarte();
DROP TRIGGER IF EXISTS trg_pnc_romaneio_descarte_itens_imutavel ON pnc_romaneio_descarte_itens;
CREATE TRIGGER trg_pnc_romaneio_descarte_itens_imutavel BEFORE UPDATE OR DELETE ON pnc_romaneio_descarte_itens FOR EACH ROW EXECUTE FUNCTION impedir_mutacao_pnc_descarte();
COMMIT;
