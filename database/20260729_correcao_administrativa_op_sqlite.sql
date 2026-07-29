BEGIN;

ALTER TABLE ordens_producao
    ADD COLUMN bloqueada_administrativamente INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS correcoes_administrativas_op (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id INTEGER NOT NULL,
    numero_op INTEGER NOT NULL,
    usuario_id INTEGER,
    usuario_nome TEXT NOT NULL,
    perfil TEXT NOT NULL,
    campo_alterado TEXT NOT NULL,
    valor_anterior REAL NOT NULL,
    novo_valor REAL NOT NULL,
    motivo TEXT NOT NULL,
    observacoes TEXT,
    origem_sessao TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_correcoes_administrativas_op_op
    ON correcoes_administrativas_op (op_id, criado_em DESC);

CREATE TABLE IF NOT EXISTS tentativas_correcao_administrativa_op (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id INTEGER,
    numero_op INTEGER,
    usuario_id INTEGER,
    usuario_nome TEXT,
    perfil TEXT,
    campo_solicitado TEXT NOT NULL,
    valor_anterior REAL,
    valor_solicitado REAL,
    motivo TEXT,
    observacoes TEXT,
    origem_sessao TEXT,
    motivo_negacao TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMIT;
