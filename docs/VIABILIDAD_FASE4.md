# Fase 4 — Viabilidad de fuentes nuevas

Sonda: `scripts/sonda_portales.py --grupo fase4` y `--grupo condiciones` (workflow `sonda`).
Ejecución: 2026-11-03 10:47 UTC, runner `ubuntu-latest` (IP de centro de datos de GitHub).
Un GET por URL tras robots.txt, sin login, cookies ni reintentos, pausa de 5 s.

## 1. APIs oficiales (condiciones leídas desde Actions)

| API | Condiciones | Veredicto |
|---|---|---|
| InfoJobs | Prohíbe expresamente "aplicaciones que sean agregadores de ofertas" y "usar los datos para crear otro portal de empleo". Solo deja una caché temporal. | **No viable** sin un acuerdo escrito con InfoJobs |
| Jooble | El plan gratuito tiene **500 peticiones en total por clave, de por vida** (no son mensuales), y hay una clave por país. | **No viable** para uso diario |
| Adzuna | Gratis para "búsqueda personal de empleo" e investigación personal, con atribución. El plan gratis es "para evaluar", con límites en la cuenta. Un uso comercial exige licencia. | **Posible** (uso personal). Requiere el OK del CEO: servicio y secreto nuevos |
| Careerjet | robots.txt no se pudo leer desde Actions | Sin datos |

## 2. Datos abiertos y feeds

| Fuente | Resultado | Evidencia | Veredicto |
|---|---|---|---|
| **Feina Activa XML** (Generalitat, `feinaactiva.gencat.cat/api/offers/offers-xml`) | 200, más de 5 MB (cortado al tope) | Ficha en datos.gob.es: ofertas de Catalunya, se actualiza a diario, licencia de datos abiertos de la Generalitat | **Mejor candidata.** Falta leer el XML entero para ver su esquema |
| Feina Activa Socrata (`32kr-h32h`) | Los datos dan 403 y los metadatos 200 | La ficha no se actualiza desde 16/09/2026 | Usar el XML directo |
| Greenhouse (API pública de empleo de empresas) | 200 JSON para `typeform`; 404 para `glovo` | Campos: title, location, absolute_url, updated_at… | **Viable** por empresa. Hace falta una lista de empresas con su slug |
| Lever / Ashby (wallapop, factorial) | 404 | El slug no existe | Viable si se dan slugs correctos |
| SmartRecruiters | Prohibido por robots.txt | — | Descartar |
| Arbeitnow, Remotive | 200 JSON | Casi todo fuera de España o en remoto | Bajo valor para Catalunya |

## 3. Portales HTML

| Portal | Resultado | Evidencia | Veredicto |
|---|---|---|---|
| Infoempleo | **Funciona** | 200, 312 KB, "Ofertas de trabajo en Barcelona", 67 × "oferta" | Candidato |
| Ticjob (IT) | **Funciona** | 200, 764 KB | Candidato |
| Jobfluent (tech BCN) | **Funciona** | 200, 99 KB, 34 × "oferta" | Candidato |
| Talent.com | **Funciona** | 200, 462 KB, 239 × "oferta" | Es un agregador. Revisar sus condiciones antes de usarlo |
| Welcome to the Jungle | Responde, sin ofertas en el HTML | 0 × "oferta" | Necesita JS. Descartar por ahora |
| EURES | Responde, sin ofertas en el HTML | 0 × "oferta" | Necesita JS. Descartar por ahora |
| Feina Activa web | Funciona | 2 MB | Mejor usar el XML abierto |
| Indeed | **Bloqueado** | 403 "Security Check", captcha | Descartar (regla 7) |
| SEPE Empléate | robots.txt no leído | — | Sin datos |
| Barcelona Activa | 404 | La URL de la sonda es incorrecta | Repetir con otra URL |

Antes de construir cada portal HTML hay que leer su aviso legal. La sonda solo comprueba
robots.txt.
