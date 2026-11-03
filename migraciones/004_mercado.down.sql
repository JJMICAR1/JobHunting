-- Reversion manual de 004 (NO la aplica migrar(); solo para dev).
DROP VIEW IF EXISTS v_mercado_hoy;
DROP VIEW IF EXISTS v_mercado_diario;
ALTER TABLE recuento_diario DROP COLUMN IF EXISTS n_desaparecidas;
DELETE FROM schema_migraciones WHERE version = '004_mercado';
