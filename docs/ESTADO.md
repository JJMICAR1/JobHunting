# Estado del proyecto

_Última actualización: 2026-11-03_

## Fase actual
**Fase 1 — Fundación: OK (CEO, 2026-11-03).** Siguiente: Fase 2 — Viabilidad, en una sesión nueva.

| Fase | Estado |
|------|--------|
| 0. Arranque | OK (CEO) |
| 1. Fundación | OK (CEO) |
| 2. Viabilidad | Siguiente |
| 3–9 | Sin empezar |

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
- 2026-11-03: Actions no arrancaba porque la cuenta de GitHub estaba bloqueada por facturación.
  El CEO lo resolvió y el workflow `tests` pasó en `main`. Si un job falla en 2-3 s sin log,
  mirar primero las anotaciones del check (puede ser otra vez facturación).

## Pendientes
- Antes de la Fase 3: crear Neon (rama `dev`) y los GitHub Secrets (lo hace el CEO; el jefe
  dará los pasos).
- Inicio de la Fase 2: subir `actions/checkout` y `actions/setup-python` a versiones con Node 24
  (aviso de que Node 20 está obsoleto).
