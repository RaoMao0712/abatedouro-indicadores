-- Produto Acabado Não Conforme no encerramento da OP (SQLite, aditiva e idempotente).
CREATE TABLE IF NOT EXISTS pa_nao_conformes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, numero TEXT UNIQUE NOT NULL, op_id INTEGER NOT NULL,
    caixa_id INTEGER UNIQUE NOT NULL, lote TEXT NOT NULL, produto TEXT NOT NULL,
    apresentacao TEXT NOT NULL, quantidade REAL NOT NULL, peso REAL, unidade TEXT NOT NULL,
    motivo TEXT NOT NULL, descricao TEXT, status TEXT NOT NULL DEFAULT 'BLOQUEADO',
    local_estoque_id INTEGER NOT NULL, registrado_por TEXT NOT NULL,
    perfil_registro TEXT NOT NULL, registrado_em TEXT NOT NULL, decisao TEXT,
    justificativa_destinacao TEXT, observacoes TEXT, decidido_por TEXT,
    perfil_decisao TEXT, decidido_em TEXT, criado_em TEXT NOT NULL, atualizado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pa_nao_conforme_eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, pa_nao_conforme_id INTEGER NOT NULL,
    acao TEXT NOT NULL, status_anterior TEXT, status_novo TEXT, usuario TEXT NOT NULL,
    perfil TEXT NOT NULL, justificativa TEXT, detalhes TEXT, origem TEXT NOT NULL,
    criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pa_nc_op ON pa_nao_conformes(op_id);
CREATE INDEX IF NOT EXISTS idx_pa_nc_status ON pa_nao_conformes(status);
CREATE INDEX IF NOT EXISTS idx_pa_nc_eventos ON pa_nao_conforme_eventos(pa_nao_conforme_id);
INSERT INTO locais_estoque (nome, tipo, ativo)
SELECT 'Abatedouro — Área de Produto Não Conforme', 'segregacao', 'Sim'
WHERE NOT EXISTS (SELECT 1 FROM locais_estoque WHERE nome='Abatedouro — Área de Produto Não Conforme');
