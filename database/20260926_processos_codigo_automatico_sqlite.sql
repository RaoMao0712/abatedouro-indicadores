CREATE TABLE IF NOT EXISTS processos_produtivos_codigo_seq (
    chave TEXT PRIMARY KEY,
    ultimo_valor INTEGER NOT NULL DEFAULT 0 CHECK (ultimo_valor >= 0)
);

INSERT OR IGNORE INTO processos_produtivos_codigo_seq (chave, ultimo_valor)
VALUES ('PROCESSO', 0);

UPDATE processos_produtivos_codigo_seq
SET ultimo_valor = MAX(
    ultimo_valor,
    COALESCE((
        SELECT MAX(CAST(SUBSTR(codigo, 6) AS INTEGER))
        FROM processos_produtivos
        WHERE codigo GLOB 'PROC-[0-9]*'
          AND LENGTH(SUBSTR(codigo, 6)) > 0
          AND SUBSTR(codigo, 6) NOT GLOB '*[^0-9]*'
    ), 0)
)
WHERE chave = 'PROCESSO';
