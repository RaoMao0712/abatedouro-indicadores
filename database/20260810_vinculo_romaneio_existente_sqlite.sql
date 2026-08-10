BEGIN;
CREATE TABLE IF NOT EXISTS pedido_venda_vinculos (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 pedido_id INTEGER NOT NULL REFERENCES pedidos_venda(id),
 expedicao_id INTEGER NOT NULL UNIQUE REFERENCES expedicoes(id),
 origem TEXT NOT NULL,
 idempotency_key TEXT NOT NULL UNIQUE,
 usuario TEXT NOT NULL,
 perfil TEXT NOT NULL,
 criado_em TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pedido_venda_vinculo_itens (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 vinculo_id INTEGER NOT NULL REFERENCES pedido_venda_vinculos(id),
 pedido_item_id INTEGER NOT NULL REFERENCES pedido_venda_itens(id),
 expedicao_item_id INTEGER NOT NULL UNIQUE REFERENCES expedicao_itens(id),
 sku TEXT NOT NULL,
 apresentacao_snapshot TEXT,
 quantidade_operacional_mil INTEGER NOT NULL,
 unidade_operacional TEXT NOT NULL,
 aves_por_unidade_operacional INTEGER,
 quantidade_comercial_mil INTEGER NOT NULL,
 unidade_comercial TEXT NOT NULL,
 peso_mil_kg INTEGER,
 quantidade_entregue_anterior_mil INTEGER NOT NULL,
 saldo_anterior_mil INTEGER NOT NULL,
 saldo_posterior_mil INTEGER NOT NULL,
 criado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pedido_vinculos_pedido ON pedido_venda_vinculos(pedido_id,criado_em);
CREATE INDEX IF NOT EXISTS idx_pedido_vinculo_itens_pedido ON pedido_venda_vinculo_itens(pedido_item_id);
COMMIT;
