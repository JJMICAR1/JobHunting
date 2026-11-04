# Fase 7 — Reglas y etiquetado Sí/No (diseño)

Decisiones del CEO (2026-11-04):
- El bot vive en **GitHub Actions**: un workflow cada hora recoge los clics y comandos (`getUpdates`) y, una vez al día,
  envía un lote de ofertas con botones Sí/No. No hay servicios nuevos.
- Los criterios se escriben **con comandos de Telegram** y se guardan en Neon (tabla `config`). **Nunca en el repo.**
- Muestreo **70/30**: de cada lote, 70 % las de mejor nota según las reglas y 30 % al azar.
- Puerta: **100 etiquetas** en prod.

## Datos (migración 006, idempotente, con su `.down.sql`)
- `config (clave text PK, valor jsonb NOT NULL, actualizado timestamptz NOT NULL)`.
  Claves: `reglas` (ver abajo), `telegram_offset` (número, solo prod), `lote` (número, por defecto 10).
- `envios_etiquetado (id bigint identity PK, portal, id_portal, enviado timestamptz, muestra text CHECK IN ('reglas','azar'),
  nota real, message_id bigint NULL, UNIQUE (portal, id_portal), FK a ofertas ON DELETE CASCADE)`.
  Una oferta se envía como mucho una vez.
- `etiquetas (portal, id_portal, etiqueta boolean NOT NULL, etiquetada timestamptz NOT NULL, envio_id bigint REFERENCES
  envios_etiquetado, PK (portal, id_portal), FK a ofertas ON DELETE CASCADE)`. Si se pulsa otra vez, gana el último clic (upsert).
- Ni token ni chat_id en la BD.

## Reglas (`jobhunting/reglas.py`, puro, sin BD ni red)
Formato de `config.reglas`: `{"si": [...], "no": [...], "ciudades": [...], "modalidades": [...]}` (listas sin repetidos).
Se compara el texto normalizado (minúsculas, sin tildes, por palabra o frase completa, no subcadena).
- `si`: +1 por cada término que aparece en el título.
- `no`: −3 por cada término que aparece en el título o en la empresa.
- `ciudades`: +0,5 si la ciudad de la oferta está en la lista (si la lista está vacía, no suma).
- `modalidades` (presencial/hibrido/remoto): +0,5 si coincide (si la lista está vacía, no suma).
`puntuar(...)` devuelve la nota y los motivos (p. ej. `["python", "Barcelona"]`).

Comandos (solo desde el chat `TELEGRAM_CHAT_ID`; los demás se ignoran):
`/si <término>`, `/no <término>`, `/quitar <término>` (lo quita de si/no/ciudades),
`/ciudad <nombre>`, `/modalidad presencial|hibrido|remoto`, `/lote <1-30>`, `/ver` (reglas y progreso: N/100, Sí, No),
`/ayuda`. Son idempotentes (son conjuntos). Un término tiene como mucho 60 caracteres y una lista, como mucho 200 términos.

## Reglas aprendidas (el bot las deduce de tus Sí/No)
No hace falta escribir criterios: el bot aprende de las etiquetas (`reglas.aprender`, puro y determinista).
- Con menos de 10 etiquetas no aprende nada (devuelve reglas vacías).
- Términos: palabras normalizadas del título (3+ caracteres, sin stopwords es/ca como de, la, per, amb) y bigramas contiguos.
- Para cada término con al menos 3 etiquetas: tasa suavizada `(si+1)/(n+2)`. Va a `si` si tasa >= 0,7 y a `no` si <= 0,2.
  Ciudades y modalidades: solo a la lista positiva (tasa >= 0,7).
- Máximo 30 términos por lista, primero los de más evidencia (n mayor; empate, orden alfabético).
- Se recalculan antes de enviar el lote y con `/ver`, y se guardan en `config.reglas_auto` (solo prod y sin `--dry-run`).
- La nota usa manuales + aprendidas, pero **lo manual manda**: un término puesto a mano en `no` no puede estar en `si` aprendido, y al revés.
- `/olvidar <término>` lo mete en `ignorar` (dentro de `config.reglas`): el aprendizaje no lo usa nunca. `/quitar` lo saca de ahí.
- `/ver` muestra tus reglas manuales, lo aprendido aparte («Aprendido de tus Sí/No») y el progreso.
- El lote abre con un mensaje corto: «Lote de hoy: 7 por lo que he aprendido de ti, 3 al azar» y los 5 términos principales,
  o «Aún aprendo: llevas N/10 etiquetas para empezar a puntuar». No se repite si se reanuda un lote cortado.

## Bot (`jobhunting/etiquetado.py`, `python -m jobhunting.etiquetado --entorno prod|dev [--dry-run]`)
1. **Recoger**: `getUpdates` (`timeout=0`, `allowed_updates=["message","callback_query"]`).
   - En prod se envía `offset` = `config.telegram_offset` y, al terminar, se guarda el último `update_id + 1`.
   - En dev **no** se envía `offset` ni se confirma nada (solo mira): así dev no se come los clics de prod.
   - Callback `"<p|d>:<s|n>:<envio_id>"`: solo se procesa si el prefijo coincide con el entorno. Se guarda la etiqueta,
     se responde con `answerCallbackQuery` y se edita el mensaje para mostrar «Sí ✅» o «No ❌».
   - Los comandos solo se aplican en prod (en dev se ignoran).
   - Volver a procesar el mismo update deja el mismo estado.
   - Como prod confirma todos los updates, un clic en un mensaje de dev (`d:`) se pierde si prod corre antes que dev.
     Es aceptable: dev solo sirve para probar.
   - Si `config.reglas` tiene un formato no válido, el comando responde con un aviso y se da por consumido
     (un update que siempre falla no bloquea el offset).
2. **Enviar el lote**: una vez al día (tabla `avisos`, tipo `etiquetado`), solo si hay ofertas vistas hoy (`ultima_vez` de hoy, UTC).
   Candidatas: vistas hoy y no enviadas nunca. `round(lote*0,7)` las de mejor nota (empate: más reciente primero) y el resto
   al azar entre las demás (`random.Random(dia)`: el mismo día da el mismo lote). Si no hay reglas, todas van al azar.
   Un mensaje por oferta, en texto plano: título, empresa, ciudad · modalidad, nota y motivos, `[azar]` si toca, url;
   y botones Sí / No.
3. Nunca se imprimen el token, el chat_id ni `DATABASE_URL`. Los errores de red no muestran la URL.
   Ante 429 de Telegram, se para (sin reintentos).

## Workflow `.github/workflows/etiquetado.yml`
`schedule` a los 37 min de cada hora (prod, solo desde main), `workflow_dispatch` (dev/prod) y push en `claude/**` del propio yml (dev).
`permissions: contents: read`; `concurrency` por entorno; `timeout-minutes: 5`.
