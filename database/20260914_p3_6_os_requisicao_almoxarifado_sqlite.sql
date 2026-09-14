-- P3.6 SQLite: vinculo OS de Manutencao -> Requisicao de Almoxarifado.
-- Mantido para paridade documental; em SQLite o schema de testes continua
-- provisionado em runtime por criar_tabelas_requisicoes_almoxarifado().
ALTER TABLE almoxarifado_requisicoes ADD COLUMN ordem_servico_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_almox_req_ordem_servico ON almoxarifado_requisicoes(ordem_servico_id);
