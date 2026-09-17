-- Executar somente antes de qualquer uso operacional dos novos IDs canônicos.
BEGIN;
UPDATE clientes SET parceiro_id=NULL WHERE id IN (
 SELECT m.id_legado FROM parceiro_migracoes_legado m WHERE m.tipo_legado='CLIENTE'
 AND NOT EXISTS(SELECT 1 FROM pedidos_venda p WHERE p.cliente_parceiro_id=m.parceiro_id)
 AND NOT EXISTS(SELECT 1 FROM expedicoes e WHERE e.cliente_parceiro_id=m.parceiro_id));
UPDATE fornecedores SET parceiro_id=NULL WHERE id IN (
 SELECT m.id_legado FROM parceiro_migracoes_legado m WHERE m.tipo_legado='FORNECEDOR'
 AND NOT EXISTS(SELECT 1 FROM ordens_producao o WHERE o.fornecedor_parceiro_id=m.parceiro_id));
DELETE FROM parceiro_papeis WHERE EXISTS (
 SELECT 1 FROM parceiro_migracoes_legado m WHERE m.parceiro_id=parceiro_papeis.parceiro_id
 AND m.papel_adicionado=1 AND parceiro_papeis.papel=CASE m.tipo_legado WHEN 'CLIENTE' THEN 'CLIENTE' ELSE 'FORNECEDOR' END
 AND NOT EXISTS(SELECT 1 FROM pedidos_venda p WHERE p.cliente_parceiro_id=m.parceiro_id)
 AND NOT EXISTS(SELECT 1 FROM expedicoes e WHERE e.cliente_parceiro_id=m.parceiro_id)
 AND NOT EXISTS(SELECT 1 FROM ordens_producao o WHERE o.fornecedor_parceiro_id=m.parceiro_id));
-- Parceiros e a trilha de migração são preservados como evidência; a remoção
-- física só pode ocorrer após revisão humana das dependências.
COMMIT;
