PRAGMA foreign_keys = OFF;

BEGIN;

CREATE TABLE bom_nova (
    id INTEGER PRIMARY KEY,
    produto_id INTEGER NOT NULL REFERENCES skus(id),
    numero_versao INTEGER NOT NULL CHECK (numero_versao > 0),
    descricao TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'RASCUNHO' CHECK (status IN ('RASCUNHO', 'PUBLICADA', 'ATIVA', 'INATIVA')),
    data_inicio_vigencia DATE NOT NULL,
    data_fim_vigencia DATE,
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
    CHECK (
        (rendimento_entrada IS NULL AND rendimento_saida IS NULL
            AND rendimento_unidade_entrada IS NULL AND rendimento_unidade_saida IS NULL)
        OR (rendimento_entrada IS NOT NULL AND CAST(rendimento_entrada AS NUMERIC) > 0
            AND rendimento_saida IS NOT NULL AND CAST(rendimento_saida AS NUMERIC) > 0
            AND rendimento_unidade_entrada IS NOT NULL AND rendimento_unidade_saida IS NOT NULL)
    )
);
INSERT INTO bom_nova (id, produto_id, numero_versao, descricao, status, data_inicio_vigencia, data_fim_vigencia, observacoes, rendimento_entrada, rendimento_saida, rendimento_unidade_entrada, rendimento_unidade_saida, criado_em, atualizado_em, criado_por, atualizado_por) SELECT id, produto_id, numero_versao, descricao, status, data_inicio_vigencia, data_fim_vigencia, observacoes, rendimento_entrada, rendimento_saida, rendimento_unidade_entrada, rendimento_unidade_saida, criado_em, atualizado_em, criado_por, atualizado_por FROM bom;
DROP TABLE bom;
ALTER TABLE bom_nova RENAME TO bom;

CREATE INDEX ix_bom_vigencia ON bom (produto_id, status, data_inicio_vigencia);
CREATE UNIQUE INDEX uq_bom_ativa_produto ON bom (produto_id) WHERE status = 'ATIVA';

CREATE TRIGGER trg_bom_incluir BEFORE INSERT ON bom
WHEN NEW.status <> 'RASCUNHO'
BEGIN
    SELECT RAISE(ABORT, 'A BOM deve iniciar em rascunho');
END;

CREATE TRIGGER trg_bom_excluir BEFORE DELETE ON bom
WHEN OLD.status <> 'RASCUNHO'
BEGIN
    SELECT RAISE(ABORT, 'Versão de BOM imutável');
END;

CREATE TRIGGER trg_bom_alterar BEFORE UPDATE ON bom
WHEN NOT (
    (OLD.status = 'RASCUNHO' AND NEW.status IN ('RASCUNHO', 'PUBLICADA'))
    OR (
        ((OLD.status = 'PUBLICADA' AND NEW.status IN ('ATIVA', 'INATIVA'))
         OR (OLD.status = 'ATIVA' AND NEW.status = 'INATIVA'))
        AND NEW.id IS OLD.id
        AND NEW.produto_id IS OLD.produto_id
        AND NEW.numero_versao IS OLD.numero_versao
        AND NEW.descricao IS OLD.descricao
        AND NEW.data_inicio_vigencia IS OLD.data_inicio_vigencia
        AND NEW.data_fim_vigencia IS OLD.data_fim_vigencia
        AND NEW.observacoes IS OLD.observacoes
        AND NEW.rendimento_entrada IS OLD.rendimento_entrada
        AND NEW.rendimento_saida IS OLD.rendimento_saida
        AND NEW.rendimento_unidade_entrada IS OLD.rendimento_unidade_entrada
        AND NEW.rendimento_unidade_saida IS OLD.rendimento_unidade_saida
        AND NEW.criado_em IS OLD.criado_em
        AND NEW.criado_por IS OLD.criado_por
    )
)
BEGIN
    SELECT RAISE(ABORT, 'Versão de BOM imutável ou transição inválida');
END;

CREATE TRIGGER trg_bom_item_insert BEFORE INSERT ON bom_item
WHEN NOT EXISTS (SELECT 1 FROM bom WHERE id = NEW.bom_id AND status = 'RASCUNHO')
BEGIN
    SELECT RAISE(ABORT, 'Itens de BOM publicada são imutáveis');
END;

CREATE TRIGGER trg_bom_item_delete BEFORE DELETE ON bom_item
WHEN NOT EXISTS (SELECT 1 FROM bom WHERE id = OLD.bom_id AND status = 'RASCUNHO')
BEGIN
    SELECT RAISE(ABORT, 'Itens de BOM publicada são imutáveis');
END;

CREATE TRIGGER trg_bom_item_update BEFORE UPDATE ON bom_item
WHEN NOT EXISTS (SELECT 1 FROM bom WHERE id = OLD.bom_id AND status = 'RASCUNHO') OR NOT EXISTS (SELECT 1 FROM bom WHERE id = NEW.bom_id AND status = 'RASCUNHO')
BEGIN
    SELECT RAISE(ABORT, 'Itens de BOM publicada são imutáveis');
END;

COMMIT;
