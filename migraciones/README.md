# Migraciones

- `NNN_nombre.sql` se aplican en orden por `jobhunting.db.migrar`; son idempotentes y se registran en `schema_migraciones`.
- `NNN_nombre.down.sql` es la reversion manual (solo dev; `migrar` la ignora).
- `004_mercado`: `recuento_diario.n_desaparecidas` y vistas `v_mercado_diario` / `v_mercado_hoy` (deltas 1d/7d por portal).
- Solo contra la rama `dev` de Neon; produccion la migra el pipeline.

## Tamano y retencion (limite 0,5 GB de Neon free)
Estimacion por fila de `ofertas` (titulo ~60 B, url ~100 B, empresa ~25 B, ubicacion ~20 B, 3 timestamptz = 24 B,
ids ~15 B, cabecera de tupla 24-28 B, puntero) ~ 300 B de heap + PK (~50 B) + 2 indices (~50 B c/u) ~ 450 B/oferta.
Con margen (bloat, WAL, historial) se cuenta ~0,6-1 KB/oferta: **caben ~400.000-700.000 ofertas** en 0,5 GB
(dejando ~20% libre). `recuento_diario` y `ejecuciones` son despreciables (decenas de MB en anos).
Propuesta de retencion (aun no implementada): borrar ofertas con `ultima_vez` > 90 dias (ya no activas), conservando
`recuento_diario` para siempre; las descripciones de candidatas (Fase 7+) se guardan aparte y se podan primero.
Vigilar con `SELECT pg_database_size(current_database())`.
