CREATE TABLE IF NOT EXISTS processos_produtivos_codigo_seq (
    chave TEXT PRIMARY KEY,
    ultimo_valor BIGINT NOT NULL DEFAULT 0 CHECK (ultimo_valor >= 0)
);

INSERT INTO processos_produtivos_codigo_seq (chave, ultimo_valor)
SELECT
    'PROCESSO',
    COALESCE(MAX(SUBSTRING(codigo FROM 6)::BIGINT), 0)
FROM processos_produtivos
WHERE codigo ~ '^PROC-[0-9]+$'
ON CONFLICT (chave) DO UPDATE
SET ultimo_valor = GREATEST(
    processos_produtivos_codigo_seq.ultimo_valor,
    EXCLUDED.ultimo_valor
);
