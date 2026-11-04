-- Reversion manual de 006 (NO la aplica migrar(); solo para dev).
DROP TABLE IF EXISTS etiquetas;
DROP TABLE IF EXISTS envios_etiquetado;
DROP TABLE IF EXISTS config;
DELETE FROM schema_migraciones WHERE version = '006_etiquetado';
