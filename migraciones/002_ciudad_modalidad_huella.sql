-- 002: ciudad, modalidad y huella por oferta; n_unicas en el recuento (idempotente, UTC).
-- huella = hash (16 hex) de empresa+titulo+ciudad. NO es unica: ofertas repetidas no se fusionan
-- (pueden ser varias vacantes) pero se agrupan para contar puestos unicos.
ALTER TABLE ofertas ADD COLUMN IF NOT EXISTS ciudad    text;
ALTER TABLE ofertas ADD COLUMN IF NOT EXISTS modalidad text;
ALTER TABLE ofertas ADD COLUMN IF NOT EXISTS huella    text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'ofertas_modalidad_chk'
                     AND conrelid = 'ofertas'::regclass) THEN
        ALTER TABLE ofertas ADD CONSTRAINT ofertas_modalidad_chk
            CHECK (modalidad IS NULL OR modalidad IN ('presencial','hibrido','remoto'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ofertas_portal_huella_idx ON ofertas (portal, huella);
CREATE INDEX IF NOT EXISTS ofertas_ciudad_modalidad_idx ON ofertas (ciudad, modalidad);

-- Puestos unicos = huellas distintas vistas ese dia (huella NULL cuenta cada fila aparte).
ALTER TABLE recuento_diario ADD COLUMN IF NOT EXISTS n_unicas integer;

-- Grupos de publicaciones repetidas (misma huella en un portal). Filas sin huella excluidas.
CREATE OR REPLACE VIEW v_grupos_ofertas AS
SELECT portal,
       huella,
       min(empresa) AS empresa,
       min(titulo)  AS titulo,
       min(ciudad)  AS ciudad,
       count(*)     AS n_publicaciones,
       array_agg(id_portal ORDER BY id_portal) AS ids,
       min(primera_vez) AS primera_vez,
       max(ultima_vez)  AS ultima_vez
FROM ofertas
WHERE huella IS NOT NULL
GROUP BY portal, huella
HAVING count(*) > 1;

-- Mercado por ciudad y modalidad sobre TODAS las ofertas guardadas (lo mas simple;
-- filtrar por ultima_vez en la consulta si se quiere solo las activas).
CREATE OR REPLACE VIEW v_mercado_ciudad_modalidad AS
SELECT portal,
       coalesce(ciudad, '(sin ciudad)')      AS ciudad,
       coalesce(modalidad, '(sin indicar)')  AS modalidad,
       count(*) AS n_ofertas,
       count(DISTINCT coalesce(huella, id_portal)) AS n_unicas
FROM ofertas
GROUP BY portal, coalesce(ciudad, '(sin ciudad)'), coalesce(modalidad, '(sin indicar)');
