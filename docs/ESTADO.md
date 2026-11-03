# Estado del proyecto

_Última actualización: 2026-11-03 (Fase 4 OK; siguiente Fase 5)_

## Tareas del CEO (lo que tienes que hacer tú)
_El jefe actualiza esta lista al final de cada sesión. Si está vacía, no tienes nada pendiente._

1. Abrir una sesión nueva y escribir **"Empezamos la Fase 5"**.

Nada más es urgente. Lo que queda de fuentes está en la **Fase 4.5**, más abajo, para hacerlo más adelante.

## Fase actual
**Fase 4 — Fuentes: OK (CEO, 2026-11-03).** Cerrada con Tecnoempleo y Feina Activa (PR #10 y #11 fusionados).
El cron de prod está activo desde el 2026-11-03 (05:17 UTC, los dos portales); su primera ejecución es el 2026-11-04.
**Siguiente: Fase 5 — Salud y reparación**, en una sesión nueva.
Al empezar la Fase 5, lo primero: comprobar en Actions que el cron de prod corrió (evento schedule) y que
`recuento_diario` de la rama `production` tiene fila de hoy para `tecnoempleo` y `feinaactiva`.

## Fase 4.5 — Fuentes pendientes (más adelante, sin bloquear las fases siguientes)
Cada fuente necesita la decisión del CEO y su propia puerta (tests, ejecución en Neon dev y revisión del CEO).
- **Jobfluent** (tech, Barcelona, unas 34 ofertas): el HTML se deja leer y robots.txt lo permite. El aviso legal está
  en zona gris: no prohíbe el acceso automatizado, pero no cede derechos de explotación. **CEO: ¿sí o no?**
- **Infoempleo** (unas 67 ofertas en Barcelona): el HTML se deja leer, pero el aviso legal no se puede leer
  automáticamente. **CEO: leer infoempleo.com/avisolegal/ y decir si permite robots o la extracción de datos.**
- **Greenhouse / Lever / Ashby** (APIs públicas de empleo de empresas): técnicamente viables (Typeform responde).
  **CEO: dar una lista de empresas de interés**; el jefe busca sus slugs.
- **Adzuna** (API, gratis para búsqueda personal, con atribución): **CEO: darse de alta en developer.adzuna.com**
  y guardar la clave como secretos (el jefe dirá antes los nombres).
- Repetir la sonda: **Barcelona Activa** (la URL era incorrecta), **SEPE Empléate** y **Careerjet** (robots.txt no leído).
- Descartadas (no reintentar): InfoJobs API (prohíbe agregadores), Jooble API (500 peticiones de por vida),
  Talent.com (prohíbe el scraping), Ticjob (prohíbe descargar la web), Indeed (captcha), LinkedIn (robots.txt),
  Glassdoor (403), SmartRecruiters (robots.txt).
- Seguridad (opcional, CEO): un GitHub Environment `prod` con `NEO_URL_PROD`, limitado a `main`.

| Fase | Estado |
|------|--------|
| 0. Arranque | OK (CEO) |
| 1. Fundación | OK (CEO) |
| 2. Viabilidad | OK (CEO) |
| 3. Esqueleto andante | OK (CEO) |
| 4. Fuentes | OK (CEO) |
| 4.5 Fuentes pendientes | Más adelante |
| 5. Salud y reparación | Siguiente |
| 6–9 | Sin empezar |

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
  - Migración 002 (CEO): `ciudad` y `modalidad` (presencial/hibrido/remoto) separadas para todas las
    ciudades; `huella` = empresa+título+ciudad normalizados. Repetidas NO se fusionan (pueden ser varias
    vacantes): vista `v_grupos_ofertas`; mercado en `v_mercado_ciudad_modalidad`; `recuento_diario.n_unicas`.
  - Tests: 150 (24 de BD se saltan sin `TEST_DATABASE_URL`) + 1 live.
- Fase 4:
  - `sonda_portales.py --grupo fase2|fase4|condiciones`. fase4 prueba portales HTML, feeds XML/JSON y APIs
    de ATS, y solo registra nombres de campo y recuentos. condiciones vuelca al log el texto de las condiciones
    de uso de las APIs. robots.txt se comprueba en cada redirect, hay topes de lectura y, tras un 403/429,
    se saltan las demás URLs de ese host. Un push de `sonda.yml` en `claude/**` ejecuta fase4 y luego condiciones.
  - `pipeline.yml`: `schedule` 05:17 UTC, con un paso prod (`NEO_URL_PROD`) que solo corre en schedule.
  - Tests: 218 (24 de BD se saltan) + 1 live.
- Fase 4, fuente Feina Activa:
  - `jobhunting/portales/feinaactiva/`: un GET diario de unos 7 MB a `feinaactiva.gencat.cat/api/offers/offers-xml`.
    Grupos `feinaactiva` (unas 3980) y `sicas` (668, del SOC). Ficha ligera: id, título, empresa, ciudad/región,
    fecha (medianoche de Madrid pasada a UTC), url y modalidad. NO se guardan content, requisitos ni salarios.
  - `jobhunting/xml_seguro.py`: rechaza DOCTYPE/ENTITY y tiene topes de bytes y de tiempo.
    `descarga.descargar_bytes`: `_Redireccion` NO sigue saltos a otro host y comprueba robots.txt antes de cada
    salto (también para Tecnoempleo; como mucho 3 saltos).
  - Pipeline multi-portal: `--portal tecnoempleo|feinaactiva|todos` (por defecto todos). Cada portal es
    independiente y el código de salida es el peor. El cron ejecuta todos.
  - Licencia: reutilización libre citando la fuente (Generalitat de Catalunya, Feina Activa) y la fecha de
    actualización, sin desnaturalizar la información (Ley 37/2007).
  - `scripts/diagnostico_feinaactiva.py` + workflow `diagnostico`: muestra la estructura del XML sin valores.
  - `db.guardar_ofertas` guarda por lotes de 500 (executemany en modo pipeline). La ejecución de los dos portales
    pasa de 10,5 min a 2 min 13 s (el timeout es de 15).
  - Neon dev, 2026-11-03: 1.ª ejecución, Feina Activa 4655 ofertas (3987 feinaactiva + 668 sicas), 0 descartadas,
    4570 puestos únicos. 2.ª ejecución, 1 nueva (idempotente). Tecnoempleo 632, sin cambios.
  - Tests: 514 con BD.

## Agentes activos por fase
- Fase 2: devops, reviewer.
- Fase 3: scraper-dev, tester, db-engineer, devops, reviewer.
- Fase 4: scraper-dev, tester, reviewer (+ devops si hay secretos de API nuevos).
- Fase 5: devops, scraper-dev, tester, reviewer.
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

- 2026-11-03 (CEO, plan de la Fase 4): NO se construye nada que salte captchas, Cloudflare u otras
  protecciones (regla 7, riesgo legal, coste). La Fase 4 combina:
  1. APIs oficiales gratuitas de InfoJobs y Jooble: el jefe revisa primero sus condiciones de uso
     (límites, si permiten guardar datos) y luego el CEO da de alta las claves como secretos.
  2. Sonda de portales nuevos que se dejen leer (portales públicos de empleo, webs catalanas, páginas
     de empleo de empresas), con su tabla funciona/bloqueado como en la Fase 2.
  3. Fuentes con formatos abiertos (feeds de ofertas).
  Cada fuente nueva necesita el OK del CEO y su propia puerta.

- 2026-11-03 (Fase 4, avisos legales): Talent.com prohíbe el scraping y Ticjob prohíbe descargar la web: los dos
  quedan descartados. Jobfluent está en zona gris (lo decide el CEO). Infoempleo no se pudo leer. Ver `docs/VIABILIDAD_FASE4.md` §4.
- 2026-11-03 (Fase 4, condiciones leídas desde Actions): la API de InfoJobs prohíbe los agregadores de ofertas,
  así que no es viable. El plan gratis de Jooble da 500 peticiones de por vida, así que tampoco. Adzuna permite
  la búsqueda personal (necesita el OK del CEO). Mejor candidata: el XML abierto de Feina Activa (Generalitat).

## Pendientes
- Hecho (CEO, 2026-11-03): Neon free, proyecto `jobhunting` en Frankfurt (Postgres 18), ramas
  `production` y `dev` (sin auto-borrado), secretos `NEON_URL_PROD` y `NEON_URL_DEV` en GitHub.
  La contraseña se rotó tras pegarse en un chat. Nunca pegar cadenas de conexión en el chat ni en el repo.
- Hecho: `.env*` en `.gitignore`.
- Hecho (Fase 3): 14 tarjetas descartadas (ids `rf-` alfanuméricos) y 18 sin ubicación (texto sin `<b>`)
  corregidos; fixture `tarjetas_raras.html`. Pipeline en dev: 632/633 ofertas, 0 descartadas.
  Diagnóstico reutilizable: `scripts/diagnostico_tecnoempleo.py` (workflow `fixture` en push).
- CEO: OK al cron diario contra Neon prod (`NEO_URL_PROD`) para cerrar la Fase 3.
- CEO (2026-11-03): en la Fase 4 hay que intentar que funcionen todos los portales. Si para alguno
  la única vía rompe las reglas 7 u 8, el jefe para y el CEO decide.
- Siguiente sesión: comprobar que el cron de prod corre (pipeline con evento schedule, 05:17 UTC)
  y que `recuento_diario` tiene fila del día en la rama `production`. Hasta hoy no ha corrido nunca.
- CEO: puerta de Feina Activa (revisar el recuento en Neon dev y fusionar el PR). Siguientes candidatas, por puertas:
  Infoempleo, Ticjob y Jobfluent (antes, leer su aviso legal), Greenhouse/Lever por empresa (hace falta una
  lista de slugs) y Adzuna (clave nueva).
- Recomendado por el reviewer (lo decide el CEO): un GitHub Environment `prod` con `NEO_URL_PROD` limitado a `main`.
- Hecho: actions a Node 24 (checkout@v5, setup-python@v6, upload-artifact@v6).
