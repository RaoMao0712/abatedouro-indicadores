BEGIN;
ALTER TABLE requisicao_compra_itens ADD COLUMN IF NOT EXISTS quantidade_aprovada REAL;
-- Backfill seguro: RC ja decidida (aprovado_em preenchido) nunca teve ajuste registrado; aprovada = solicitada.
UPDATE requisicao_compra_itens i SET quantidade_aprovada = i.quantidade_solicitada
  FROM requisicoes_compra r
 WHERE r.id = i.requisicao_compra_id AND r.aprovado_em IS NOT NULL AND i.quantidade_aprovada IS NULL;
COMMIT;
