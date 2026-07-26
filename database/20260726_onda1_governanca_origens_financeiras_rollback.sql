-- Rollback tecnico da estrutura aditiva da Onda 1 (PostgreSQL).
-- Exportar a governanca antes de executar. Nao toca movimentacoes_financeiras.
BEGIN;

DROP INDEX IF EXISTS idx_mov_fin_linha_movimentacao;
DROP INDEX IF EXISTS idx_mov_fin_linha_status;
DROP INDEX IF EXISTS idx_mov_fin_linha_lote_numero;
DROP INDEX IF EXISTS idx_mov_fin_lote_status_data;
DROP INDEX IF EXISTS idx_mov_fin_lote_hash;
DROP INDEX IF EXISTS idx_mov_fin_origem_idempotente;
DROP INDEX IF EXISTS idx_mov_fin_origem_lote;
DROP INDEX IF EXISTS idx_mov_fin_origem_chave_externa;
DROP INDEX IF EXISTS idx_mov_fin_origem_modo;
DROP INDEX IF EXISTS idx_mov_fin_origem_movimentacao;
DROP INDEX IF EXISTS uq_mov_fin_origem_principal_ativa;

DROP TABLE IF EXISTS movimentacoes_financeiras_importacao_linhas;
DROP TABLE IF EXISTS movimentacoes_financeiras_origens;
DROP TABLE IF EXISTS movimentacoes_financeiras_importacao_lotes;
DROP TABLE IF EXISTS movimentacoes_financeiras_configuracao_corte;

COMMIT;
