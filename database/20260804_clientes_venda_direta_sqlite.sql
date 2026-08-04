BEGIN;

CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    razao_social TEXT NOT NULL, nome_fantasia TEXT, tipo_pessoa TEXT NOT NULL,
    documento TEXT, telefone TEXT, endereco TEXT, complemento TEXT, bairro TEXT,
    cidade TEXT, uf TEXT, cep TEXT, observacoes TEXT, status TEXT NOT NULL DEFAULT 'Ativo',
    criado_por TEXT NOT NULL, atualizado_por TEXT NOT NULL,
    criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_clientes_documento ON clientes(documento) WHERE documento IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_clientes_busca ON clientes(status,razao_social,cidade);
CREATE TABLE IF NOT EXISTS cliente_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, cliente_id INTEGER NOT NULL,
    acao TEXT NOT NULL, dados_anteriores TEXT, dados_novos TEXT,
    usuario TEXT NOT NULL, perfil TEXT NOT NULL, criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cliente_eventos ON cliente_eventos(cliente_id,criado_em);

-- As colunas de expedicoes são adicionadas de forma idempotente pelo migrador runtime,
-- pois versões SQLite anteriores não suportam ADD COLUMN IF NOT EXISTS.

COMMIT;
