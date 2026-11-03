-- Reversion manual de 003 (NO la aplica migrar(); solo para dev).
ALTER TABLE ejecuciones DROP COLUMN IF EXISTS total_anunciado, DROP COLUMN IF EXISTS n_descartadas;
DELETE FROM schema_migraciones WHERE version = '003_ejecuciones_salud';
