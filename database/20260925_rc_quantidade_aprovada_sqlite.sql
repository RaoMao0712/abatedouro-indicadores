ALTER TABLE requisicao_compra_itens ADD COLUMN quantidade_aprovada REAL;
UPDATE requisicao_compra_itens SET quantidade_aprovada = quantidade_solicitada
 WHERE quantidade_aprovada IS NULL
   AND requisicao_compra_id IN (SELECT id FROM requisicoes_compra WHERE aprovado_em IS NOT NULL);
