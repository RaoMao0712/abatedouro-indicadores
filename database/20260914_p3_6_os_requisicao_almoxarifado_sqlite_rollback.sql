-- Rollback SQLite da P3.6 (vinculo OS -> Requisicao de Almoxarifado).
-- SQLite nao suporta DROP COLUMN em versoes antigas; recriar a tabela nao é
-- seguro de forma generica aqui. Ambiente de teste local: recriar o banco.
DROP INDEX IF EXISTS idx_almox_req_ordem_servico;
