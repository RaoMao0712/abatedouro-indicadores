BEGIN;

ALTER TABLE pa_nao_conformes ALTER COLUMN op_id DROP NOT NULL;
ALTER TABLE pa_nao_conformes ALTER COLUMN caixa_id DROP NOT NULL;
ALTER TABLE pa_nao_conformes ALTER COLUMN lote DROP NOT NULL;

ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS tipo_registro TEXT NOT NULL DEFAULT 'CAIXA_RASTREADA';
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS validade TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS origem_entrada TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS data_contagem TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS responsaveis_contagem TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS validacao_qualidade TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS validacao_gerencia TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS condicao_inicial TEXT;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS caixas_iniciais INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS bandejas_iniciais INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS caixas_bloqueadas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS bandejas_bloqueadas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS saldo_inicial_g BIGINT NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS saldo_bloqueado_g BIGINT NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS saldo_pendente_g BIGINT NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS saldo_operacional_g BIGINT NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS saldo_reservado_operacional_g BIGINT NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS saldo_destinado_g BIGINT NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_pa_nc_idempotency_key ON pa_nao_conformes(idempotency_key) WHERE idempotency_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS pa_nao_conforme_solicitacoes (
    id SERIAL PRIMARY KEY,
    pa_nao_conforme_id INTEGER NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL,
    peso_g BIGINT NOT NULL CHECK (peso_g > 0),
    caixas INTEGER NOT NULL DEFAULT 0 CHECK (caixas >= 0),
    bandejas INTEGER NOT NULL DEFAULT 0 CHECK (bandejas >= 0),
    status TEXT NOT NULL,
    justificativa TEXT NOT NULL,
    observacoes TEXT,
    solicitado_por TEXT NOT NULL,
    perfil_solicitante TEXT NOT NULL,
    solicitado_em TIMESTAMP NOT NULL,
    decidido_por TEXT,
    perfil_decisor TEXT,
    decidido_em TIMESTAMP,
    justificativa_decisao TEXT,
    criado_em TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pa_nc_solicitacoes ON pa_nao_conforme_solicitacoes(pa_nao_conforme_id, status);

ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS pa_nao_conforme_id INTEGER;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS quantidade_caixas INTEGER DEFAULT 0;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS quantidade_bandejas INTEGER DEFAULT 0;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS origem_tipo TEXT;

COMMIT;
