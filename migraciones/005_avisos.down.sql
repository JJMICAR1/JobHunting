-- Reversion manual de 005 (NO la aplica migrar(); solo para dev).
DROP TABLE IF EXISTS avisos;
DELETE FROM schema_migraciones WHERE version = '005_avisos';
