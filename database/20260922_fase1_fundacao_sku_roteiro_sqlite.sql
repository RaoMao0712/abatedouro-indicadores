BEGIN;
CREATE TABLE IF NOT EXISTS sku_versoes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, sku_id INTEGER NOT NULL REFERENCES skus(id), versao INTEGER NOT NULL,
 nome TEXT NOT NULL, unidade_apresentacao TEXT NOT NULL, categoria_tipo TEXT NOT NULL,
 status TEXT NOT NULL, vigencia_inicio TEXT NOT NULL, vigencia_fim TEXT, usuario_id INTEGER,
 usuario_nome TEXT NOT NULL, criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(sku_id,versao));
CREATE UNIQUE INDEX IF NOT EXISTS ux_sku_versao_ativa ON sku_versoes(sku_id) WHERE status='ATIVA';
CREATE TABLE IF NOT EXISTS etapas_catalogo (
 id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT NOT NULL UNIQUE, nome TEXT NOT NULL, natureza TEXT NOT NULL,
 ativo INTEGER NOT NULL DEFAULT 1, parametros_json TEXT NOT NULL DEFAULT '{}', usuario_nome TEXT NOT NULL,
 criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS roteiro_versoes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, sku_versao_id INTEGER NOT NULL REFERENCES sku_versoes(id), versao INTEGER NOT NULL,
 status TEXT NOT NULL, vigencia_inicio TEXT NOT NULL, vigencia_fim TEXT, aprovado_por TEXT, aprovado_em TEXT,
 observacoes TEXT, parametros_json TEXT NOT NULL DEFAULT '{}', usuario_nome TEXT NOT NULL,
 criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, atualizado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(sku_versao_id,versao));
CREATE UNIQUE INDEX IF NOT EXISTS ux_roteiro_versao_ativo ON roteiro_versoes(sku_versao_id) WHERE status='ATIVO';
CREATE TABLE IF NOT EXISTS roteiro_etapas (
 id INTEGER PRIMARY KEY AUTOINCREMENT, roteiro_versao_id INTEGER NOT NULL REFERENCES roteiro_versoes(id) ON DELETE CASCADE,
 etapa_catalogo_id INTEGER REFERENCES etapas_catalogo(id), ordem INTEGER NOT NULL, nome TEXT NOT NULL,
 obrigatoria INTEGER NOT NULL DEFAULT 1, unidade_entrada TEXT, unidade_saida TEXT,
 gera_intermediario INTEGER NOT NULL DEFAULT 0, controla_qualidade INTEGER NOT NULL DEFAULT 0,
 parametros_json TEXT NOT NULL DEFAULT '{}', UNIQUE(roteiro_versao_id,ordem));
CREATE TABLE IF NOT EXISTS roteiro_etapa_insumos (
 id INTEGER PRIMARY KEY AUTOINCREMENT, roteiro_etapa_id INTEGER NOT NULL REFERENCES roteiro_etapas(id) ON DELETE CASCADE,
 insumo_id INTEGER NOT NULL REFERENCES almoxarifado_insumos(id), unidade TEXT NOT NULL,
 quantidade_fator REAL NOT NULL, tipo_calculo TEXT NOT NULL, tolerancia_perda REAL,
 obrigatorio INTEGER NOT NULL DEFAULT 1, origem_baixa TEXT NOT NULL, parametros_json TEXT NOT NULL DEFAULT '{}',
 UNIQUE(roteiro_etapa_id,insumo_id,tipo_calculo));
CREATE TABLE IF NOT EXISTS op_config_snapshots (
 id INTEGER PRIMARY KEY AUTOINCREMENT, op_id INTEGER NOT NULL UNIQUE REFERENCES ordens_producao(id), sku_id INTEGER REFERENCES skus(id),
 sku_versao_id INTEGER REFERENCES sku_versoes(id), roteiro_versao_id INTEGER REFERENCES roteiro_versoes(id),
 schema_version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, usuario_id INTEGER, usuario_nome TEXT NOT NULL,
 criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
COMMIT;
