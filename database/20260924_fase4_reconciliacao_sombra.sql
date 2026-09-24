BEGIN;

CREATE TABLE IF NOT EXISTS op_config_reconciliacoes (
    id SERIAL PRIMARY KEY,
    op_id INTEGER NOT NULL,
    snapshot_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    executado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resultado_geral TEXT NOT NULL CHECK (resultado_geral IN ('PARIDADE','DIVERGENCIA','INCONCLUSIVO')),
    dimensoes_json TEXT NOT NULL,
    divergencias_json TEXT NOT NULL DEFAULT '[]',
    versao_comparacao INTEGER NOT NULL,
    revisao INTEGER NOT NULL,
    hash_comparacao TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(snapshot_id, versao_comparacao, revisao),
    UNIQUE(snapshot_id, versao_comparacao, hash_comparacao)
);

CREATE INDEX IF NOT EXISTS ix_op_config_reconciliacoes_op
    ON op_config_reconciliacoes(op_id, executado_em DESC);
CREATE INDEX IF NOT EXISTS ix_op_config_reconciliacoes_filtros
    ON op_config_reconciliacoes(resultado_geral, sku, executado_em DESC);

COMMIT;
