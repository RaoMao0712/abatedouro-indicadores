-- Ordem de Retrabalho: transforma Produto Acabado existente em outro Produto
-- Acabado. Entidade própria, nunca escreve em ordens_producao nem em
-- pa_caixa_composicao (ver output/ordem-retrabalho-etapa-a-auditoria-desenho.md).
-- Documentação da migration; a criação efetiva em runtime é idempotente via
-- modules.retrabalho.services.criar_tabelas_retrabalho().
BEGIN;

CREATE TABLE IF NOT EXISTS retrabalhos (
    id SERIAL PRIMARY KEY,
    numero TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'ABERTA',
    motivo TEXT NOT NULL,
    sku_origem TEXT NOT NULL,
    apresentacao_origem TEXT,
    unidade_estoque_origem TEXT NOT NULL,
    sku_destino TEXT NOT NULL,
    apresentacao_destino TEXT,
    unidade_estoque_destino TEXT NOT NULL,
    galinhas_por_pacote_destino INTEGER,
    unidade_origem TEXT NOT NULL,
    unidade_destino TEXT NOT NULL,
    quantidade_planejada_origem REAL NOT NULL DEFAULT 0,
    quantidade_apontada_destino REAL,
    quantidade_perda REAL NOT NULL DEFAULT 0,
    unidade_perda TEXT,
    justificativa_perda TEXT,
    data_retrabalho TEXT NOT NULL,
    data_fabricacao_destino TEXT,
    data_validade_destino TEXT,
    local_estoque_id_destino INTEGER,
    observacoes TEXT,
    criado_por TEXT NOT NULL,
    perfil_criacao TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL,
    encerrado_por TEXT,
    encerrado_em TIMESTAMP,
    liberado_por TEXT,
    liberado_em TIMESTAMP,
    cancelado_por TEXT,
    cancelado_em TIMESTAMP,
    motivo_cancelamento TEXT,
    estornado_por TEXT,
    estornado_em TIMESTAMP,
    motivo_estorno TEXT,
    idempotency_key TEXT UNIQUE NOT NULL,
    versao INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS retrabalho_origens (
    id SERIAL PRIMARY KEY,
    retrabalho_id INTEGER NOT NULL,
    caixa_id_origem INTEGER NOT NULL,
    op_id_origem INTEGER,
    quantidade_reservada REAL NOT NULL,
    quantidade_consumida REAL NOT NULL DEFAULT 0,
    unidade TEXT NOT NULL,
    galinhas_por_pacote_origem INTEGER,
    condicao_no_momento TEXT,
    disponibilidade_no_momento TEXT,
    data_fabricacao_origem TEXT,
    data_validade_origem TEXT,
    snapshot_json TEXT,
    criado_em TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS retrabalho_saidas (
    id SERIAL PRIMARY KEY,
    retrabalho_id INTEGER NOT NULL,
    caixa_id_destino INTEGER NOT NULL,
    quantidade REAL NOT NULL,
    unidade TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS retrabalho_eventos (
    id SERIAL PRIMARY KEY,
    retrabalho_id INTEGER NOT NULL,
    acao TEXT NOT NULL,
    estado_anterior TEXT,
    estado_novo TEXT,
    usuario TEXT NOT NULL,
    perfil TEXT NOT NULL,
    justificativa TEXT,
    dados_json TEXT,
    criado_em TIMESTAMP NOT NULL,
    idempotency_key TEXT
);

CREATE INDEX IF NOT EXISTS idx_retrabalho_origens_rt ON retrabalho_origens(retrabalho_id);
CREATE INDEX IF NOT EXISTS idx_retrabalho_saidas_rt ON retrabalho_saidas(retrabalho_id);
CREATE INDEX IF NOT EXISTS idx_retrabalho_eventos_rt ON retrabalho_eventos(retrabalho_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_retrabalho_eventos_idem ON retrabalho_eventos(idempotency_key);

-- Novo valor aditivo de pa_caixas.disponibilidade: 'RETRABALHADO', marcando uma
-- posição de origem totalmente consumida por uma RT (mesmo padrão já usado para
-- 'EXPEDIDO'/'REPROCESSADO' em outras features). Não é um ALTER de schema —
-- apenas um novo literal já tratado pelo código (consolidado_estoque.py e
-- estoque_service.py já o excluem das listagens de saldo).

COMMIT;
