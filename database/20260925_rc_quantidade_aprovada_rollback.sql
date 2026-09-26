BEGIN;
ALTER TABLE requisicao_compra_itens DROP COLUMN IF EXISTS quantidade_aprovada;
COMMIT;
