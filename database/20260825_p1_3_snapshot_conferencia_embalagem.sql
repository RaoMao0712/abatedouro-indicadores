-- P1.3: snapshot documental completo da Conferência Analítica.
ALTER TABLE embalagem_secundaria_conferencias
    ADD COLUMN IF NOT EXISTS snapshot_json TEXT;

