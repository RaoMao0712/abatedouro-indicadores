BEGIN;
CREATE TABLE IF NOT EXISTS relatorios_nc_verificacao (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 numero TEXT UNIQUE NOT NULL,
 emitido_em TEXT NOT NULL,
 usuario TEXT NOT NULL,
 perfil TEXT NOT NULL,
 filtros_json TEXT NOT NULL,
 selecao_json TEXT NOT NULL,
 snapshot_json TEXT NOT NULL,
 totais_json TEXT NOT NULL,
 integridade_hash TEXT NOT NULL,
 resultado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relatorios_nc_verificacao_eventos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 relatorio_id INTEGER NOT NULL REFERENCES relatorios_nc_verificacao(id),
 acao TEXT NOT NULL,
 usuario TEXT NOT NULL,
 perfil TEXT NOT NULL,
 detalhes_json TEXT NOT NULL,
 criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_relatorios_nc_emissao
 ON relatorios_nc_verificacao(emitido_em);
CREATE INDEX IF NOT EXISTS idx_relatorios_nc_eventos
 ON relatorios_nc_verificacao_eventos(relatorio_id);
COMMIT;
