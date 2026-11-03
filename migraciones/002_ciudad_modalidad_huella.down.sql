-- Reversion manual de 002 (NO la aplica migrar(); solo para dev).
DROP VIEW IF EXISTS v_mercado_ciudad_modalidad, v_grupos_ofertas;
ALTER TABLE recuento_diario DROP COLUMN IF EXISTS n_unicas;
DROP INDEX IF EXISTS ofertas_portal_huella_idx, ofertas_ciudad_modalidad_idx;
ALTER TABLE ofertas DROP CONSTRAINT IF EXISTS ofertas_modalidad_chk;
ALTER TABLE ofertas DROP COLUMN IF EXISTS huella, DROP COLUMN IF EXISTS modalidad, DROP COLUMN IF EXISTS ciudad;
DELETE FROM schema_migraciones WHERE version = '002_ciudad_modalidad_huella';
