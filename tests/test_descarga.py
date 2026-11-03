import io
import urllib.error
import urllib.robotparser

import pytest

from jobhunting import descarga
from jobhunting.descarga import Bloqueado, ErrorDescarga, USER_AGENT, descargar

URL = "https://www.tecnoempleo.com/ofertas-trabajo/?pr=1"
HTML_OK = "<html><body>" + "ofertas de trabajo " * 10 + "</body></html>"


class Resp:
    def __init__(self, cuerpo, status=200, url=URL):
        self._c, self.status, self._u = cuerpo.encode(), status, url

    def read(self):
        return self._c

    def geturl(self):
        return self._u

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Red:
    """urlopen falso: registra peticiones; robots.txt aparte de la pagina."""

    def __init__(self, status=200, cuerpo=HTML_OK, robots="User-agent: *\nAllow: /\n"):
        self.status, self.cuerpo, self.robots = status, cuerpo, robots
        self.llamadas = []

    def __call__(self, req, timeout=None):
        self.llamadas.append(req)
        if req.full_url.endswith("/robots.txt"):
            if isinstance(self.robots, Exception):
                raise self.robots
            return Resp(self.robots, url=req.full_url)
        if self.status != 200:
            raise urllib.error.HTTPError(req.full_url, self.status, "x", {}, io.BytesIO(self.cuerpo.encode()))
        return Resp(self.cuerpo)

    @property
    def paginas(self):
        return [r for r in self.llamadas if not r.full_url.endswith("/robots.txt")]


@pytest.fixture
def red(monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})

    def instalar(**kw):
        r = Red(**kw)
        monkeypatch.setattr(descarga.urllib.request, "urlopen", r)
        return r
    return instalar


def test_ok_devuelve_html(red):
    r = red()
    assert descargar(URL) == HTML_OK
    assert len(r.paginas) == 1


def test_user_agent_correcto(red):
    r = red()
    descargar(URL)
    assert USER_AGENT.startswith("JobHuntingBot/")
    assert len(r.llamadas) == 2  # robots + pagina
    for req in r.llamadas:
        assert req.get_header("User-agent") == USER_AGENT


@pytest.mark.parametrize("status", [403, 429, 451, 503])
def test_status_de_bloqueo(red, status):
    r = red(status=status, cuerpo="")
    with pytest.raises(Bloqueado):
        descargar(URL)
    assert len(r.paginas) == 1  # sin reintentos


def test_captcha_en_pagina_pequena(red):
    r = red(cuerpo="<html>Please solve the CAPTCHA</html>")
    with pytest.raises(Bloqueado):
        descargar(URL)
    assert len(r.paginas) == 1


def test_marca_en_pagina_grande_no_bloquea(red):
    grande = HTML_OK + "<script src='/cdn-cgi/challenge-platform/x'></script>" + "a" * 60_000
    red(cuerpo=grande)
    assert descargar(URL) == grande


def test_robots_prohibe(red):
    r = red(robots="User-agent: *\nDisallow: /\n")
    with pytest.raises(Bloqueado):
        descargar(URL)
    assert r.paginas == []  # nunca se pidio la pagina


def test_robots_cacheado(red):
    r = red()
    descargar(URL)
    descargar(URL)
    assert len([x for x in r.llamadas if x.full_url.endswith("/robots.txt")]) == 1


def test_robots_403_es_bloqueo(red):
    # En Red, los errores de robots se lanzan como excepcion
    err = urllib.error.HTTPError("https://www.tecnoempleo.com/robots.txt", 403, "x", {}, io.BytesIO(b""))
    r = red(robots=err)
    with pytest.raises(Bloqueado):
        descargar(URL)
    assert r.paginas == []


def test_robots_404_sin_restricciones(red):
    err = urllib.error.HTTPError("https://www.tecnoempleo.com/robots.txt", 404, "x", {}, io.BytesIO(b""))
    red(robots=err)
    assert descargar(URL) == HTML_OK


def test_robots_ilegible_es_error_descarga(red):
    red(robots=OSError("boom"))
    with pytest.raises(ErrorDescarga):
        descargar(URL)


def test_fallo_de_red_sin_reintento(red):
    r = red()

    def falla(req, timeout=None):
        r.llamadas.append(req)
        if req.full_url.endswith("/robots.txt"):
            return Resp("User-agent: *\nAllow: /\n")
        raise TimeoutError("t")
    descarga.urllib.request.urlopen = falla  # monkeypatch ya restaurara el original
    with pytest.raises(ErrorDescarga):
        descargar(URL)
    assert len(r.paginas) == 1


def test_404_es_error_no_bloqueo(red):
    red(status=404, cuerpo="no")
    with pytest.raises(ErrorDescarga) as e:
        descargar(URL)
    assert not isinstance(e.value, Bloqueado)
