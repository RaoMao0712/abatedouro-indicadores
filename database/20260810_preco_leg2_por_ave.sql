BEGIN;
ALTER TABLE pedido_venda_itens ADD COLUMN IF NOT EXISTS quantidade_operacional_mil BIGINT;
ALTER TABLE pedido_venda_itens ADD COLUMN IF NOT EXISTS unidade_operacional TEXT;
ALTER TABLE pedido_venda_itens ADD COLUMN IF NOT EXISTS aves_por_unidade_operacional INTEGER;
ALTER TABLE pedido_venda_itens ADD COLUMN IF NOT EXISTS quantidade_comercial_mil BIGINT;
ALTER TABLE pedido_venda_itens ADD COLUMN IF NOT EXISTS base_preco TEXT;
COMMIT;

-- Sem UPDATE/BACKFILL: pedidos existentes permanecem integralmente históricos.
