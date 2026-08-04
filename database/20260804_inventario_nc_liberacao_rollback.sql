BEGIN;

-- O rollback preserva os saldos e a auditoria: somente remove a extensao de romaneio.
-- As colunas de saldo e a tabela de solicitacoes nao sao apagadas para evitar perda de dados.
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS origem_tipo;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS quantidade_bandejas;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS quantidade_caixas;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS pa_nao_conforme_id;

COMMIT;
