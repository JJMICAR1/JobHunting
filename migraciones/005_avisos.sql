-- Avisos enviados (uno por dia y tipo): evita duplicados con los crons de respaldo.
CREATE TABLE IF NOT EXISTS avisos (
    dia     date NOT NULL,
    tipo    text NOT NULL,
    enviado timestamptz NOT NULL,
    PRIMARY KEY (dia, tipo)
);
