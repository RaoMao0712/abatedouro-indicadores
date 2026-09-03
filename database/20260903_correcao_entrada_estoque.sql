BEGIN;

-- O FrigoDatta autoriza a acao pelo perfil da sessao; nao existe cadastro
-- persistente de permissoes. CORRIGIR_ENTRADA_ESTOQUE = admin/gerencia no servico.
ALTER TABLE almoxarifado_lotes ADD COLUMN IF NOT EXISTS validade TEXT;
ALTER TABLE almoxarifado_lotes ADD COLUMN IF NOT EXISTS criado_por TEXT;
ALTER TABLE almoxarifado_lotes ADD COLUMN IF NOT EXISTS versao INTEGER NOT NULL DEFAULT 0;
ALTER TABLE almoxarifado_lotes ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMP;
ALTER TABLE almoxarifado_movimentacoes ADD COLUMN IF NOT EXISTS criado_por TEXT;

CREATE TABLE IF NOT EXISTS almoxarifado_correcoes_entrada (
    id SERIAL PRIMARY KEY, entrada_id INTEGER NOT NULL, insumo_id INTEGER NOT NULL,
    usuario TEXT NOT NULL, usuario_id INTEGER, perfil TEXT NOT NULL, motivo TEXT NOT NULL,
    quantidade_anterior TEXT NOT NULL, quantidade_nova TEXT NOT NULL,
    valor_unitario_anterior TEXT NOT NULL, valor_unitario_novo TEXT NOT NULL,
    total_anterior TEXT NOT NULL, total_novo TEXT NOT NULL, impacto_financeiro TEXT NOT NULL,
    fornecedor_anterior TEXT, fornecedor_novo TEXT, documento_anterior TEXT, documento_novo TEXT,
    lote_anterior TEXT, lote_novo TEXT, validade_anterior TEXT, validade_nova TEXT,
    observacao_anterior TEXT, observacao_nova TEXT, metodo TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE, versao_anterior INTEGER NOT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_almox_correcoes_entrada ON almoxarifado_correcoes_entrada (entrada_id, id);

COMMIT;
