-- Rollback técnico SQLite. O local oficial é preservado para manter referências de estoque.
DROP INDEX IF EXISTS idx_pa_nc_eventos;
DROP INDEX IF EXISTS idx_pa_nc_status;
DROP INDEX IF EXISTS idx_pa_nc_op;
DROP TABLE IF EXISTS pa_nao_conforme_eventos;
DROP TABLE IF EXISTS pa_nao_conformes;
