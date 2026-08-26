-- P2.3: subledger aditivo de CMV. Nao altera nem recalcula estoque historico.
CREATE TABLE IF NOT EXISTS cmv_camadas (
    id SERIAL PRIMARY KEY, produto TEXT NOT NULL, unidade TEXT NOT NULL,
    data_entrada TEXT NOT NULL, quantidade_inicial REAL NOT NULL,
    quantidade_disponivel REAL NOT NULL, custo_unitario REAL,
    custo_conhecido INTEGER NOT NULL DEFAULT 0, origem_tipo TEXT NOT NULL,
    origem_id TEXT, documento TEXT, op_id INTEGER, lote TEXT,
    idempotency_key TEXT NOT NULL UNIQUE, status TEXT NOT NULL DEFAULT 'ATIVA',
    criado_por TEXT NOT NULL, criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cmv_eventos (
    id SERIAL PRIMARY KEY, tipo TEXT NOT NULL, data_evento TEXT NOT NULL,
    documento TEXT NOT NULL, produto TEXT NOT NULL, unidade TEXT NOT NULL,
    quantidade REAL NOT NULL, quantidade_com_custo REAL NOT NULL DEFAULT 0,
    quantidade_sem_custo REAL NOT NULL DEFAULT 0, custo_total REAL,
    estado_calculo TEXT NOT NULL, evento_original_id INTEGER,
    origem_tipo TEXT NOT NULL, origem_id TEXT, idempotency_key TEXT NOT NULL UNIQUE,
    justificativa TEXT, criado_por TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cmv_consumos (
    id SERIAL PRIMARY KEY, evento_id INTEGER NOT NULL, camada_id INTEGER,
    quantidade REAL NOT NULL, custo_unitario REAL, custo_total REAL,
    custo_conhecido INTEGER NOT NULL DEFAULT 0, ordem_fifo INTEGER NOT NULL,
    restaurado INTEGER NOT NULL DEFAULT 0, criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS cmv_auditoria (
    id SERIAL PRIMARY KEY, entidade TEXT NOT NULL, entidade_id INTEGER NOT NULL,
    acao TEXT NOT NULL, dados TEXT, usuario TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_cmv_camadas_fifo ON cmv_camadas(produto,unidade,status,data_entrada,id);
CREATE INDEX IF NOT EXISTS idx_cmv_eventos_periodo ON cmv_eventos(data_evento,tipo,estado_calculo);
CREATE INDEX IF NOT EXISTS idx_cmv_consumos_evento ON cmv_consumos(evento_id,ordem_fifo);
