BEGIN;
ALTER TABLE pedido_venda_itens ADD COLUMN quantidade_operacional_mil INTEGER;
ALTER TABLE pedido_venda_itens ADD COLUMN unidade_operacional TEXT;
ALTER TABLE pedido_venda_itens ADD COLUMN aves_por_unidade_operacional INTEGER;
ALTER TABLE pedido_venda_itens ADD COLUMN quantidade_comercial_mil INTEGER;
ALTER TABLE pedido_venda_itens ADD COLUMN base_preco TEXT;
COMMIT;

-- Sem UPDATE/BACKFILL: pedidos existentes permanecem integralmente históricos.
