# Estado del proyecto

_Última actualización: 2026-11-03_

## Fase actual
**Fase 1 — Fundación: hecha, pendiente de "Fase 1 OK" del CEO.**
No se empieza la Fase 2 hasta esa puerta.

| Fase | Estado |
|------|--------|
| 0. Arranque | OK (CEO) |
| 1. Fundación | Entregada, esperando puerta |
| 2–9 | Sin empezar |

## Qué hay
- `.claude/agents/`: scraper-dev, tester, db-engineer, ml-engineer, devops, reviewer
  (todos `model: sonnet`, ninguno puede crear subagentes, reviewer solo lectura).
- `tests/test_humo.py`: test de prueba (comprueba los agentes y sus permisos).
- `.github/workflows/tests.yml`: ejecuta `pytest` en cada PR y en push a `main`.
  Sin cron, sin secretos, `permissions: contents: read`.
- `pyproject.toml`: config de pytest; los tests `@pytest.mark.live` no corren por defecto.

## Agentes activos por fase
- Fase 2: devops, reviewer.
- Fase 3: scraper-dev, tester, db-engineer, devops, reviewer.
- Fase 8: ml-engineer.

## Decisiones
- Tests con `pytest`; CI en GitHub Actions (gratis en repo público).

## Pendientes
- Antes de la Fase 3: crear Neon (rama `dev`) y los GitHub Secrets (lo hace el CEO; el jefe
  dará los pasos).
- Puerta Fase 1: el CEO comprueba que el workflow `tests` pasa en el PR y escribe "Fase 1 OK".
