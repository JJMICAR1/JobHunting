-- 001_inicial: esquema base (idempotente). Todas las fechas en UTC (timestamptz).
CREATE TABLE IF NOT EXISTS schema_migraciones (
    version   text PRIMARY KEY,
    aplicada  timestamptz NOT NULL DEFAULT now()
);

-- Ficha ligera: sin descripcion.
CREATE TABLE IF NOT EXISTS ofertas (
    portal             text NOT NULL,
    id_portal          text NOT NULL,
    titulo             text NOT NULL,
    url                text NOT NULL,
    empresa            text,
    ubicacion          text,
    fecha_publicacion  timestamptz,
    primera_vez        timestamptz NOT NULL,
    ultima_vez         timestamptz NOT NULL,
    PRIMARY KEY (portal, id_portal)
);
CREATE INDEX IF NOT EXISTS ofertas_ultima_vez_idx ON ofertas (portal, ultima_vez);
CREATE INDEX IF NOT EXISTS ofertas_primera_vez_idx ON ofertas (portal, primera_vez);

CREATE TABLE IF NOT EXISTS recuento_diario (
    dia       date NOT NULL,          -- dia UTC
    portal    text NOT NULL,
    n_vistas  integer NOT NULL,
    n_nuevas  integer NOT NULL,
    PRIMARY KEY (dia, portal)
);

CREATE TABLE IF NOT EXISTS ejecuciones (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portal     text NOT NULL,
    inicio     timestamptz NOT NULL,
    fin        timestamptz NOT NULL,
    estado     text NOT NULL CHECK (estado IN ('ok','bloqueado','error')),
    n_ofertas  integer NOT NULL DEFAULT 0,
    detalle    text
);
CREATE INDEX IF NOT EXISTS ejecuciones_portal_fin_idx ON ejecuciones (portal, fin DESC);
