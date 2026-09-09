-- P3.4 SQLite 3.35+: estrutura aditiva para testes e instalações locais.
BEGIN;
ALTER TABLE clientes ADD COLUMN parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE fornecedores ADD COLUMN parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE fornecedores ADD COLUMN documento TEXT;
ALTER TABLE fornecedores ADD COLUMN status TEXT DEFAULT 'Ativo';
ALTER TABLE fornecedores ADD COLUMN tipo_pessoa TEXT DEFAULT 'PJ';
ALTER TABLE fornecedores ADD COLUMN telefone TEXT;
ALTER TABLE fornecedores ADD COLUMN email TEXT;
ALTER TABLE fornecedores ADD COLUMN endereco TEXT;
ALTER TABLE fornecedores ADD COLUMN complemento TEXT;
ALTER TABLE fornecedores ADD COLUMN bairro TEXT;
ALTER TABLE fornecedores ADD COLUMN cidade TEXT;
ALTER TABLE fornecedores ADD COLUMN uf TEXT;
ALTER TABLE fornecedores ADD COLUMN cep TEXT;
ALTER TABLE fornecedores ADD COLUMN observacoes TEXT;
ALTER TABLE pedidos_venda ADD COLUMN cliente_parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE expedicoes ADD COLUMN cliente_parceiro_id INTEGER REFERENCES parceiros(id);
ALTER TABLE ordens_producao ADD COLUMN fornecedor_parceiro_id INTEGER REFERENCES parceiros(id);
CREATE TABLE parceiro_migracoes_legado (
 id INTEGER PRIMARY KEY AUTOINCREMENT,tipo_legado TEXT NOT NULL,id_legado INTEGER NOT NULL,
 parceiro_id INTEGER REFERENCES parceiros(id),parceiro_criado INTEGER NOT NULL DEFAULT 0,
 papel_adicionado INTEGER NOT NULL DEFAULT 0,resultado TEXT NOT NULL,detalhes TEXT,
 executor TEXT NOT NULL,executado_em TEXT NOT NULL,UNIQUE(tipo_legado,id_legado)
);
CREATE INDEX idx_clientes_parceiro ON clientes(parceiro_id);
CREATE INDEX idx_fornecedores_parceiro ON fornecedores(parceiro_id);
CREATE INDEX idx_pedidos_venda_cliente_parceiro ON pedidos_venda(cliente_parceiro_id,data_pedido);
CREATE INDEX idx_expedicoes_cliente_parceiro ON expedicoes(cliente_parceiro_id,data);
CREATE INDEX idx_ops_fornecedor_parceiro ON ordens_producao(fornecedor_parceiro_id,data);
COMMIT;
