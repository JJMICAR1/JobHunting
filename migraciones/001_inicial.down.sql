-- Reversion manual de 001 (NO la aplica migrar(); solo para dev).
DROP TABLE IF EXISTS ejecuciones, recuento_diario, ofertas;
DELETE FROM schema_migraciones WHERE version = '001_inicial';
