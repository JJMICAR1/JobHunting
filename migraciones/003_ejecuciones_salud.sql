-- Fase 5 (salud): datos por ejecucion para detectar selectores rotos a medias.
ALTER TABLE ejecuciones ADD COLUMN IF NOT EXISTS n_descartadas integer NOT NULL DEFAULT 0;
ALTER TABLE ejecuciones ADD COLUMN IF NOT EXISTS total_anunciado integer;
