-- Marco zero do estoque da Expedição.
-- Migration aditiva; os apontamentos de Produção e o PA histórico são preservados.

CREATE TABLE IF NOT EXISTS estoque_marcos (
    id SERIAL PRIMARY KEY,
    tipo TEXT UNIQUE NOT NULL,
    referencia_data TEXT NOT NULL,
    fuso_horario TEXT NOT NULL,
    legacy_max_op_id INTEGER NOT NULL,
    ativado_por TEXT NOT NULL,
    ativado_em TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'ATIVO'
);

CREATE TABLE IF NOT EXISTS estoque_eventos (
    id SERIAL PRIMARY KEY,
    caixa_id INTEGER,
    expedicao_id INTEGER,
    acao TEXT NOT NULL,
    situacao_anterior TEXT,
    situacao_nova TEXT,
    condicao_anterior TEXT,
    condicao_nova TEXT,
    quantidade REAL DEFAULT 0,
    peso REAL DEFAULT 0,
    justificativa TEXT,
    observacao TEXT,
    usuario TEXT NOT NULL,
    perfil TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL,
    idempotency_key TEXT UNIQUE
);

ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS estoque_classificacao TEXT DEFAULT 'POS_MARCO';
ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS estoque_marco_id INTEGER;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS estoque_operacional INTEGER DEFAULT 0;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS peso_tara REAL DEFAULT 0;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS condicao TEXT DEFAULT 'CONFORME';
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS disponibilidade TEXT DEFAULT 'PENDENTE_OP';
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS zona_estoque TEXT DEFAULT 'Conforme';
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS motivo_nao_conformidade TEXT;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS reservado_expedicao_id INTEGER;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS formado_por TEXT;
ALTER TABLE pa_caixas ADD COLUMN IF NOT EXISTS formado_em TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS origem TEXT DEFAULT 'Abatedouro';
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS criado_por TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS perfil_criacao TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS atualizado_em TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS concluido_em TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS cancelado_em TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS estornado_em TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS justificativa TEXT;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS situacao_anterior TEXT;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS condicao_anterior TEXT;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS local_anterior_id INTEGER;
