"""Descarga educada: robots.txt, sin login/cookies, sin reintentos, parar ante bloqueo."""
from __future__ import annotations

import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse

from jobhunting.bloqueo import STATUS_BLOQUEO, clasificar

USER_AGENT = "JobHuntingBot/0.1 (+https://github.com/JJMICAR1/JobHunting)"
TIMEOUT = 20
TIMEOUT_BYTES = 60   # descargas grandes (un XML de varios MB)


class ErrorDescarga(Exception):
    pass


class Bloqueado(ErrorDescarga):
    """403/429/451/503, captcha, Cloudflare o robots.txt prohibido: hay que parar."""


MAX_SALTOS = 3

_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


class _Redireccion(urllib.request.HTTPRedirectHandler):
    """Revisa cada salto ANTES de pedirlo: otro host -> parar; mismo host -> robots.txt."""

    max_redirections = MAX_SALTOS

    def __init__(self, comprobar_robots: bool = True):
        self.comprobar_robots = comprobar_robots

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).netloc != urlparse(req.full_url).netloc:
            raise Bloqueado("redireccion a otro host")
        if self.comprobar_robots and not robots_permitido(newurl):
            raise Bloqueado("redireccion prohibida por robots.txt")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _abrir(req, timeout=None):
    """Punto de inyeccion de la red (los tests lo sustituyen). Opener propio por llamada, sin cookies."""
    es_robots = urlparse(req.full_url).path == "/robots.txt"
    opener = urllib.request.build_opener(_Redireccion(comprobar_robots=not es_robots))
    return opener.open(req, timeout=timeout)


def _cargar_robots(origen: str):
    rp = urllib.robotparser.RobotFileParser()
    try:
        req = urllib.request.Request(origen + "/robots.txt", headers={"User-Agent": USER_AGENT})
        with _abrir(req, timeout=TIMEOUT) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as e:
        if e.code in STATUS_BLOQUEO or e.code >= 500:
            raise Bloqueado(f"robots.txt http_{e.code}")
        return None  # 4xx: sin restricciones publicadas
    except ErrorDescarga:
        raise
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


def crawl_delay(url: str) -> float:
    """Crawl-delay de robots.txt para nuestro agente (0 si no hay)."""
    p = urlparse(url)
    origen = f"{p.scheme}://{p.netloc}"
    if origen not in _robots:
        _robots[origen] = _cargar_robots(origen)
    rp = _robots[origen]
    d = rp.crawl_delay(USER_AGENT) if rp is not None else None
    return float(d or 0)


def _validar_respuesta(url: str, status, final: str, html: str) -> None:
    """Para (Bloqueado) ante redirección a otro host, robots o señales de bloqueo/login; ErrorDescarga si error."""
    if final and urlparse(final).netloc != urlparse(url).netloc:
        raise Bloqueado("redireccion a otro host")
    if final and final != url and not robots_permitido(final):
        raise Bloqueado("redireccion prohibida por robots.txt")
    # esperadas=["x"] es irrelevante: solo nos interesa bloqueado/login/error HTTP
    estado, senales = clasificar(status, final, html, esperadas=[""])
    if estado == "bloqueado":
        raise Bloqueado(",".join(senales))
    if estado == "redirige_login":
        raise Bloqueado("redirige a login")
    if estado == "error":
        raise ErrorDescarga(",".join(senales))


def descargar(url: str) -> str:
    if not robots_permitido(url):
        raise Bloqueado("prohibido por robots.txt")
    status, html, final = None, "", url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with _abrir(req, timeout=TIMEOUT) as r:
            status, final = r.status, r.geturl()
            html = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status, final = e.code, e.geturl()
        try:
            html = e.read().decode("utf-8", "replace")
        except Exception:
            pass
    except ErrorDescarga:
        raise
    except Exception as e:
        raise ErrorDescarga(f"fallo de red: {type(e).__name__}")
    _validar_respuesta(url, status, final, html)
    return html


def descargar_bytes(url: str, max_bytes: int = 50_000_000) -> bytes:
    """Como `descargar`, pero devuelve los bytes crudos (XML/JSON grandes) con un tope de tamaño.

    Una sola petición, sin reintentos, sin pedir gzip. Si el cuerpo supera `max_bytes` -> ErrorDescarga.
    """
    if not robots_permitido(url):
        raise Bloqueado("prohibido por robots.txt")
    status, cuerpo, final = None, b"", url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with _abrir(req, timeout=TIMEOUT_BYTES) as r:
            status, final = r.status, r.geturl()
            cuerpo = r.read(max_bytes + 1)
    except urllib.error.HTTPError as e:
        status, final = e.code, e.geturl()
        try:
            cuerpo = e.read(max_bytes + 1)
        except Exception:
            pass
    except ErrorDescarga:
        raise
    except Exception as e:
        raise ErrorDescarga(f"fallo de red: {type(e).__name__}")
    if len(cuerpo) > max_bytes:
        raise ErrorDescarga("supera el tope de bytes")
    # Solo el principio decide el bloqueo (las páginas de aviso son pequeñas).
    _validar_respuesta(url, status, final, cuerpo[:60_000].decode("utf-8", "replace"))
    return cuerpo
