BEGIN;
CREATE TABLE IF NOT EXISTS linha_abate_programacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER UNIQUE NOT NULL,
    inicio_programado TEXT NOT NULL, fim_programado TEXT NOT NULL,
    inicio_real TEXT, fim_real TEXT,
    inicio_registrado_por TEXT, inicio_registrado_por_id INTEGER,
    fim_registrado_por TEXT, fim_registrado_por_id INTEGER,
    criado_por TEXT NOT NULL, criado_por_id INTEGER,
    criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL,
    versao INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS linha_abate_paradas_planejadas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, programacao_id INTEGER NOT NULL,
    categoria TEXT NOT NULL, inicio_previsto TEXT NOT NULL,
    fim_previsto TEXT NOT NULL, duracao_minutos INTEGER NOT NULL,
    observacao TEXT, ativa INTEGER NOT NULL DEFAULT 1,
    criado_por TEXT NOT NULL, criado_por_id INTEGER,
    criado_em TEXT NOT NULL, desativado_em TEXT, desativado_por TEXT
);
CREATE TABLE IF NOT EXISTS linha_abate_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER NOT NULL,
    entidade TEXT NOT NULL, entidade_id INTEGER, acao TEXT NOT NULL,
    valor_anterior TEXT, valor_novo TEXT, justificativa TEXT,
    usuario TEXT NOT NULL, usuario_id INTEGER, perfil TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
ALTER TABLE apontamentos_paradas ADD COLUMN afeta_linha_abate INTEGER;
ALTER TABLE apontamentos_paradas ADD COLUMN natureza_disponibilidade TEXT;
ALTER TABLE apontamentos_paradas ADD COLUMN classificacao_alterada_em TEXT;
ALTER TABLE apontamentos_paradas ADD COLUMN classificacao_alterada_por TEXT;
ALTER TABLE apontamentos_paradas ADD COLUMN classificacao_justificativa TEXT;
CREATE INDEX IF NOT EXISTS idx_linha_programacao_op ON linha_abate_programacoes(op_id);
CREATE INDEX IF NOT EXISTS idx_linha_pausas_programacao ON linha_abate_paradas_planejadas(programacao_id, ativa);
CREATE INDEX IF NOT EXISTS idx_linha_auditoria_op ON linha_abate_auditoria(op_id, criado_em);
CREATE INDEX IF NOT EXISTS idx_paradas_afeta_linha ON apontamentos_paradas(afeta_linha_abate, op_id, data);
COMMIT;
