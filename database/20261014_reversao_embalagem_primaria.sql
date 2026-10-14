ALTER TABLE embalagem_primaria_apontamentos
    ADD COLUMN IF NOT EXISTS vigente INTEGER NOT NULL DEFAULT 1;
ALTER TABLE embalagem_primaria_apontamentos
    ADD COLUMN IF NOT EXISTS invalidado_em TIMESTAMP;
ALTER TABLE embalagem_primaria_apontamentos
    ADD COLUMN IF NOT EXISTS invalidado_por TEXT;
ALTER TABLE embalagem_primaria_apontamentos
    ADD COLUMN IF NOT EXISTS invalidacao_motivo TEXT;
ALTER TABLE estoque_produto_intermediario
    ADD COLUMN IF NOT EXISTS apontamento_origem_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_primaria_op_vigente
    ON embalagem_primaria_apontamentos (op_id, vigente, id);
CREATE INDEX IF NOT EXISTS idx_pi_apontamento_origem
    ON estoque_produto_intermediario (apontamento_origem_id, tipo);
