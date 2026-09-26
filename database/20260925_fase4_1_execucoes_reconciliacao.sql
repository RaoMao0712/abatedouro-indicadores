BEGIN;

CREATE TABLE IF NOT EXISTS op_config_reconciliacao_execucoes (
    id SERIAL PRIMARY KEY,
    op_id INTEGER NOT NULL,
    snapshot_id INTEGER NOT NULL,
    versao_comparacao INTEGER NOT NULL,
    gatilho TEXT NOT NULL,
    tentativa INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDENTE','PROCESSANDO','SUCESSO','ERRO')),
    reconciliacao_id INTEGER,
    erro_tipo TEXT,
    erro_mensagem TEXT,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    iniciado_em TIMESTAMP,
    concluido_em TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_id, versao_comparacao, gatilho, tentativa)
);

CREATE INDEX IF NOT EXISTS ix_op_config_reconciliacao_execucoes_estado
    ON op_config_reconciliacao_execucoes(status, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_op_config_reconciliacao_execucoes_op
    ON op_config_reconciliacao_execucoes(op_id, id DESC);

COMMIT;
