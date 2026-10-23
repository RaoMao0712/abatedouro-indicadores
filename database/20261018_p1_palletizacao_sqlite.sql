BEGIN;
CREATE TABLE IF NOT EXISTS pallet_codigo_sequencia (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    proximo INTEGER NOT NULL CHECK (proximo > 0)
);
INSERT OR IGNORE INTO pallet_codigo_sequencia(id, proximo) VALUES (1, 1);

CREATE TABLE IF NOT EXISTS pallets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'ABERTO' CHECK (status IN (
        'ABERTO', 'EM_FORMACAO', 'DISPONIVEL', 'RESERVADO',
        'PARCIALMENTE_CARREGADO', 'CARREGADO', 'ENCERRADO', 'CANCELADO'
    )),
    localizacao_atual_id INTEGER REFERENCES locais_estoque(id) ON DELETE RESTRICT,
    posicao_atual TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por TEXT NOT NULL,
    encerrado_em TEXT,
    encerrado_por TEXT,
    versao INTEGER NOT NULL DEFAULT 0 CHECK (versao >= 0),
    observacao TEXT
);

CREATE TABLE IF NOT EXISTS pallet_caixa_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id INTEGER NOT NULL REFERENCES pallets(id) ON DELETE RESTRICT,
    caixa_id INTEGER REFERENCES pa_caixas(id) ON DELETE RESTRICT,
    tipo_evento TEXT NOT NULL CHECK (tipo_evento IN (
        'PALLET_CRIADO', 'CAIXA_ADICIONADA', 'CAIXA_REMOVIDA', 'CAIXA_TRANSFERIDA',
        'PALLET_MOVIMENTADO', 'PALLET_AGRUPADO', 'PALLET_DESAGRUPADO',
        'PALLET_RESERVADO', 'RESERVA_PALLET_CANCELADA', 'PALLET_CARREGADO',
        'CARREGAMENTO_PARCIAL', 'CARREGAMENTO_PALLET_ESTORNADO',
        'PALLET_DEVOLVIDO_ESTOQUE', 'PALLET_ENCERRADO', 'PALLET_REABERTO',
        'PALLET_CANCELADO'
    )),
    pallet_origem_id INTEGER REFERENCES pallets(id) ON DELETE RESTRICT,
    pallet_destino_id INTEGER REFERENCES pallets(id) ON DELETE RESTRICT,
    expedicao_id INTEGER REFERENCES expedicoes(id) ON DELETE RESTRICT,
    evento_origem_id INTEGER REFERENCES pallet_caixa_eventos(id) ON DELETE RESTRICT,
    usuario TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    justificativa TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    dados_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS pallet_caixas_atuais (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pallet_id INTEGER NOT NULL REFERENCES pallets(id) ON DELETE RESTRICT,
    caixa_id INTEGER NOT NULL REFERENCES pa_caixas(id) ON DELETE RESTRICT,
    adicionado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    adicionado_por TEXT NOT NULL,
    evento_origem_id INTEGER NOT NULL REFERENCES pallet_caixa_eventos(id) ON DELETE RESTRICT,
    versao INTEGER NOT NULL DEFAULT 0 CHECK (versao >= 0),
    CONSTRAINT ux_pallet_caixas_atuais_caixa UNIQUE (caixa_id)
);

CREATE TABLE IF NOT EXISTS op_palletizacao_excecoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id INTEGER NOT NULL REFERENCES ordens_producao(id) ON DELETE RESTRICT,
    justificativa TEXT NOT NULL,
    usuario TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    caixas_sem_pallet INTEGER NOT NULL CHECK (caixas_sem_pallet >= 0),
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_op_palletizacao_excecoes_op
    ON op_palletizacao_excecoes(op_id, criado_em, id);

CREATE INDEX IF NOT EXISTS idx_pallets_local_status ON pallets(localizacao_atual_id, status);
CREATE INDEX IF NOT EXISTS idx_pallet_caixas_atuais_pallet ON pallet_caixas_atuais(pallet_id, id);
CREATE INDEX IF NOT EXISTS idx_pallet_eventos_pallet_data ON pallet_caixa_eventos(pallet_id, criado_em, id);
CREATE INDEX IF NOT EXISTS idx_pallet_eventos_caixa_data ON pallet_caixa_eventos(caixa_id, criado_em, id);
CREATE INDEX IF NOT EXISTS idx_pallet_eventos_origem ON pallet_caixa_eventos(evento_origem_id);

CREATE TRIGGER IF NOT EXISTS trg_pallet_eventos_update_append_only
BEFORE UPDATE ON pallet_caixa_eventos BEGIN
    SELECT RAISE(ABORT, 'pallet_caixa_eventos e append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_pallet_eventos_delete_append_only
BEFORE DELETE ON pallet_caixa_eventos BEGIN
    SELECT RAISE(ABORT, 'pallet_caixa_eventos e append-only');
END;
CREATE TRIGGER IF NOT EXISTS trg_pallet_codigo_imutavel
BEFORE UPDATE OF codigo ON pallets
WHEN NEW.codigo <> OLD.codigo BEGIN
    SELECT RAISE(ABORT, 'codigo do pallet e imutavel');
END;
COMMIT;
