BEGIN;

ALTER TABLE ordens_producao ADD COLUMN versao_operacional INTEGER NOT NULL DEFAULT 0;
ALTER TABLE apontamentos_producao ADD COLUMN vigente INTEGER NOT NULL DEFAULT 1;
ALTER TABLE apontamentos_producao ADD COLUMN invalidado_em TEXT;
ALTER TABLE apontamentos_producao ADD COLUMN invalidado_por TEXT;

CREATE TABLE IF NOT EXISTS op_operacoes_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id INTEGER NOT NULL,
    tipo TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    usuario TEXT NOT NULL,
    perfil TEXT NOT NULL,
    motivo TEXT NOT NULL,
    etapa_destino TEXT,
    status_anterior TEXT,
    status_posterior TEXT,
    preflight_json TEXT NOT NULL,
    efeitos_json TEXT NOT NULL,
    resultado_json TEXT NOT NULL,
    ip_origem TEXT,
    criado_em TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_op_operacoes_data ON op_operacoes_auditoria(op_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_apontamentos_producao_vigente ON apontamentos_producao(op_id, vigente);

COMMIT;
