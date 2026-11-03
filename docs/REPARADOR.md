# Reparación (Fase 5)

**Tarea programada "Reparador JobHunting"** (creada por el CEO en claude.ai/code → Routines, con el repo
`JJMICAR1/JobHunting` seleccionado; Sonnet; diaria a las 9:23 hora de Madrid, después de `salud` a las 07:41 UTC).
Cada ejecución es una sesión nueva: si no hay issues `alerta` abiertos responde "Sin alertas" y termina.
Probada el 2026-11-03: lee el repo y los issues (respuesta "Sin alertas").
Si la tarea no basta, el CEO abre la sesión de la fase y el jefe repara con subagentes, cuidando la cuota.

## Flujo
1. `pipeline` registra cada ejecución en la tabla `ejecuciones` (estado, ofertas, descartadas, total anunciado).
2. `salud` (`python -m jobhunting.salud`) evalúa y abre un issue por alerta con la etiqueta `alerta`:
   título `[alerta][prod|dev] <portal>: <tipo>`. Lo cierra solo cuando la alerta desaparece.
3. La tarea programada (o el jefe, desde la sesión de la fase) atiende cada issue abierto con la etiqueta `alerta`.

| Tipo | Significado | Qué hace el reparador |
|------|-------------|------------------------|
| `error` | excepción o `ParserRoto` | Reproducir con fixture y arreglar el parser. |
| `cero` | ok pero 0 ofertas | Selector de tarjetas/listado cambiado: arreglar el parser. |
| `descartes` | >10 % de tarjetas descartadas | Un campo (título, id, url...) ha cambiado: arreglar el parser. |
| `incompleto` | <80 % del total anunciado | Paginación rota: arreglar el scraper. |
| `caida` | <50 % de la mediana reciente | Investigar; si es el mercado real, comentar y no tocar código. |
| `bloqueado` | 403/429/captcha/robots | **No arreglar**: comentar en el issue y avisar al CEO (regla 7). |
| `sin_ejecucion` | el cron no corrió en >28 h | **No tocar workflows**: comentar en el issue (posible facturación o cron apagado). |

## Reglas de la reparación
- Rama `claude/reparar-<portal>-<tipo>` desde `main`.
  Nunca toca `main`, secretos, Neon prod ni workflows de cron. Nunca hace merge.
- Si ya hay un PR abierto que enlaza el issue, no abre otro (idempotencia).
- Desde la nube no se puede descargar de los portales: para ver el HTML/XML nuevo, ejecuta en Actions el workflow
  `fixture` (Tecnoempleo) o `diagnostico` (Feina Activa) en su rama, y descarga el artefacto.
- Arreglo mínimo: fixture nuevo en `tests/fixtures/`, test que falla antes y pasa después, `python3 -m pytest` en verde.
- Abre un PR que cierre el issue (`Closes #N`), con causa, cambio y prueba. El CEO revisa y fusiona.
- Comentar en el issue el enlace al PR. Al fusionar y volver a ejecutar, `salud` cierra el issue sola.

## Prompt de la tarea programada
> Eres el reparador de JobHunting. Lee CLAUDE.md y docs/REPARADOR.md de main. Con las herramientas de GitHub lista
> los issues abiertos con la etiqueta alerta. Si no hay ninguno, responde "Sin alertas" y termina. Si los hay, sigue
> docs/REPARADOR.md: rama claude/reparar-<portal>-<tipo> desde main, test que falla antes y pasa después, PR con
> "Closes #N". Nunca hagas merge ni toques main, secretos, Neon prod o workflows.

## Lecciones (2026-11-03)
- Una tarea programada creada **desde una sesión** de Claude arranca sin repo y sin `add_repo` (403 de GitHub):
  no sirve. Debe crearla el CEO en claude.ai con el repo seleccionado. Solo el CEO puede lanzarla a mano.
- Una sesión de Claude no hace push/PR porque se lo pida otra sesión (necesita confirmación humana).
- En sesiones en la nube, `gh issue list` falla (GraphQL bloqueado): usar las herramientas MCP de GitHub.

## Simulacro (puerta de la Fase 5, 2026-11-03)
Selector de tarjetas de Tecnoempleo roto a propósito (`bg-white` → `bg-blanco`) en `claude/fase-5-al-lio-0bm1ey`
→ `pipeline` en Neon dev guarda 0 ofertas → `salud` abre el issue #14 `[alerta][dev] tecnoempleo: cero`
→ scraper-dev arregla en `claude/reparar-tecnoempleo-cero` con test de regresión → PR #15
→ `pipeline` en dev con el arreglo → `salud` cierra el issue.
