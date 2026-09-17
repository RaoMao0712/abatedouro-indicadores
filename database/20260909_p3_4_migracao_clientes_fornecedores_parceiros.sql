-- P3.4 PostgreSQL: estrutura aditiva. O backfill auditável é executado pelo serviço Python.
BEGIN;
ALTER TABLE clientes ADD COLUMN IF NOT EXISTS parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS documento TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Ativo';
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS tipo_pessoa TEXT DEFAULT 'PJ';
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS telefone TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS endereco TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS complemento TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS bairro TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS cidade TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS uf TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS cep TEXT;
ALTER TABLE fornecedores ADD COLUMN IF NOT EXISTS observacoes TEXT;
ALTER TABLE pedidos_venda ADD COLUMN IF NOT EXISTS cliente_parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE pedidos_venda ALTER COLUMN cliente_id DROP NOT NULL;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS cliente_parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE ordens_producao ADD COLUMN IF NOT EXISTS fornecedor_parceiro_id INTEGER REFERENCES parceiros(id);
CREATE TABLE IF NOT EXISTS parceiro_migracoes_legado (
 id SERIAL PRIMARY KEY,tipo_legado TEXT NOT NULL,id_legado INTEGER NOT NULL,
 parceiro_id INTEGER REFERENCES parceiros(id),parceiro_criado INTEGER NOT NULL DEFAULT 0,
 papel_adicionado INTEGER NOT NULL DEFAULT 0,resultado TEXT NOT NULL,detalhes TEXT,
 executor TEXT NOT NULL,executado_em TIMESTAMP NOT NULL,UNIQUE(tipo_legado,id_legado)
);
CREATE INDEX IF NOT EXISTS idx_clientes_parceiro ON clientes(parceiro_id);
CREATE INDEX IF NOT EXISTS idx_fornecedores_parceiro ON fornecedores(parceiro_id);
CREATE INDEX IF NOT EXISTS idx_pedidos_venda_cliente_parceiro ON pedidos_venda(cliente_parceiro_id,data_pedido);
CREATE INDEX IF NOT EXISTS idx_expedicoes_cliente_parceiro ON expedicoes(cliente_parceiro_id,data);
CREATE INDEX IF NOT EXISTS idx_ops_fornecedor_parceiro ON ordens_producao(fornecedor_parceiro_id,data);
COMMIT;
