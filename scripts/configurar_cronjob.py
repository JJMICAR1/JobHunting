"""Plan B del cron: crea (o actualiza) en cron-job.org las tareas que lanzan los workflows de prod.

GitHub no dispara los `schedule` de este repo, así que cron-job.org llama a la API de GitHub
(workflow_dispatch) a la hora fijada. Idempotente: busca cada tarea por título; si existe la
actualiza (PATCH) y si no la crea (PUT). Ejecutar dos veces deja el mismo estado.

Entorno: CRONJOB_API_KEY (clave de la API de cron-job.org) y GH_DISPATCH_TOKEN (token
fine-grained de GitHub, solo este repo, permiso Actions: read/write). Nunca se imprimen:
el log solo muestra títulos, ids y códigos HTTP (los logs del repo son públicos).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cron-job.org"
REPO = "JJMICAR1/JobHunting"
ZONA = "Europe/Madrid"
TIMEOUT = 20
POST = 1  # requestMethod de cron-job.org: 0 GET, 1 POST

# título -> (workflow, minutos, horas); -1 = todas.
TAREAS = {
    "jobhunting etiquetado prod": ("etiquetado.yml", [37], [-1]),
    "jobhunting pipeline prod": ("pipeline.yml", [17], [6]),
}


def job(titulo: str, workflow: str, minutos: list[int], horas: list[int], gh_token: str) -> dict:
    return {
        "title": titulo,
        "url": f"https://api.github.com/repos/{REPO}/actions/workflows/{workflow}/dispatches",
        "enabled": True,
        "saveResponses": False,
        "requestMethod": POST,
        "schedule": {"timezone": ZONA, "expiresAt": 0, "minutes": minutos, "hours": horas,
                     "mdays": [-1], "months": [-1], "wdays": [-1]},
        "extendedData": {
            "headers": {
                "Authorization": f"Bearer {gh_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
            "body": json.dumps({"ref": "main", "inputs": {"entorno": "prod"}}),
        },
    }


def http(metodo: str, ruta: str, clave: str, datos: dict | None = None):
    """-> (status, json). Los errores no incluyen la clave ni las cabeceras."""
    req = urllib.request.Request(
        API + ruta, method=metodo, data=json.dumps(datos).encode() if datos is not None else None,
        headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:
        raise RuntimeError(f"fallo de red con cron-job.org ({type(e).__name__})") from None


def configurar(clave: str, gh_token: str, llamar=http) -> int:
    st, resp = llamar("GET", "/jobs", clave)
    if st != 200 or not isinstance(resp, dict):
        print(f"Error: cron-job.org respondió {st} al listar tareas (¿API key correcta?)")
        return 1
    existentes = {j.get("title"): j.get("jobId") for j in resp.get("jobs") or []}
    fallos = 0
    for titulo, (wf, minutos, horas) in TAREAS.items():
        datos = {"job": job(titulo, wf, minutos, horas, gh_token)}
        try:
            if titulo in existentes:
                st, _ = llamar("PATCH", f"/jobs/{existentes[titulo]}", clave, datos)
                accion = f"actualizada (id {existentes[titulo]})"
            else:
                st, r = llamar("PUT", "/jobs", clave, datos)
                accion = f"creada (id {(r or {}).get('jobId')})"
        except RuntimeError as e:   # un fallo de red en una tarea no impide intentar la otra
            print(f"Error: {titulo}: {e}")
            fallos += 1
            continue
        if 200 <= st < 300:
            print(f"{titulo}: {accion}")
        else:
            print(f"Error: {titulo}: cron-job.org respondió {st}")
            fallos += 1
    return 1 if fallos else 0


def main() -> int:
    clave = (os.environ.get("CRONJOB_API_KEY") or "").strip()
    gh = (os.environ.get("GH_DISPATCH_TOKEN") or "").strip()
    if not clave or not gh:
        print("Faltan los secretos CRONJOB_API_KEY o GH_DISPATCH_TOKEN")
        return 1
    try:
        return configurar(clave, gh)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
