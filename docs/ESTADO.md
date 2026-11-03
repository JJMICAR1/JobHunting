# Estado del proyecto

_Última actualización: 2026-11-03 (Fase 3 en revisión)_

## Fase actual
**Fase 3 — Esqueleto andante: construida, pendiente de puerta del CEO.**
Tecnoempleo (Catalunya) -> Neon dev -> recuento diario. Falta: comprobación manual del CEO y OK al cron de prod.

| Fase | Estado |
|------|--------|
| 0. Arranque | OK (CEO) |
| 1. Fundación | OK (CEO) |
| 2. Viabilidad | OK (CEO) |
| 3. Esqueleto andante | En revisión (PR) |
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
- Fase 3:
  - `jobhunting/modelo.py` (contrato `Oferta`, UTC, dedup), `bloqueo.py`, `descarga.py` (robots.txt,
    Crawl-delay, sin reintentos, para ante 403/429/captcha y redirecciones a otro host).
  - `jobhunting/portales/tecnoempleo/{parser,scraper}.py`: listado Catalunya
    `?pr=,240,252,262,276,` (Barcelona, Girona, Lleida, Tarragona), 30 por página, pausa 5 s, tope 30 páginas.
  - `jobhunting/db.py` + `migraciones/001_inicial.sql`: `ofertas` (upsert por portal+id),
    `recuento_diario` (recalculado en SQL, idempotente), `ejecuciones` (para el latido), `schema_migraciones`.
  - `jobhunting/pipeline.py` (`python -m jobhunting.pipeline [--dry-run]`, env `DATABASE_URL`;
    salida 0 ok / 2 bloqueado / 1 error). Un bloqueo a medias guarda ofertas pero no recuento.
  - Workflows: `pipeline` (manual: dev o dry-run; push en `claude/**` que cambie el workflow = ejecución
    en Neon dev), `fixture` (captura HTML para tests), `tests` con Postgres 16 de servicio.
  - Tests: 110 (16 de BD se saltan sin `TEST_DATABASE_URL`) + 1 live.

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

- 2026-11-03 (Fase 3): `?provincia=9` de la sonda NO filtraba (era toda España); el filtro real es `pr=`.
  Catalunya ≈ 640 ofertas incluyendo remotas. Los secretos se llaman `NEO_URL_DEV` / `NEO_URL_PROD`
  (sin la N); el código usa esos nombres. Commit explícito: `db.conectar` abre en autocommit.
- Test local en la nube: Postgres 16 del contenedor (`/usr/lib/postgresql/16/bin`), usar `python3 -m pytest`.

## Pendientes
- Hecho (CEO, 2026-11-03): Neon free, proyecto `jobhunting` en Frankfurt (Postgres 18), ramas
  `production` y `dev` (sin auto-borrado), secretos `NEON_URL_PROD` y `NEON_URL_DEV` en GitHub.
  La contraseña se rotó tras pegarse en un chat. Nunca pegar cadenas de conexión en el chat ni en el repo.
- Hecho: `.env*` en `.gitignore`.
- Fase 3: en vivo se descartan ~14 de 640 tarjetas; el resumen del pipeline ya muestra el motivo. Revisar.
- CEO: OK al cron diario contra Neon prod (`NEO_URL_PROD`) para cerrar la Fase 3.
- CEO (2026-11-03): en la Fase 4 hay que intentar que funcionen todos los portales. Si para alguno
  la única vía rompe las reglas 7 u 8, el jefe para y el CEO decide.
- CEO: decidir si se piden claves de las APIs de InfoJobs y Jooble (gratis, nuevo servicio + secreto).
- Hecho: actions a Node 24 (checkout@v5, setup-python@v6, upload-artifact@v6).
