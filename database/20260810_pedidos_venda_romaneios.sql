BEGIN;
CREATE TABLE IF NOT EXISTS pedidos_venda (
 id SERIAL PRIMARY KEY, numero TEXT UNIQUE NOT NULL, cliente_id INTEGER NOT NULL,
 cliente_snapshot TEXT NOT NULL, destino TEXT NOT NULL, data_pedido TEXT NOT NULL,
 previsao_entrega TEXT, responsavel TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'RASCUNHO',
 subtotal_centavos BIGINT NOT NULL DEFAULT 0, desconto_centavos BIGINT NOT NULL DEFAULT 0,
 valor_total_centavos BIGINT NOT NULL DEFAULT 0, forma_pagamento TEXT NOT NULL,
 condicao_pagamento TEXT NOT NULL, vencimento_inicial TEXT, prazo_dias INTEGER,
 numero_parcelas INTEGER, intervalo_dias INTEGER, entrada_centavos BIGINT,
 entrada_percentual_milesimos INTEGER, condicao_saldo TEXT, descricao_condicao TEXT,
 observacoes TEXT, motivo_cancelamento TEXT, criado_por TEXT NOT NULL,
 atualizado_por TEXT NOT NULL, criado_em TIMESTAMP NOT NULL, atualizado_em TIMESTAMP NOT NULL,
 confirmado_em TIMESTAMP, cancelado_em TIMESTAMP, versao INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS pedido_venda_itens (
 id SERIAL PRIMARY KEY, pedido_id INTEGER NOT NULL, produto_id INTEGER, sku TEXT NOT NULL,
 produto_snapshot TEXT NOT NULL, apresentacao_snapshot TEXT, quantidade_negociada_mil BIGINT NOT NULL,
 unidade_comercial TEXT NOT NULL, preco_unitario_centavos BIGINT NOT NULL,
 desconto_centavos BIGINT NOT NULL DEFAULT 0, valor_bruto_centavos BIGINT NOT NULL,
 valor_liquido_centavos BIGINT NOT NULL, quantidade_operacional_mil BIGINT,
 unidade_operacional TEXT, aves_por_unidade_operacional INTEGER,
 quantidade_comercial_mil BIGINT, base_preco TEXT, observacoes TEXT, criado_em TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS pedido_venda_romaneio_itens (
 id SERIAL PRIMARY KEY, pedido_id INTEGER NOT NULL, pedido_item_id INTEGER NOT NULL,
 expedicao_id INTEGER NOT NULL, quantidade_planejada_mil BIGINT NOT NULL,
 unidade TEXT NOT NULL, criado_por TEXT NOT NULL, criado_em TIMESTAMP NOT NULL,
 UNIQUE(pedido_item_id, expedicao_id)
);
CREATE TABLE IF NOT EXISTS pedido_venda_atendimentos (
 id SERIAL PRIMARY KEY, pedido_id INTEGER NOT NULL, pedido_item_id INTEGER NOT NULL,
 expedicao_id INTEGER NOT NULL, expedicao_item_id INTEGER NOT NULL UNIQUE,
 quantidade_atendida_mil BIGINT NOT NULL, unidade TEXT NOT NULL, peso_atendido_mil_kg BIGINT,
 status TEXT NOT NULL DEFAULT 'ENTREGUE', criado_por TEXT NOT NULL,
 criado_em TIMESTAMP NOT NULL, atualizado_em TIMESTAMP NOT NULL
);
CREATE TABLE IF NOT EXISTS pedido_venda_eventos (
 id SERIAL PRIMARY KEY, pedido_id INTEGER, acao TEXT NOT NULL, estado_anterior TEXT,
 estado_novo TEXT, dados_anteriores TEXT, dados_novos TEXT, usuario TEXT NOT NULL,
 perfil TEXT NOT NULL, justificativa TEXT, origem TEXT NOT NULL, criado_em TIMESTAMP NOT NULL,
 idempotency_key TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS pedido_venda_sequencias (data_documento TEXT PRIMARY KEY, ultimo INTEGER NOT NULL);
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS pedido_venda_id INTEGER;
ALTER TABLE expedicoes ADD COLUMN IF NOT EXISTS pedido_destino_entrega TEXT;
ALTER TABLE expedicao_itens ADD COLUMN IF NOT EXISTS pedido_item_id INTEGER;
CREATE INDEX IF NOT EXISTS idx_pedidos_venda_filtros ON pedidos_venda(status,data_pedido,cliente_id);
CREATE INDEX IF NOT EXISTS idx_pedido_itens_pedido ON pedido_venda_itens(pedido_id);
CREATE INDEX IF NOT EXISTS idx_pedido_planos_expedicao ON pedido_venda_romaneio_itens(expedicao_id);
CREATE INDEX IF NOT EXISTS idx_pedido_atendimentos_item ON pedido_venda_atendimentos(pedido_item_id,status);
CREATE INDEX IF NOT EXISTS idx_pedido_eventos_pedido ON pedido_venda_eventos(pedido_id,criado_em);
CREATE INDEX IF NOT EXISTS idx_expedicoes_pedido ON expedicoes(pedido_venda_id,status);
CREATE INDEX IF NOT EXISTS idx_expedicao_itens_pedido_item ON expedicao_itens(pedido_item_id);
COMMIT;
