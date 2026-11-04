-- Fase 7 (etiquetado Si/No): config, envios y etiquetas. Sin token ni chat_id en la BD.
CREATE TABLE IF NOT EXISTS config (
    clave       text PRIMARY KEY,
    valor       jsonb NOT NULL,
    actualizado timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS envios_etiquetado (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    portal     text NOT NULL,
    id_portal  text NOT NULL,
    enviado    timestamptz NOT NULL,
    muestra    text NOT NULL CHECK (muestra IN ('reglas','azar')),
    nota       real,
    message_id bigint,
    UNIQUE (portal, id_portal),
    FOREIGN KEY (portal, id_portal) REFERENCES ofertas (portal, id_portal) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS etiquetas (
    portal     text NOT NULL,
    id_portal  text NOT NULL,
    etiqueta   boolean NOT NULL,
    etiquetada timestamptz NOT NULL,
    envio_id   bigint REFERENCES envios_etiquetado (id),
    PRIMARY KEY (portal, id_portal),
    FOREIGN KEY (portal, id_portal) REFERENCES ofertas (portal, id_portal) ON DELETE CASCADE
);
