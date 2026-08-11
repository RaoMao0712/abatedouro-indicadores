BEGIN;
CREATE TABLE IF NOT EXISTS linha_abate_velocidades_ideais (
    id SERIAL PRIMARY KEY, linha TEXT NOT NULL DEFAULT 'LINHA_ABATE',
    configuracao TEXT NOT NULL, sku TEXT, velocidade_aves_hora TEXT NOT NULL,
    vigencia_inicio TEXT NOT NULL, vigencia_fim TEXT, status TEXT NOT NULL DEFAULT 'PROPOSTA',
    justificativa_tecnica TEXT NOT NULL, proposto_por TEXT NOT NULL,
    proposto_por_id INTEGER, proposto_em TEXT NOT NULL, aprovado_por TEXT,
    aprovado_por_id INTEGER, aprovado_em TEXT, rejeitado_por TEXT,
    rejeitado_por_id INTEGER, rejeitado_em TEXT, encerrado_por TEXT,
    encerrado_por_id INTEGER, encerrado_em TEXT, justificativa_decisao TEXT,
    ativo_logico INTEGER NOT NULL DEFAULT 1, versao INTEGER NOT NULL DEFAULT 1,
    CHECK (status IN ('PROPOSTA','APROVADA','ATIVA','ENCERRADA','REJEITADA'))
);
CREATE TABLE IF NOT EXISTS linha_performance_snapshots_op (
    id SERIAL PRIMARY KEY, op_id INTEGER NOT NULL, velocidade_id INTEGER NOT NULL,
    linha TEXT NOT NULL, configuracao TEXT NOT NULL, sku TEXT,
    velocidade_aves_hora TEXT NOT NULL, vigencia_inicio TEXT NOT NULL,
    vigencia_fim TEXT, resolvido_em TEXT NOT NULL, resolvido_por TEXT NOT NULL,
    resolvido_por_id INTEGER, versao INTEGER NOT NULL DEFAULT 1,
    atual INTEGER NOT NULL DEFAULT 1, justificativa_correcao TEXT
);
CREATE TABLE IF NOT EXISTS linha_performance_contagens (
    id SERIAL PRIMARY KEY, op_id INTEGER NOT NULL, aves_recebidas TEXT NOT NULL,
    mortes_antes_pendura TEXT NOT NULL, aves_processadas TEXT NOT NULL,
    origem_calculo TEXT NOT NULL, confirmado_por TEXT NOT NULL,
    confirmado_por_id INTEGER, confirmado_em TEXT NOT NULL, observacao TEXT,
    versao INTEGER NOT NULL DEFAULT 1, atual INTEGER NOT NULL DEFAULT 1,
    justificativa_correcao TEXT
);
CREATE TABLE IF NOT EXISTS linha_performance_reprocessos (
    id SERIAL PRIMARY KEY, op_id INTEGER NOT NULL, quantidade_aves TEXT NOT NULL,
    atravessou_linha INTEGER NOT NULL, data_hora TEXT NOT NULL, motivo TEXT NOT NULL,
    usuario TEXT NOT NULL, usuario_id INTEGER, execucao_original TEXT NOT NULL,
    chave_idempotencia TEXT, ativo_logico INTEGER NOT NULL DEFAULT 1,
    CHECK (atravessou_linha IN (0,1))
);
CREATE TABLE IF NOT EXISTS linha_performance_auditoria (
    id SERIAL PRIMARY KEY, op_id INTEGER, entidade TEXT NOT NULL,
    entidade_id INTEGER, acao TEXT NOT NULL, valor_anterior TEXT, valor_novo TEXT,
    justificativa TEXT, usuario TEXT NOT NULL, usuario_id INTEGER,
    perfil TEXT NOT NULL, criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_velocidade_resolucao ON linha_abate_velocidades_ideais(linha,sku,configuracao,status,vigencia_inicio,vigencia_fim);
CREATE INDEX IF NOT EXISTS idx_performance_snapshot_op ON linha_performance_snapshots_op(op_id,atual);
CREATE INDEX IF NOT EXISTS idx_performance_contagem_op ON linha_performance_contagens(op_id,atual);
CREATE INDEX IF NOT EXISTS idx_performance_reprocesso_op ON linha_performance_reprocessos(op_id,atravessou_linha,ativo_logico);
CREATE INDEX IF NOT EXISTS idx_performance_auditoria ON linha_performance_auditoria(op_id,criado_em);
CREATE UNIQUE INDEX IF NOT EXISTS ux_performance_reprocesso_chave ON linha_performance_reprocessos(op_id,chave_idempotencia) WHERE chave_idempotencia IS NOT NULL;
COMMIT;
