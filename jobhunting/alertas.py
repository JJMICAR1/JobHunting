"""Alertas como issues de GitHub (gratis, sin servicios nuevos). Idempotente.

- Una alerta abierta = un issue abierto con la etiqueta `alerta` y el título
  `[alerta][<entorno>] <portal>: <tipo>`. Si ya existe, no se toca (no se duplica ni se comenta).
- Los issues abiertos de ese entorno cuya alerta ya no está se comentan y se cierran solos.
- La red entra por `http(metodo, ruta, cuerpo) -> (status, json)`; por defecto la API REST con
  GITHUB_TOKEN y GITHUB_REPOSITORY. El token nunca se imprime.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

ETIQUETA = "alerta"
COLORES = {ETIQUETA: "d73a4a", "entorno:prod": "b60205", "entorno:dev": "fbca04"}
API = "https://api.github.com"


def prefijo(entorno: str) -> str:
    return f"[alerta][{entorno}] "


def titulo(alerta, entorno: str) -> str:
    return prefijo(entorno) + alerta.clave


def _enlace_ejecucion() -> str:
    srv, repo, run = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"{srv}/{repo}/actions/runs/{run}" if srv and repo and run else "-"


def cuerpo(alerta, entorno: str) -> str:
    return (f"**Portal:** `{alerta.portal}`  \n**Tipo:** `{alerta.tipo}`  \n**Entorno:** `{entorno}`\n\n"
            f"{alerta.mensaje}\n\n"
            f"Detectado por el workflow `salud`: {_enlace_ejecucion()}\n\n"
            "El agente reparador lo atiende según `docs/REPARADOR.md` (rama `claude/`, PR para el CEO). "
            "Este issue se cierra solo cuando la alerta desaparece.\n")


def http_github(metodo: str, ruta: str, datos=None):
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise RuntimeError("faltan GITHUB_TOKEN o GITHUB_REPOSITORY")
    req = urllib.request.Request(
        f"{API}/repos/{repo}{ruta}", method=metodo,
        data=json.dumps(datos).encode() if datos is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "jobhunting-salud"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


def _ok(status, que):
    if not 200 <= status < 300:
        raise RuntimeError(f"API de GitHub: {que} devolvió {status}")


def _asegurar_etiquetas(http, entorno):
    for nombre in (ETIQUETA, f"entorno:{entorno}"):
        st, _ = http("POST", "/labels", {"name": nombre, "color": COLORES.get(nombre, "ededed")})
        if st not in (201, 422):  # 422 = ya existe
            _ok(st, f"crear etiqueta {nombre}")


def abiertos(http, entorno: str) -> dict[str, int]:
    """{título: número} de los issues abiertos con la etiqueta `alerta` de ese entorno."""
    res, pagina = {}, 1
    while True:
        st, datos = http("GET", f"/issues?state=open&labels={ETIQUETA}&per_page=100&page={pagina}")
        _ok(st, "listar issues")
        for i in datos or []:
            if "pull_request" not in i and i.get("title", "").startswith(prefijo(entorno)):
                res[i["title"]] = i["number"]
        if not datos or len(datos) < 100:
            return res
        pagina += 1


def sincronizar(alertas, entorno: str, http=None) -> dict[str, int]:
    http = http or http_github
    actuales = {titulo(a, entorno): a for a in alertas}
    existentes = abiertos(http, entorno)
    cambios = {"abiertos": 0, "cerrados": 0, "sin_cambios": 0}
    nuevas = [t for t in actuales if t not in existentes]
    if nuevas:
        _asegurar_etiquetas(http, entorno)
    for t in nuevas:
        st, _ = http("POST", "/issues", {"title": t, "body": cuerpo(actuales[t], entorno),
                                        "labels": [ETIQUETA, f"entorno:{entorno}"]})
        _ok(st, "crear issue")
        cambios["abiertos"] += 1
    for t, num in existentes.items():
        if t in actuales:
            cambios["sin_cambios"] += 1
            continue
        st, _ = http("POST", f"/issues/{num}/comments",
                     {"body": f"La alerta ya no aparece (workflow `salud`: {_enlace_ejecucion()}). Se cierra."})
        _ok(st, "comentar issue")
        st, _ = http("PATCH", f"/issues/{num}", {"state": "closed", "state_reason": "completed"})
        _ok(st, "cerrar issue")
        cambios["cerrados"] += 1
    return cambios
