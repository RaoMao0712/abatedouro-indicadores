BEGIN;

CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    razao_social TEXT NOT NULL,
    nome_fantasia TEXT,
    tipo_pessoa TEXT NOT NULL CHECK (tipo_pessoa IN ('PF','PJ')),
    documento TEXT,
    telefone TEXT,
    endereco TEXT,
    complemento TEXT,
    bairro TEXT,
    cidade TEXT,
    uf TEXT,
    cep TEXT,
    observacoes TEXT,
    status TEXT NOT NULL DEFAULT 'Ativo',
    criado_por TEXT NOT NULL,
    atualizado_por TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_clientes_documento ON clientes(documento) WHERE documento IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clientes_busca ON clientes(status,razao_social,cidade);

CREATE TABLE IF NOT EXISTS cliente_eventos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL,
    acao TEXT NOT NULL,
    dados_anteriores TEXT,
    dados_novos TEXT,
    usuario TEXT NOT NULL,
    perfil TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cliente_eventos ON cliente_eventos(cliente_id,criado_em);

ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS tipo_saida TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS cliente_id INTEGER;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS cliente_snapshot TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS veiculo TEXT;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS motorista TEXT;
UPDATE expedicoes SET tipo_saida='TRANSFERENCIA_LSM'
WHERE tipo_saida IS NULL AND tipo_movimentacao='TRANSFERENCIA';
CREATE INDEX IF NOT EXISTS idx_expedicoes_tipo_saida ON expedicoes(tipo_saida,status,data);
CREATE INDEX IF NOT EXISTS idx_expedicoes_cliente ON expedicoes(cliente_id,data);

COMMIT;
