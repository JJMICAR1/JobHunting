# Estado del proyecto

_Última actualización: 2026-11-03 (Fase 2 OK)_

## Fase actual
**Fase 2 — Viabilidad: OK (CEO, 2026-11-03).** Resultado en `docs/VIABILIDAD.md`.
Siguiente: Fase 3 — Esqueleto andante con Tecnoempleo, en una sesión nueva.

| Fase | Estado |
|------|--------|
| 0. Arranque | OK (CEO) |
| 1. Fundación | OK (CEO) |
| 2. Viabilidad | OK (CEO) |
| 3. Esqueleto andante | Siguiente |
| 4–9 | Sin empezar |

## Qué hay
- `.claude/agents/`: scraper-dev, tester, db-engineer, ml-engineer, devops, reviewer
  (todos `model: sonnet`, ninguno puede crear subagentes, reviewer solo lectura).
- `tests/test_humo.py`: test de prueba (comprueba los agentes y sus permisos).
- `.github/workflows/tests.yml`: ejecuta `pytest` en cada PR y en push a `main`.
  Sin cron, sin secretos, `permissions: contents: read`.
- `scripts/sonda_portales.py` + `.github/workflows/sonda.yml` (solo `workflow_dispatch`):
  sonda de viabilidad; tests en `tests/test_sonda.py` (sin red).
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

- 2026-11-03 (Fase 2): desde Actions, solo Tecnoempleo responde; InfoJobs (captcha), Jooble
  (Cloudflare) y Glassdoor (403) bloquean, y LinkedIn lo prohíbe por robots.txt. No se usan
  proxies (reglas 7 y 8). Propuesta: Fase 3 con Tecnoempleo; APIs oficiales de InfoJobs/Jooble
  como fuentes de la Fase 4, si el CEO las aprueba.

## Pendientes
- Hecho (CEO, 2026-11-03): Neon free, proyecto `jobhunting` en Frankfurt (Postgres 18), ramas
  `production` y `dev` (sin auto-borrado), secretos `NEON_URL_PROD` y `NEON_URL_DEV` en GitHub.
  La contraseña se rotó tras pegarse en un chat. Nunca pegar cadenas de conexión en el chat ni en el repo.
- Fase 3: añadir `.env*` al `.gitignore` antes de usar la CLI de Neon (escribe `.env.local`).
- CEO (2026-11-03): en la Fase 4 hay que intentar que funcionen todos los portales. Si para alguno
  la única vía rompe las reglas 7 u 8, el jefe para y el CEO decide.
- CEO: decidir si se piden claves de las APIs de InfoJobs y Jooble (gratis, nuevo servicio + secreto).
- Hecho: actions a Node 24 (checkout@v5, setup-python@v6, upload-artifact@v6).
