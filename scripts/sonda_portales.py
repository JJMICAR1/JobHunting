"""Sonda de viabilidad (Fase 2): ¿responde cada portal para búsquedas en Catalunya?

Una petición GET por portal, sin login ni cookies, respetando robots.txt.
No guarda el cuerpo HTML. Sale siempre con código 0 (es un informe).
"""
import json
import re
import os
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

USER_AGENT = "JobHuntingSonda/0.1 (+https://github.com/JJMICAR1/JobHunting)"
TIMEOUT = 20
PAUSA_S = 5
PAUSA_ROBOTS_S = 2  # entre robots.txt y la búsqueda del mismo host

# Config: nombre, URL de búsqueda pública, palabras esperadas en un HTML de ofertas.
PORTALES = [
    {"portal": "Jooble", "url": "https://es.jooble.org/trabajo-empleo/Barcelona",
     "esperadas": ["jooble", "oferta", "empleo", "trabajo"]},
    {"portal": "InfoJobs", "url": "https://www.infojobs.net/ofertas-trabajo/barcelona",
     "esperadas": ["infojobs", "oferta", "empleo", "trabajo"]},
    {"portal": "Tecnoempleo", "url": "https://www.tecnoempleo.com/ofertas-trabajo/?provincia=9",
     "esperadas": ["tecnoempleo", "oferta", "empleo", "trabajo"]},
    {"portal": "LinkedIn", "url": "https://www.linkedin.com/jobs/search/?location=Barcelona",
     "esperadas": ["linkedin", "job", "empleo", "trabajo"]},
    {"portal": "Glassdoor", "url": "https://www.glassdoor.es/Empleo/barcelona-empleo-SRCH_IL.0,9_IC2677052.htm",
     "esperadas": ["glassdoor", "empleo", "oferta", "trabajo"]},
]

from jobhunting.bloqueo import (  # noqa: E402
    ESPERADAS_GENERICAS, MARCAS_BLOQUEO, MARCAS_LOGIN, MAX_BYTES_BLOQUEO, STATUS_BLOQUEO,
    clasificar,
)


def resumen_html(html):
    """Datos no personales para revisar a mano: título y recuentos de palabras."""
    bajo = (html or "").lower()
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    titulo = " ".join(m.group(1).split())[:80] if m else ""
    return {"titulo": titulo.replace("|", "/"),
            "n_oferta": bajo.count("oferta"), "n_empleo": bajo.count("empleo"),
            "n_just_a_moment": bajo.count("just a moment")}


def robots_permitido(url):
    p = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as e:
        # robots.txt 4xx = sin restricciones publicadas; 5xx = no concluyente
        return True if e.code < 500 else None
    except Exception:
        return None  # no se pudo leer
    return rp.can_fetch(USER_AGENT, url)


def sondear(cfg):
    url = cfg["url"]
    reg = {"portal": cfg["portal"], "url": url, "robots_ok": None, "http_status": None,
           "url_final": None, "bytes": 0, "ms": 0, "senales": [], "estado": "error",
           "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ok = robots_permitido(url)
    reg["robots_ok"] = ok
    if ok is False:
        reg["estado"] = "prohibido_robots"
        return reg
    if ok is None:
        reg["senales"].append("robots_no_leido")
        reg["estado"] = "error"
        return reg
    time.sleep(PAUSA_ROBOTS_S)
    t0 = time.monotonic()
    html = ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            reg["http_status"] = r.status
            reg["url_final"] = r.geturl()
            body = r.read()
            reg["bytes"] = len(body)
            html = body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # sin reintentos
        reg["http_status"] = e.code
        reg["url_final"] = e.geturl()
        try:
            body = e.read()
            reg["bytes"] = len(body)
            html = body.decode("utf-8", "replace")
        except Exception:
            pass
    except Exception as e:
        reg["senales"].append(f"excepcion:{type(e).__name__}")
        reg["ms"] = int((time.monotonic() - t0) * 1000)
        return reg
    reg["ms"] = int((time.monotonic() - t0) * 1000)
    if reg["url_final"] and reg["url_final"] != url:
        reg["senales"].append("redirect")
        if robots_permitido(reg["url_final"]) is False:
            reg["senales"].append("redirect_prohibido_robots")
            reg["estado"] = "prohibido_robots"
            return reg
    reg.update(resumen_html(html))
    estado, senales = clasificar(reg["http_status"], reg["url_final"], html,
                                 cfg.get("esperadas"))
    reg["estado"] = estado
    reg["senales"] += senales
    return reg


def tabla_md(regs):
    filas = ["| Portal | Estado | HTTP | robots | bytes | ms | Señales | Título | n_oferta |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in regs:
        filas.append(f"| {r['portal']} | {r['estado']} | {r['http_status']} | {r['robots_ok']} "
                     f"| {r['bytes']} | {r['ms']} | {', '.join(r['senales'])} "
                     f"| {r.get('titulo', '')} | {r.get('n_oferta', '')} |")
    return "\n".join(filas) + "\n"


def main():
    regs = []
    for i, cfg in enumerate(PORTALES):
        if i:
            time.sleep(PAUSA_S)
        try:
            regs.append(sondear(cfg))
        except Exception as e:  # nunca romper el informe
            regs.append({"portal": cfg["portal"], "url": cfg["url"], "robots_ok": None,
                         "http_status": None, "url_final": None, "bytes": 0, "ms": 0,
                         "senales": [f"excepcion:{type(e).__name__}"], "estado": "error",
                         "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    with open("sonda.json", "w", encoding="utf-8") as f:
        json.dump(regs, f, ensure_ascii=False, indent=2)
    tabla = tabla_md(regs)
    print(tabla)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write("## Sonda de portales\n\n" + tabla)
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
