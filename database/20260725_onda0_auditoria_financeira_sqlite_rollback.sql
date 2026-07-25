-- Rollback tecnico da estrutura aditiva da Onda 0 (SQLite).
-- Executar somente apos exportar a trilha. Nao toca movimentacoes_financeiras.
BEGIN IMMEDIATE;

DROP INDEX IF EXISTS idx_mov_fin_auditoria_movimentacao_data;
DROP TABLE IF EXISTS movimentacoes_financeiras_auditoria;

COMMIT;
