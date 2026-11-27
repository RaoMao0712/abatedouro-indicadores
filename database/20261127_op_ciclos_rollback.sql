-- Rollback anterior ao uso do reprocessamento. Arquiva o modelo se já houver novos ciclos.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM op_ciclos WHERE numero_ciclo > 1 OR operacao_reset_id IS NOT NULL)
       OR EXISTS (SELECT 1 FROM op_planos_reprocessamento)
       OR EXISTS (SELECT 1 FROM op_ciclo_registros_invalidados) THEN
        RAISE EXCEPTION 'Rollback recusado: existem ciclos de reprocessamento auditáveis.';
    END IF;
END;
$$;
DROP TRIGGER IF EXISTS trg_op_ciclo_corrente ON ordens_producao;
DROP TRIGGER IF EXISTS trg_op_ciclo_excluir ON ordens_producao;
DROP FUNCTION IF EXISTS sincronizar_ciclo_corrente_op();
DROP TABLE op_planos_reprocessamento;
DROP TABLE op_ciclo_registros_invalidados;
DROP TABLE op_ciclos;
