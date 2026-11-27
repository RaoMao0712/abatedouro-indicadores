CREATE TABLE IF NOT EXISTS op_ciclos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    op_id INTEGER NOT NULL REFERENCES ordens_producao(id) ON DELETE RESTRICT,
    numero_ciclo INTEGER NOT NULL CHECK (numero_ciclo > 0),
    status TEXT NOT NULL CHECK (status IN ('ATIVO', 'ENCERRADO', 'ESTORNADO', 'INVALIDADO_REPROCESSAMENTO')),
    corrente INTEGER NOT NULL DEFAULT 1 CHECK (corrente IN (0, 1)),
    iniciado_em TEXT,
    iniciado_por TEXT NOT NULL,
    encerrado_em TEXT,
    invalidado_em TEXT,
    invalidado_por TEXT,
    motivo_invalidacao TEXT,
    operacao_reset_id TEXT UNIQUE,
    UNIQUE (op_id, numero_ciclo),
    CHECK ((corrente = 0) = (status = 'INVALIDADO_REPROCESSAMENTO'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_op_ciclos_corrente ON op_ciclos (op_id) WHERE corrente = 1;

CREATE TABLE IF NOT EXISTS op_ciclo_registros_invalidados (
    ciclo_id INTEGER NOT NULL REFERENCES op_ciclos(id),
    tabela TEXT NOT NULL,
    registro_id INTEGER NOT NULL,
    PRIMARY KEY (tabela, registro_id)
);

CREATE TABLE IF NOT EXISTS op_planos_reprocessamento (
    id TEXT PRIMARY KEY,
    ciclo_id INTEGER NOT NULL REFERENCES op_ciclos(id),
    versao_operacional INTEGER NOT NULL,
    hash_consequencias TEXT NOT NULL,
    snapshot_json TEXT NOT NULL,
    criado_por TEXT NOT NULL,
    criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO op_ciclos (op_id, numero_ciclo, status, iniciado_por)
SELECT id, 1, CASE UPPER(COALESCE(status, ''))
    WHEN 'ENCERRADA' THEN 'ENCERRADO'
    WHEN 'ESTORNADA' THEN 'ESTORNADO'
    WHEN 'ESTORNADO' THEN 'ESTORNADO'
    ELSE 'ATIVO' END, 'Backfill'
FROM ordens_producao WHERE 1=1
ON CONFLICT (op_id, numero_ciclo) DO NOTHING;

CREATE TRIGGER IF NOT EXISTS trg_op_ciclo_criar
AFTER INSERT ON ordens_producao
BEGIN
    INSERT INTO op_ciclos (op_id, numero_ciclo, status, iniciado_em, iniciado_por)
    VALUES (NEW.id, 1, CASE UPPER(COALESCE(NEW.status, ''))
        WHEN 'ENCERRADA' THEN 'ENCERRADO'
        WHEN 'ESTORNADA' THEN 'ESTORNADO'
        WHEN 'ESTORNADO' THEN 'ESTORNADO'
        ELSE 'ATIVO' END, CURRENT_TIMESTAMP, 'Sistema');
END;

CREATE TRIGGER IF NOT EXISTS trg_op_ciclo_status
AFTER UPDATE OF status ON ordens_producao
WHEN OLD.status IS NOT NEW.status
BEGIN
    UPDATE op_ciclos SET status = CASE UPPER(COALESCE(NEW.status, ''))
        WHEN 'ENCERRADA' THEN 'ENCERRADO'
        WHEN 'ESTORNADA' THEN 'ESTORNADO'
        WHEN 'ESTORNADO' THEN 'ESTORNADO'
        ELSE 'ATIVO' END,
        encerrado_em = CASE UPPER(COALESCE(NEW.status, ''))
        WHEN 'ENCERRADA' THEN CURRENT_TIMESTAMP
        WHEN 'ESTORNADA' THEN encerrado_em
        WHEN 'ESTORNADO' THEN encerrado_em
        ELSE NULL END
    WHERE op_id = NEW.id AND corrente = 1;
END;

CREATE TRIGGER IF NOT EXISTS trg_op_ciclo_excluir
BEFORE DELETE ON ordens_producao
BEGIN
    SELECT RAISE(ABORT, 'OP com histórico de reprocessamento não pode ser excluída')
    WHERE EXISTS (
        SELECT 1 FROM op_ciclos c WHERE c.op_id=OLD.id AND (
            c.numero_ciclo>1 OR c.corrente=0
            OR EXISTS (SELECT 1 FROM op_planos_reprocessamento p WHERE p.ciclo_id=c.id)
            OR EXISTS (SELECT 1 FROM op_ciclo_registros_invalidados r WHERE r.ciclo_id=c.id)
        )
    );
    DELETE FROM op_ciclos WHERE op_id=OLD.id;
END;
