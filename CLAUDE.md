# JobHunting — reglas del proyecto

## Objetivo
Recoger ofertas de los portales grandes (Catalunya/España), contar el mercado por portal
y puntuar las ofertas según los Sí/No del CEO. Todo en la nube y casi gratis.

## Organigrama
- **CEO: Joan.** Decide, da las puertas ("Fase N OK"), aprueba gastos y cambios de reglas.
- **Jefe de equipo: la sesión principal de Claude Code.** Planifica, delega en subagentes,
  elige el modelo de cada delegación, integra resultados y hace los cambios en el repo
  (siempre en ramas `claude/` y por PR). Al acabar cada tarea informa al CEO en 10 líneas o menos.
- **Equipo: subagentes.** Los subagentes no crean otros subagentes: todo se encadena desde el jefe.

## Quién decide qué
- **El jefe decide solo:** dividir tareas, elegir agente y modelo (dentro de la política),
  escribir código, tests y docs, abrir PR, actualizar `docs/ESTADO.md`.
- **El jefe pide OK al CEO antes de:** pasar de fase; usar Opus o Fable; añadir una fuente o
  servicio nuevo; cualquier cosa que cueste dinero; tocar secretos, producción (Neon prod,
  workflows de cron) o ramas protegidas; cambiar este CLAUDE.md (propone el cambio y espera).
- **Prohibido siempre:** saltarse una puerta, hacer merge a `main` sin aprobación del CEO,
  commitear datos personales.
- **Continuidad:** cada sesión empieza de cero. El jefe lee `docs/ESTADO.md` al empezar
  (fase actual, decisiones, pendientes) y lo actualiza al terminar.

## Política de modelos
- Por defecto: **Sonnet 5.5, esfuerzo medio.**
- **Haiku:** documentación, formato, resumir logs, tareas triviales.
- **Opus 5.5 (pedir permiso):** plan de arquitectura de una fase, revisión de la Fase 8 (modelo),
  o un bug que tras 2 intentos no se logra aislar.
- **Fable:** no usar.
- Subagentes con `model: sonnet` salvo que se indique otra cosa. El jefe puede fijar el modelo
  en cada delegación.
- Plan Pro con tope de uso: máximo 2-3 subagentes a la vez y una fase por sesión.
  Avisar al CEO antes de lanzar una tarea larga.

## Reglas de oro
1. **Puertas por fase.** No se empieza la fase N+1 hasta que el CEO escriba "Fase N OK".
2. **Quien escribe no testea.** El constructor entrega; el tester prueba; luego el reviewer.
3. **Idempotencia.** Ejecutar dos veces la misma tarea da el mismo estado (sin duplicados).
4. **Parser y descarga separados.** Tests del parser con HTML guardado (tests/fixtures), sin red.
   Un único test de contrato en vivo por portal, marcado aparte.
5. **Fechas en UTC.** Deduplicar lo antes posible. Salida con campos validados.
6. **Repo PÚBLICO: nada personal.** Prohibido commitear CV, palabras clave, etiquetas Sí/No,
   credenciales o URLs con tokens. Config personal en Neon (tabla `config`) o GitHub Secrets.
7. **Respeto a los portales.** Sin login, ritmo bajo, parar ante captcha/bloqueo/403/429,
   respetar robots.txt. Nunca saltarse protecciones.
8. **Sin pagar.** Solo servicios gratuitos. Si algo exige pago, parar y avisar.

## Arquitectura
- Agentes (Claude Code web): construyen, testean y mantienen. NO ejecutan el scraping diario.
- Ejecución diaria: GitHub Actions (cron) con Python determinista. Cero uso de Claude.
- Base de datos: Neon free (0,5 GB). Ficha ligera por oferta; descripción solo de candidatas.
  Los agentes trabajan en la rama `dev` de Neon; producción solo la toca el pipeline.
- Reparación: alerta -> tarea programada de Claude (disparador API) -> abre PR -> el CEO revisa.
- Avisos y etiquetado: Telegram (dónde alojar el bot se decide en la Fase 7).

## Agentes (permisos mínimos; activar solo los de la fase)
- scraper-dev: escribe y arregla scrapers y parsers.
- tester: tests con fixtures, idempotencia, contrato de salida. Escribe solo en `tests/`.
- db-engineer: esquema, migraciones, retención de datos (límite 0,5 GB).
- ml-engineer: embeddings + regresión logística + muestreo por incertidumbre.
- devops: workflows de Actions, secretos, latido y alertas.
- reviewer: solo lectura (Read, Grep, Glob, Bash). Seguridad, secretos, robots.txt,
  que no se cuelen datos personales.

## Fases y puertas
0. Arranque: `CLAUDE.md` en la raíz de `main` (PR fusionado por el CEO).
   Puerta: el archivo se ve en `main` y una sesión nueva lo lee.
1. Fundación: `docs/ESTADO.md`, subagentes en `.claude/agents`, test de prueba.
   Neon (rama dev) y secretos se preparan antes de la Fase 3.
   Puerta: agentes listados y un test de prueba pasa en la nube.
2. Viabilidad: desde Actions, ¿responde cada portal en Catalunya?
   Puerta: tabla por portal (funciona / bloqueado / necesita proxy).
3. Esqueleto andante: una fuente -> Neon -> recuento diario.
   Puerta: tests de parser, idempotencia y comprobación manual del CEO.
4. Fuentes una a una (Jooble, InfoJobs, Tecnoempleo, LinkedIn, Glassdoor...), cada una con su puerta.
5. Salud y reparación: alertas, latido, agente reparador.
   Puerta: romper un selector a propósito -> alerta -> PR de arreglo.
6. Control de mercado: vistas SQL y recuento por Telegram.
7. Reglas + etiquetado Sí/No. Puerta: 100 etiquetas.
8. Modelo: embeddings + regresión logística. Puerta: mejora a las reglas en datos no vistos.
9. Resumen diario. Puerta: una semana de uso real.

## Notas
- Actions: el cron puede retrasarse y en repos públicos se desactiva tras 60 días sin actividad: latido.
- Los agentes en la nube solo alcanzan dominios permitidos: testear con fixtures; lo en vivo va en Actions.
