BEGIN;
CREATE TEMP TABLE _op_ciclos_rollback_guard (
    permite INTEGER NOT NULL CHECK (permite = 1)
);
INSERT OR ROLLBACK INTO _op_ciclos_rollback_guard
SELECT CASE WHEN EXISTS (
    SELECT 1 FROM op_ciclos WHERE numero_ciclo > 1 OR operacao_reset_id IS NOT NULL
) OR EXISTS (
    SELECT 1 FROM op_planos_reprocessamento
) OR EXISTS (
    SELECT 1 FROM op_ciclo_registros_invalidados
) THEN 0 ELSE 1 END;
DROP TABLE _op_ciclos_rollback_guard;
DROP TRIGGER IF EXISTS trg_op_ciclo_criar;
DROP TRIGGER IF EXISTS trg_op_ciclo_status;
DROP TRIGGER IF EXISTS trg_op_ciclo_excluir;
DROP TABLE op_planos_reprocessamento;
DROP TABLE op_ciclo_registros_invalidados;
DROP TABLE op_ciclos;
COMMIT;
