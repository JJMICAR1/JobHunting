# Reparación (Fase 5)

**Norma del CEO (2026-11-03):** las reparaciones se hacen siempre desde la sesión de la fase (el jefe), con
subagentes y cuidando la cuota de sesión. No hay tarea programada de Claude ni sesión fija de reparador.
El CEO recibe el email del issue `alerta`, abre la sesión de la fase y pide la reparación.

## Flujo
1. `pipeline` registra cada ejecución en la tabla `ejecuciones` (estado, ofertas, descartadas, total anunciado).
2. `salud` (`python -m jobhunting.salud`) evalúa y abre un issue por alerta con la etiqueta `alerta`:
   título `[alerta][prod|dev] <portal>: <tipo>`. Lo cierra solo cuando la alerta desaparece.
3. El jefe lista los issues abiertos con la etiqueta `alerta` y delega cada arreglo (scraper-dev para parsers,
   devops para workflows; luego tester y reviewer).

| Tipo | Significado | Qué hace el jefe |
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

## Por qué no hay tarea programada (2026-11-03)
Las tareas programadas creadas desde una sesión arrancan sin repo y sin `add_repo` (403 de GitHub), y una sesión
fija con repo no acepta push/PR por mensajes de otra sesión sin confirmación humana. Además gastan cuota cada día.

## Simulacro (puerta de la Fase 5, 2026-11-03)
Selector de tarjetas de Tecnoempleo roto a propósito (`bg-white` → `bg-blanco`) en `claude/fase-5-al-lio-0bm1ey`
→ `pipeline` en Neon dev guarda 0 ofertas → `salud` abre el issue #14 `[alerta][dev] tecnoempleo: cero`
→ scraper-dev arregla en `claude/reparar-tecnoempleo-cero` con test de regresión → PR #15
→ `pipeline` en dev con el arreglo → `salud` cierra el issue.
