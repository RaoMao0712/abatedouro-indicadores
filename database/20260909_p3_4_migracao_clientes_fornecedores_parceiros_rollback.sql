-- Rollback conservador PostgreSQL: recusa remover parceiros já usados após a P3.4.
BEGIN;
UPDATE clientes c SET parceiro_id=NULL FROM parceiro_migracoes_legado m
 WHERE m.tipo_legado='CLIENTE' AND m.id_legado=c.id
 AND NOT EXISTS(SELECT 1 FROM pedidos_venda p WHERE p.cliente_parceiro_id=m.parceiro_id)
 AND NOT EXISTS(SELECT 1 FROM expedicoes e WHERE e.cliente_parceiro_id=m.parceiro_id);
UPDATE fornecedores f SET parceiro_id=NULL FROM parceiro_migracoes_legado m
 WHERE m.tipo_legado='FORNECEDOR' AND m.id_legado=f.id
 AND NOT EXISTS(SELECT 1 FROM ordens_producao o WHERE o.fornecedor_parceiro_id=m.parceiro_id);
DELETE FROM parceiro_papeis pp USING parceiro_migracoes_legado m
 WHERE pp.parceiro_id=m.parceiro_id AND m.papel_adicionado=1
 AND pp.papel=CASE m.tipo_legado WHEN 'CLIENTE' THEN 'CLIENTE' ELSE 'FORNECEDOR' END
 AND NOT EXISTS(SELECT 1 FROM pedidos_venda p WHERE p.cliente_parceiro_id=m.parceiro_id)
 AND NOT EXISTS(SELECT 1 FROM expedicoes e WHERE e.cliente_parceiro_id=m.parceiro_id)
 AND NOT EXISTS(SELECT 1 FROM ordens_producao o WHERE o.fornecedor_parceiro_id=m.parceiro_id);
-- Parceiros e a trilha parceiro_migracoes_legado são deliberadamente
-- preservados como evidência. A exclusão física exige revisão humana.
COMMIT;
