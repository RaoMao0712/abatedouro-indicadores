-- QUAL-SGI-01: migration aditiva PostgreSQL.
-- A aplicacao executa os mesmos CREATE IF NOT EXISTS no startup.
CREATE TABLE IF NOT EXISTS cadastros_locais (
  id SERIAL PRIMARY KEY, tipo TEXT NOT NULL, nome TEXT NOT NULL, setor TEXT NOT NULL,
  classificacao_iluminacao TEXT, status TEXT DEFAULT 'Ativo',
  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(tipo, nome, setor)
);
CREATE TABLE IF NOT EXISTS sgi_verificacoes (
  id SERIAL PRIMARY KEY, formulario_tipo TEXT NOT NULL, formulario_codigo TEXT NOT NULL,
  formulario_nome TEXT NOT NULL, data TEXT NOT NULL, setor TEXT NOT NULL,
  vinculo_tipo TEXT NOT NULL, local_id INTEGER, equipamento_id INTEGER,
  responsavel TEXT NOT NULL, status TEXT DEFAULT 'Pendente', observacoes TEXT,
  criado_por INTEGER NOT NULL, criado_por_nome TEXT NOT NULL,
  criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP, concluido_por INTEGER,
  concluido_por_nome TEXT, concluido_em TIMESTAMP,
  atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP, justificativa_alteracao TEXT
);
CREATE TABLE IF NOT EXISTS sgi_verificacao_itens (
  id SERIAL PRIMARY KEY, verificacao_id INTEGER NOT NULL, item_codigo TEXT NOT NULL,
  item_descricao TEXT NOT NULL, valor_texto TEXT, valor_numerico REAL, unidade TEXT,
  parametro_numerico REAL, resultado TEXT, observacoes TEXT, acao_adotada TEXT,
  reposicao_simples TEXT DEFAULT 'Nao', UNIQUE(verificacao_id, item_codigo)
);
CREATE TABLE IF NOT EXISTS sgi_nao_conformidades (
  id SERIAL PRIMARY KEY, verificacao_id INTEGER NOT NULL, item_id INTEGER NOT NULL,
  descricao TEXT NOT NULL, criticidade TEXT NOT NULL, situacao TEXT NOT NULL,
  tratamento TEXT, ordem_id INTEGER, criado_por INTEGER NOT NULL,
  criado_por_nome TEXT NOT NULL, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  gerencia_decisao TEXT, gerencia_justificativa TEXT, gerencia_usuario_id INTEGER,
  gerencia_usuario_nome TEXT, gerencia_em TIMESTAMP, eficacia_resultado TEXT,
  eficacia_observacao TEXT, eficacia_usuario_id INTEGER, eficacia_usuario_nome TEXT,
  eficacia_em TIMESTAMP, encerrado_por INTEGER, encerrado_por_nome TEXT,
  encerrado_em TIMESTAMP, atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sgi_acoes_imediatas (
  id SERIAL PRIMARY KEY, nc_id INTEGER NOT NULL, item_ausente TEXT NOT NULL,
  pessoa_acionada TEXT NOT NULL, acionado_por INTEGER NOT NULL,
  acionado_por_nome TEXT NOT NULL, acionado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  status TEXT DEFAULT 'Aguardando reposicao', segunda_verificacao_resultado TEXT,
  segunda_verificacao_observacao TEXT, verificado_por INTEGER,
  verificado_por_nome TEXT, verificado_em TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sgi_eventos (
  id SERIAL PRIMARY KEY, entidade_tipo TEXT NOT NULL, entidade_id INTEGER NOT NULL,
  evento TEXT NOT NULL, descricao TEXT, justificativa TEXT, usuario_id INTEGER NOT NULL,
  usuario_nome TEXT NOT NULL, criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE manutencao_ordens ADD COLUMN IF NOT EXISTS sgi_nc_id INTEGER;
