-- Rollback técnico PostgreSQL. Não altera caixas, OPs, lotes ou históricos de estoque.
DROP INDEX IF EXISTS idx_pa_nc_eventos;
DROP INDEX IF EXISTS idx_pa_nc_status;
DROP INDEX IF EXISTS idx_pa_nc_op;
DROP TABLE IF EXISTS pa_nao_conforme_eventos;
DROP TABLE IF EXISTS pa_nao_conformes;
-- O local oficial é preservado para não invalidar referências de estoque existentes.
