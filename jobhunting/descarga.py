"""Descarga educada: robots.txt, sin login/cookies, sin reintentos, parar ante bloqueo."""
from __future__ import annotations

import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse

from jobhunting.bloqueo import STATUS_BLOQUEO, clasificar

USER_AGENT = "JobHuntingBot/0.1 (+https://github.com/JJMICAR1/JobHunting)"
TIMEOUT = 20


class ErrorDescarga(Exception):
    pass


class Bloqueado(ErrorDescarga):
    """403/429/451/503, captcha, Cloudflare o robots.txt prohibido: hay que parar."""


_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _cargar_robots(origen: str):
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(origen + "/robots.txt", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as e:
        if e.code in STATUS_BLOQUEO or e.code >= 500:
            raise Bloqueado(f"robots.txt http_{e.code}")
        return None  # 4xx: sin restricciones publicadas
    except Exception as e:
        raise ErrorDescarga(f"robots.txt ilegible: {type(e).__name__}")
    return rp


def robots_permitido(url: str) -> bool:
    p = urlparse(url)
    origen = f"{p.scheme}://{p.netloc}"
    if origen not in _robots:
        _robots[origen] = _cargar_robots(origen)
    rp = _robots[origen]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def descargar(url: str) -> str:
    if not robots_permitido(url):
        raise Bloqueado("prohibido por robots.txt")
    status, html, final = None, "", url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            status, final = r.status, r.geturl()
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, final = e.code, e.geturl()
        try:
            html = e.read().decode("utf-8", "replace")
        except Exception:
            pass
    except Exception as e:
        raise ErrorDescarga(f"fallo de red: {type(e).__name__}")
    # esperadas=["x"] es irrelevante: solo nos interesa bloqueado/login/error HTTP
    estado, senales = clasificar(status, final, html, esperadas=[""])
    if estado == "bloqueado":
        raise Bloqueado(",".join(senales))
    if estado == "redirige_login":
        raise Bloqueado("redirige a login")
    if estado == "error":
        raise ErrorDescarga(",".join(senales))
    return html
