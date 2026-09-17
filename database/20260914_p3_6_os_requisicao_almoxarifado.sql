-- P3.6 PostgreSQL: vinculo OS de Manutencao -> Requisicao de Almoxarifado.
-- Migration aditiva, nullable. Nao ha backfill: somente novos vinculos apos
-- a implementacao (ver output/p3-6-os-rastreabilidade-etapa-a-auditoria.md).
BEGIN;
ALTER TABLE almoxarifado_requisicoes ADD COLUMN IF NOT EXISTS ordem_servico_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_almox_req_ordem_servico ON almoxarifado_requisicoes(ordem_servico_id);
COMMIT;
