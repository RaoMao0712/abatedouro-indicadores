BEGIN;

CREATE TABLE IF NOT EXISTS parceiros (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    tipo_pessoa TEXT NOT NULL CHECK (tipo_pessoa IN ('PF','PJ')),
    razao_social TEXT NOT NULL,
    nome_fantasia TEXT,
    documento TEXT,
    telefone TEXT,
    email TEXT,
    endereco TEXT,
    complemento TEXT,
    bairro TEXT,
    cidade TEXT,
    uf TEXT,
    cep TEXT,
    observacoes TEXT,
    status TEXT NOT NULL DEFAULT 'Ativo' CHECK (status IN ('Ativo','Inativo')),
    criado_por TEXT NOT NULL,
    atualizado_por TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL,
    atualizado_em TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS parceiro_papeis (
    id SERIAL PRIMARY KEY,
    parceiro_id INTEGER NOT NULL REFERENCES parceiros(id),
    papel TEXT NOT NULL CHECK (papel IN ('CLIENTE','FORNECEDOR','PRESTADOR_SERVICOS','COLABORADOR_CLT')),
    ativo INTEGER NOT NULL DEFAULT 1,
    adicionado_por TEXT NOT NULL,
    adicionado_em TIMESTAMP NOT NULL,
    removido_por TEXT,
    removido_em TIMESTAMP,
    UNIQUE (parceiro_id, papel)
);

CREATE TABLE IF NOT EXISTS parceiro_eventos (
    id SERIAL PRIMARY KEY,
    parceiro_id INTEGER NOT NULL REFERENCES parceiros(id),
    acao TEXT NOT NULL,
    papel TEXT,
    estado_anterior TEXT,
    estado_posterior TEXT,
    usuario TEXT NOT NULL,
    perfil TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_parceiros_documento ON parceiros(documento) WHERE documento IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_parceiros_busca ON parceiros(status,tipo_pessoa,razao_social);
CREATE INDEX IF NOT EXISTS idx_parceiro_papeis_elegibilidade ON parceiro_papeis(papel,ativo,parceiro_id);
CREATE INDEX IF NOT EXISTS idx_parceiro_eventos_historico ON parceiro_eventos(parceiro_id,criado_em);

ALTER TABLE apontamentos_mao_obra ADD COLUMN IF NOT EXISTS parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE apontamentos_mao_obra ADD COLUMN IF NOT EXISTS parceiro_nome_snapshot TEXT;
ALTER TABLE apontamentos_mao_obra ADD COLUMN IF NOT EXISTS natureza_vinculo TEXT;
CREATE INDEX IF NOT EXISTS idx_apontamentos_mao_obra_parceiro ON apontamentos_mao_obra(parceiro_id,op_id);

COMMIT;
