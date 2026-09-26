BEGIN;

CREATE TABLE IF NOT EXISTS sku_prontidao_parametros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    minimo_ops_reconciliadas INTEGER NOT NULL DEFAULT 10 CHECK (minimo_ops_reconciliadas > 0),
    janela_minima_dias INTEGER NOT NULL DEFAULT 30 CHECK (janela_minima_dias >= 0),
    sequencia_minima_paridade INTEGER NOT NULL DEFAULT 5 CHECK (sequencia_minima_paridade > 0),
    max_divergencias_media INTEGER NOT NULL DEFAULT 0 CHECK (max_divergencias_media >= 0),
    max_divergencias_baixa INTEGER NOT NULL DEFAULT 0 CHECK (max_divergencias_baixa >= 0),
    cobertura_critica_minima REAL NOT NULL DEFAULT 100 CHECK (cobertura_critica_minima >= 0 AND cobertura_critica_minima <= 100),
    dimensoes_criticas_json TEXT NOT NULL,
    versao INTEGER NOT NULL DEFAULT 1 CHECK (versao > 0),
    configuravel INTEGER NOT NULL DEFAULT 1 CHECK (configuravel IN (0,1)),
    usuario_id INTEGER,
    usuario_nome TEXT,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sku_prontidao_avaliacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL,
    parametro_id INTEGER NOT NULL REFERENCES sku_prontidao_parametros(id),
    estado TEXT NOT NULL CHECK (estado IN ('NAO_AVALIAVEL','EM_OBSERVACAO','BLOQUEADO_POR_DIVERGENCIA','APTO_PARA_AVALIACAO')),
    autoridade_operacional TEXT NOT NULL DEFAULT 'LEGADO',
    parametros_json TEXT NOT NULL,
    metricas_json TEXT NOT NULL,
    motivos_json TEXT NOT NULL DEFAULT '[]',
    fonte_reconciliacao_id INTEGER,
    fonte_execucao_id INTEGER,
    hash_avaliacao TEXT NOT NULL,
    usuario_id INTEGER,
    usuario_nome TEXT,
    avaliado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(sku, hash_avaliacao)
);

CREATE INDEX IF NOT EXISTS ix_sku_prontidao_avaliacoes_sku
    ON sku_prontidao_avaliacoes(sku, avaliado_em DESC);
CREATE INDEX IF NOT EXISTS ix_sku_prontidao_avaliacoes_estado
    ON sku_prontidao_avaliacoes(estado, avaliado_em DESC);

COMMIT;
