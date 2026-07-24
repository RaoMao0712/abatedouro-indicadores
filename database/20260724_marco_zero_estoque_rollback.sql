-- Rollback técnico da estrutura do marco zero (PostgreSQL).
-- Executar somente após exportar estoque_eventos e estoque_marcos.
-- O rollback não apaga ordens, apontamentos, caixas ou composições históricas.

DROP INDEX IF EXISTS idx_estoque_eventos_caixa;
DROP INDEX IF EXISTS idx_pa_operacional_disponibilidade;
DROP TABLE IF EXISTS estoque_eventos;
DROP TABLE IF EXISTS estoque_marcos;

ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS local_anterior_id;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS condicao_anterior;
ALTER TABLE expedicao_itens DROP COLUMN IF EXISTS situacao_anterior;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS justificativa;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS estornado_em;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS cancelado_em;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS concluido_em;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS atualizado_em;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS perfil_criacao;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS criado_por;
ALTER TABLE expedicoes DROP COLUMN IF EXISTS origem;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS formado_em;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS formado_por;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS reservado_expedicao_id;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS motivo_nao_conformidade;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS zona_estoque;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS disponibilidade;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS condicao;
ALTER TABLE pa_caixas DROP COLUMN IF EXISTS estoque_operacional;
ALTER TABLE ordens_producao DROP COLUMN IF EXISTS estoque_marco_id;
ALTER TABLE ordens_producao DROP COLUMN IF EXISTS estoque_classificacao;
