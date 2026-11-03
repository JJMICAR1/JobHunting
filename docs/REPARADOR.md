# Agente reparador (Fase 5)

Tarea programada de Claude (cuenta del CEO), diaria a las 08:23 UTC, después del cron del pipeline (05:17)
y del workflow `salud` (tras el pipeline y a las 07:41). Cada ejecución empieza en una sesión nueva.

## Flujo
1. `pipeline` registra cada ejecución en la tabla `ejecuciones` (estado, ofertas, descartadas, total anunciado).
2. `salud` (`python -m jobhunting.salud`) evalúa y abre un issue por alerta con la etiqueta `alerta`:
   título `[alerta][prod|dev] <portal>: <tipo>`. Lo cierra solo cuando la alerta desaparece.
3. El reparador busca issues abiertos con la etiqueta `alerta`. **Si no hay ninguno, termina sin hacer nada.**

| Tipo | Significado | Qué hace el reparador |
|------|-------------|------------------------|
| `error` | excepción o `ParserRoto` | Reproducir con fixture y arreglar el parser. |
| `cero` | ok pero 0 ofertas | Selector de tarjetas/listado cambiado: arreglar el parser. |
| `descartes` | >10 % de tarjetas descartadas | Un campo (título, id, url...) ha cambiado: arreglar el parser. |
| `incompleto` | <80 % del total anunciado | Paginación rota: arreglar el scraper. |
| `caida` | <50 % de la mediana reciente | Investigar; si es el mercado real, comentar y no tocar código. |
| `bloqueado` | 403/429/captcha/robots | **No arreglar**: comentar en el issue y avisar al CEO (regla 7). |
| `sin_ejecucion` | el cron no corrió en >28 h | **No tocar workflows**: comentar en el issue (posible facturación o cron apagado). |

## Reglas del reparador
- Lee `CLAUDE.md` y `docs/ESTADO.md`. Trabaja solo en una rama `claude/reparar-<portal>-<tipo>`.
  Nunca toca `main`, secretos, Neon prod ni workflows de cron. Nunca hace merge.
- Si ya hay un PR abierto que enlaza el issue, no abre otro (idempotencia).
- No puede descargar de los portales desde la nube: para ver el HTML/XML nuevo, ejecuta en Actions el workflow
  `fixture` (Tecnoempleo) o `diagnostico` (Feina Activa) en su rama, y descarga el artefacto.
- Arreglo mínimo: fixture nuevo en `tests/fixtures/`, test que falla antes y pasa después, `python3 -m pytest` en verde.
- Abre un PR que cierre el issue (`Closes #N`), con causa, cambio y prueba. El CEO revisa y fusiona.
- Al final comenta en el issue el enlace al PR. Máximo 10 líneas de resumen.

## Prompt de la tarea programada
> Eres el agente reparador de JobHunting. Sigue `docs/REPARADOR.md` del repo JJMICAR1/JobHunting (rama main).
> Lista los issues abiertos con la etiqueta `alerta`. Si no hay ninguno, responde "Sin alertas" y termina.
> Si los hay, atiende uno cada vez según la tabla de tipos, sin saltarte las reglas de CLAUDE.md,
> y abre un PR de arreglo por issue (nunca hagas merge).

## Simulacro (puerta de la Fase 5)
Con este código en `main`: en una rama `claude/simulacro-selector` se rompe a propósito el selector de tarjetas
de Tecnoempleo y se ejecuta `pipeline` en Neon dev → `salud` abre `[alerta][dev] tecnoempleo: cero` →
el reparador abre el PR de arreglo → el CEO lo revisa. Al volver a ejecutar en dev con el arreglo, el issue se cierra solo.
