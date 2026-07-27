-- Engenharia de Produtos — PostgreSQL
-- Migração aditiva e retrocompatível. A aplicação repete estas operações de
-- forma idempotente no startup para instalações que usam deploy automático.

ALTER TABLE skus ADD COLUMN IF NOT EXISTS codigo TEXT;
ALTER TABLE skus ADD COLUMN IF NOT EXISTS tipo_produto TEXT DEFAULT 'PRODUTO_ACABADO';
ALTER TABLE skus ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMP;
ALTER TABLE skus ADD COLUMN IF NOT EXISTS excluido_em TIMESTAMP;

UPDATE skus SET codigo = 'LEG-' || id WHERE codigo IS NULL OR BTRIM(codigo) = '';
UPDATE skus SET tipo_produto = 'PRODUTO_ACABADO'
WHERE tipo_produto IS NULL OR BTRIM(tipo_produto) = '';
UPDATE skus SET atualizado_em = COALESCE(atualizado_em, criado_em, CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS ux_skus_codigo_ci ON skus (LOWER(codigo));

ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS unidade TEXT;
ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS fator_proporcao REAL;
ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS percentual_perda REAL;
ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Ativo';
ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS data_vigencia TEXT;
ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS usuario_responsavel TEXT;
ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS atualizado_em TIMESTAMP;
ALTER TABLE receitas_sku ADD COLUMN IF NOT EXISTS removido_em TIMESTAMP;

UPDATE receitas_sku r SET
    tipo_consumo = CASE
        WHEN tipo_consumo IN ('FIXO_UNIDADE','POR_KG','POR_CAIXA','PROPORCIONAL',
                              'PERCENTUAL','PERDA_ESPERADA','OPCIONAL') THEN tipo_consumo
        WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%proporcional%' THEN 'PROPORCIONAL'
        WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%perda%' THEN 'PERDA_ESPERADA'
        WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%outro%' THEN 'OPCIONAL'
        ELSE 'FIXO_UNIDADE'
    END,
    unidade = COALESCE(NULLIF(r.unidade, ''), i.unidade, 'Un'),
    status = COALESCE(NULLIF(r.status, ''), 'Ativo'),
    data_vigencia = COALESCE(NULLIF(r.data_vigencia, ''), SUBSTRING(r.criado_em::TEXT, 1, 10)),
    atualizado_em = COALESCE(r.atualizado_em, r.criado_em, CURRENT_TIMESTAMP)
FROM almoxarifado_insumos i
WHERE i.id = r.insumo_id;

CREATE TABLE IF NOT EXISTS processos_produtivos (
    id SERIAL PRIMARY KEY,
    codigo TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    descricao TEXT,
    setor TEXT,
    status TEXT NOT NULL DEFAULT 'Ativo',
    observacoes TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS engenharia_produtos_historico (
    id SERIAL PRIMARY KEY,
    entidade TEXT NOT NULL,
    entidade_id INTEGER NOT NULL,
    acao TEXT NOT NULL,
    usuario_id INTEGER,
    usuario_nome TEXT,
    valores_anteriores TEXT,
    valores_novos TEXT,
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
