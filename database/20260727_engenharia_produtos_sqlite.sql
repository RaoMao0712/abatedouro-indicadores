-- Engenharia de Produtos — SQLite
-- Executar somente em bases legadas, uma vez. O startup da aplicação faz as
-- mesmas alterações coluna a coluna e tolera colunas já existentes.

ALTER TABLE skus ADD COLUMN codigo TEXT;
ALTER TABLE skus ADD COLUMN tipo_produto TEXT DEFAULT 'PRODUTO_ACABADO';
ALTER TABLE skus ADD COLUMN atualizado_em TEXT;
ALTER TABLE skus ADD COLUMN excluido_em TEXT;

ALTER TABLE receitas_sku ADD COLUMN unidade TEXT;
ALTER TABLE receitas_sku ADD COLUMN fator_proporcao REAL;
ALTER TABLE receitas_sku ADD COLUMN percentual_perda REAL;
ALTER TABLE receitas_sku ADD COLUMN status TEXT DEFAULT 'Ativo';
ALTER TABLE receitas_sku ADD COLUMN data_vigencia TEXT;
ALTER TABLE receitas_sku ADD COLUMN usuario_responsavel TEXT;
ALTER TABLE receitas_sku ADD COLUMN atualizado_em TEXT;
ALTER TABLE receitas_sku ADD COLUMN removido_em TEXT;

UPDATE skus SET codigo = 'LEG-' || id WHERE codigo IS NULL OR TRIM(codigo) = '';
UPDATE skus SET tipo_produto = 'PRODUTO_ACABADO'
WHERE tipo_produto IS NULL OR TRIM(tipo_produto) = '';
UPDATE skus SET atualizado_em = COALESCE(atualizado_em, criado_em, CURRENT_TIMESTAMP);
CREATE UNIQUE INDEX IF NOT EXISTS ux_skus_codigo_ci ON skus (LOWER(codigo));

UPDATE receitas_sku SET
    tipo_consumo = CASE
        WHEN tipo_consumo IN ('FIXO_UNIDADE','POR_KG','POR_CAIXA','PROPORCIONAL',
                              'PERCENTUAL','PERDA_ESPERADA','OPCIONAL') THEN tipo_consumo
        WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%proporcional%' THEN 'PROPORCIONAL'
        WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%perda%' THEN 'PERDA_ESPERADA'
        WHEN LOWER(COALESCE(tipo_consumo, '')) LIKE '%outro%' THEN 'OPCIONAL'
        ELSE 'FIXO_UNIDADE'
    END,
    unidade = COALESCE(
        NULLIF(unidade, ''),
        (SELECT unidade FROM almoxarifado_insumos i WHERE i.id = receitas_sku.insumo_id),
        'Un'
    ),
    status = COALESCE(NULLIF(status, ''), 'Ativo'),
    data_vigencia = COALESCE(NULLIF(data_vigencia, ''), SUBSTR(criado_em, 1, 10)),
    atualizado_em = COALESCE(atualizado_em, criado_em, CURRENT_TIMESTAMP);

CREATE TABLE IF NOT EXISTS processos_produtivos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo TEXT NOT NULL UNIQUE,
    nome TEXT NOT NULL,
    descricao TEXT,
    setor TEXT,
    status TEXT NOT NULL DEFAULT 'Ativo',
    observacoes TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS engenharia_produtos_historico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entidade TEXT NOT NULL,
    entidade_id INTEGER NOT NULL,
    acao TEXT NOT NULL,
    usuario_id INTEGER,
    usuario_nome TEXT,
    valores_anteriores TEXT,
    valores_novos TEXT,
    criado_em TEXT DEFAULT CURRENT_TIMESTAMP
);
