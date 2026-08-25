BEGIN;
CREATE TABLE pnc_reprocessamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pa_nao_conforme_id INTEGER NOT NULL,
    status TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, modalidade TEXT NOT NULL,
    peso_g INTEGER NOT NULL DEFAULT 0, caixas INTEGER NOT NULL DEFAULT 0,
    bandejas INTEGER NOT NULL DEFAULT 0, galinhas INTEGER NOT NULL DEFAULT 0,
    pacotes INTEGER NOT NULL DEFAULT 0, justificativa TEXT NOT NULL, observacoes TEXT,
    iniciado_por TEXT NOT NULL, perfil_inicio TEXT NOT NULL, iniciado_em TEXT NOT NULL,
    concluido_por TEXT, concluido_em TEXT, cancelado_por TEXT, cancelado_em TEXT,
    justificativa_fechamento TEXT, snapshot_json TEXT NOT NULL, atualizado_em TEXT NOT NULL
);
CREATE INDEX idx_pnc_reprocessamento_registro ON pnc_reprocessamentos(pa_nao_conforme_id,status);
COMMIT;
