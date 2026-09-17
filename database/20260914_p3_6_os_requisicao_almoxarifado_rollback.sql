-- Rollback da P3.6: remove o vinculo OS -> Requisicao de Almoxarifado.
-- Nao destrutivo para as demais colunas/tabelas; remove apenas o que esta
-- migration adicionou.
BEGIN;
DROP INDEX IF EXISTS idx_almox_req_ordem_servico;
ALTER TABLE almoxarifado_requisicoes DROP COLUMN IF EXISTS ordem_servico_id;
COMMIT;
