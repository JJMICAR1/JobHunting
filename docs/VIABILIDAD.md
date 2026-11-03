# Fase 2 — Viabilidad de portales desde GitHub Actions

Sonda: `scripts/sonda_portales.py` (workflow `sonda`, solo a mano). Un GET por portal a la
búsqueda pública de Barcelona, tras comprobar robots.txt, sin login ni reintentos.
Ejecución: 2026-11-03 08:55 UTC, runner `ubuntu-latest` (IP de centro de datos de GitHub).

| Portal | Resultado | Evidencia | Siguiente paso posible |
|---|---|---|---|
| Tecnoempleo | **Funciona** | 200, 179 KB, título "1.760 Ofertas Trabajo en Informática…", 267 × "oferta" | Primera fuente para la Fase 3 |
| InfoJobs | **Bloqueado** (captcha) | 200 pero 30 KB, título genérico "InfoJobs", contiene captcha | API oficial gratuita de InfoJobs (requiere alta de desarrollador y secreto) |
| Jooble | **Bloqueado** (Cloudflare) | 403, "Just a moment...", challenge-platform | API oficial de Jooble (clave gratuita, requiere secreto) |
| Glassdoor | **Bloqueado** | 403, 9 bytes | Sin alternativa gratuita conocida; descartar por ahora |
| LinkedIn | **Prohibido por robots.txt** | robots.txt no permite `/jobs/search` a nuestro agente | Descartar el scraping (regla 7) |

Ninguno se marca "necesita proxy": saltar un bloqueo con proxies va contra la regla 7 y
suele costar dinero (regla 8). Las alternativas son APIs oficiales, y cada una necesita el OK del CEO.

Nota técnica: Cloudflare inyecta `challenge-platform` también en páginas normales. Desde la
2.ª ejecución, el clasificador solo cuenta las marcas de bloqueo en páginas < 50 KB o con
"Just a moment" (por eso Tecnoempleo salió "bloqueado" en el log y aquí figura como funciona).
