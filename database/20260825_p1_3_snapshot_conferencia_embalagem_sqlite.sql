-- SQLite 3.35+: alteração aditiva, sem backfill e sem tocar em saldos.
ALTER TABLE embalagem_secundaria_conferencias
    ADD COLUMN snapshot_json TEXT;

