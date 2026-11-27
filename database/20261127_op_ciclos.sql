CREATE TABLE IF NOT EXISTS op_ciclos (
    id BIGSERIAL PRIMARY KEY,
    op_id INTEGER NOT NULL REFERENCES ordens_producao(id) ON DELETE RESTRICT,
    numero_ciclo INTEGER NOT NULL CHECK (numero_ciclo > 0),
    status TEXT NOT NULL CHECK (status IN ('ATIVO', 'ENCERRADO', 'ESTORNADO', 'INVALIDADO_REPROCESSAMENTO')),
    corrente INTEGER NOT NULL DEFAULT 1 CHECK (corrente IN (0, 1)),
    iniciado_em TIMESTAMP,
    iniciado_por TEXT NOT NULL,
    encerrado_em TIMESTAMP,
    invalidado_em TIMESTAMP,
    invalidado_por TEXT,
    motivo_invalidacao TEXT,
    operacao_reset_id TEXT UNIQUE,
    UNIQUE (op_id, numero_ciclo),
    CHECK ((corrente = 0) = (status = 'INVALIDADO_REPROCESSAMENTO'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_op_ciclos_corrente ON op_ciclos (op_id) WHERE corrente = 1;

CREATE TABLE IF NOT EXISTS op_ciclo_registros_invalidados (
    ciclo_id BIGINT NOT NULL REFERENCES op_ciclos(id),
    tabela TEXT NOT NULL,
    registro_id BIGINT NOT NULL,
    PRIMARY KEY (tabela, registro_id)
);

CREATE TABLE IF NOT EXISTS op_planos_reprocessamento (
    id TEXT PRIMARY KEY,
    ciclo_id BIGINT NOT NULL REFERENCES op_ciclos(id),
    versao_operacional INTEGER NOT NULL,
    hash_consequencias TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    criado_por TEXT NOT NULL,
    criado_em TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO op_ciclos (op_id, numero_ciclo, status, iniciado_por)
SELECT id, 1, CASE UPPER(COALESCE(status, ''))
    WHEN 'ENCERRADA' THEN 'ENCERRADO'
    WHEN 'ESTORNADA' THEN 'ESTORNADO'
    WHEN 'ESTORNADO' THEN 'ESTORNADO'
    ELSE 'ATIVO' END, 'Backfill'
FROM ordens_producao
ON CONFLICT (op_id, numero_ciclo) DO NOTHING;

CREATE OR REPLACE FUNCTION sincronizar_ciclo_corrente_op()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    estado TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM op_ciclos c
        WHERE c.op_id=OLD.id AND c.numero_ciclo=1 AND c.corrente=1
          AND NOT EXISTS (SELECT 1 FROM op_planos_reprocessamento p WHERE p.ciclo_id=c.id)
          AND NOT EXISTS (SELECT 1 FROM op_ciclo_registros_invalidados r WHERE r.ciclo_id=c.id);
        RETURN OLD;
    END IF;
    estado := CASE UPPER(COALESCE(NEW.status, ''))
        WHEN 'ENCERRADA' THEN 'ENCERRADO'
        WHEN 'ESTORNADA' THEN 'ESTORNADO'
        WHEN 'ESTORNADO' THEN 'ESTORNADO'
        ELSE 'ATIVO' END;
    IF TG_OP = 'INSERT' THEN
        INSERT INTO op_ciclos (op_id, numero_ciclo, status, iniciado_em, iniciado_por)
        VALUES (NEW.id, 1, estado, CURRENT_TIMESTAMP, 'Sistema');
    ELSE
        UPDATE op_ciclos SET status = estado,
            encerrado_em = CASE WHEN estado = 'ENCERRADO' THEN CURRENT_TIMESTAMP
                                WHEN estado = 'ATIVO' THEN NULL ELSE encerrado_em END
        WHERE op_id = NEW.id AND corrente = 1 AND status <> estado;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_op_ciclo_corrente ON ordens_producao;
CREATE TRIGGER trg_op_ciclo_corrente
AFTER INSERT OR UPDATE OF status ON ordens_producao
FOR EACH ROW EXECUTE FUNCTION sincronizar_ciclo_corrente_op();

DROP TRIGGER IF EXISTS trg_op_ciclo_excluir ON ordens_producao;
CREATE TRIGGER trg_op_ciclo_excluir
BEFORE DELETE ON ordens_producao
FOR EACH ROW EXECUTE FUNCTION sincronizar_ciclo_corrente_op();
