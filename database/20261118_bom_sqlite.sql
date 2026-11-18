BEGIN;

ALTER TABLE skus ADD COLUMN fabricavel BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE skus ADD COLUMN compravel BOOLEAN NOT NULL DEFAULT TRUE;

CREATE TABLE bom (
    id INTEGER PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES skus(id),
    numero_versao INTEGER NOT NULL CHECK (numero_versao > 0),
    descricao TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN ('RASCUNHO', 'PUBLICADA', 'INATIVA')),
    data_inicio_vigencia DATE NOT NULL,
    data_fim_vigencia DATE,
    ativa BOOLEAN NOT NULL DEFAULT FALSE,
    observacoes TEXT NOT NULL DEFAULT '',
    rendimento_entrada TEXT,
    rendimento_saida TEXT,
    rendimento_unidade_entrada TEXT,
    rendimento_unidade_saida TEXT,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_por INTEGER,
    atualizado_por INTEGER,
    UNIQUE (produto_id, numero_versao),
    CHECK (data_fim_vigencia IS NULL OR data_fim_vigencia >= data_inicio_vigencia),
    CHECK (ativa = (status = 'PUBLICADA')),
    CHECK (
        (rendimento_entrada IS NULL AND rendimento_saida IS NULL
            AND rendimento_unidade_entrada IS NULL AND rendimento_unidade_saida IS NULL)
        OR (rendimento_entrada IS NOT NULL AND CAST(rendimento_entrada AS NUMERIC) > 0
            AND rendimento_saida IS NOT NULL AND CAST(rendimento_saida AS NUMERIC) > 0
            AND rendimento_unidade_entrada IS NOT NULL AND rendimento_unidade_saida IS NOT NULL)
    )
);

CREATE TABLE bom_item (
    id INTEGER PRIMARY KEY,
    bom_id INTEGER NOT NULL REFERENCES bom(id),
    componente_produto_id INTEGER REFERENCES skus(id),
    componente_insumo_id INTEGER REFERENCES almoxarifado_insumos(id),
    sequencia INTEGER NOT NULL CHECK (sequencia > 0),
    classificacao TEXT NOT NULL CHECK (LENGTH(TRIM(classificacao)) > 0),
    quantidade_base TEXT NOT NULL CHECK (CAST(quantidade_base AS NUMERIC) > 0),
    unidade TEXT NOT NULL,
    regra_calculo TEXT NOT NULL CHECK (regra_calculo IN (
        'POR_UNIDADE_PRODUZIDA', 'POR_QUANTIDADE_PRODUZIDA', 'PERCENTUAL',
        'FIXO_POR_ORDEM', 'RAZAO_AGRUPAMENTO'
    )),
    fator TEXT NOT NULL DEFAULT 1 CHECK (CAST(fator AS NUMERIC) > 0),
    perda_prevista_percentual TEXT NOT NULL DEFAULT 0 CHECK (CAST(perda_prevista_percentual AS NUMERIC) >= 0),
    etapa_id INTEGER REFERENCES etapas_catalogo(id),
    observacoes TEXT NOT NULL DEFAULT '',
    ativo BOOLEAN NOT NULL DEFAULT TRUE,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((componente_produto_id IS NULL) <> (componente_insumo_id IS NULL)),
    UNIQUE (bom_id, sequencia)
);

CREATE INDEX ix_bom_vigencia ON bom (produto_id, ativa, data_inicio_vigencia);
CREATE INDEX ix_bom_item_produto ON bom_item (componente_produto_id);
CREATE INDEX ix_bom_item_insumo ON bom_item (componente_insumo_id);

COMMIT;
