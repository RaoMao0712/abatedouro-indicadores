PRAGMA foreign_keys = OFF;

BEGIN;

DROP TRIGGER trg_bom_item_insert;
DROP TRIGGER trg_bom_item_delete;
DROP TRIGGER trg_bom_item_update;
CREATE TABLE bom_nova (
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
INSERT INTO bom_nova (id, produto_id, numero_versao, descricao, status, data_inicio_vigencia, data_fim_vigencia, observacoes, rendimento_entrada, rendimento_saida, rendimento_unidade_entrada, rendimento_unidade_saida, criado_em, atualizado_em, criado_por, atualizado_por, ativa)
SELECT id, produto_id, numero_versao, descricao, CASE WHEN status = 'ATIVA' THEN 'PUBLICADA' ELSE status END, data_inicio_vigencia, data_fim_vigencia, observacoes, rendimento_entrada, rendimento_saida, rendimento_unidade_entrada, rendimento_unidade_saida, criado_em, atualizado_em, criado_por, atualizado_por, status IN ('PUBLICADA', 'ATIVA') FROM bom;
DROP TABLE bom;
ALTER TABLE bom_nova RENAME TO bom;
CREATE INDEX ix_bom_vigencia ON bom (produto_id, ativa, data_inicio_vigencia);

COMMIT;
