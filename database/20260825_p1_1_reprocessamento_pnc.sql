BEGIN;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS galinhas_bloqueadas INTEGER NOT NULL DEFAULT 0;
ALTER TABLE pa_nao_conformes ADD COLUMN IF NOT EXISTS pacotes_bloqueados INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS pnc_reprocessamentos (
    id SERIAL PRIMARY KEY,
    pa_nao_conforme_id INTEGER NOT NULL REFERENCES pa_nao_conformes(id),
    status TEXT NOT NULL CHECK(status IN ('EM_ANDAMENTO','CONCLUIDO','CANCELADO')),
    idempotency_key TEXT NOT NULL UNIQUE,
    modalidade TEXT NOT NULL CHECK(modalidade IN ('INTEGRAL','PARCIAL')),
    peso_g BIGINT NOT NULL DEFAULT 0 CHECK(peso_g >= 0),
    caixas INTEGER NOT NULL DEFAULT 0 CHECK(caixas >= 0),
    bandejas INTEGER NOT NULL DEFAULT 0 CHECK(bandejas >= 0),
    galinhas INTEGER NOT NULL DEFAULT 0 CHECK(galinhas >= 0),
    pacotes INTEGER NOT NULL DEFAULT 0 CHECK(pacotes >= 0),
    justificativa TEXT NOT NULL, observacoes TEXT,
    iniciado_por TEXT NOT NULL, perfil_inicio TEXT NOT NULL, iniciado_em TIMESTAMP NOT NULL,
    concluido_por TEXT, concluido_em TIMESTAMP, cancelado_por TEXT, cancelado_em TIMESTAMP,
    justificativa_fechamento TEXT, snapshot_json TEXT NOT NULL, atualizado_em TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pnc_reprocessamento_registro
    ON pnc_reprocessamentos(pa_nao_conforme_id,status);
COMMIT;
