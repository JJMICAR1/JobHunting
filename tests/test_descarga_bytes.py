"""descargar_bytes: con _abrir falso y con un servidor local en 127.0.0.1 (sin red externa)."""
import http.server
import io
import threading
import urllib.error

import pytest

from jobhunting import descarga
from jobhunting.descarga import Bloqueado, ErrorDescarga, USER_AGENT, descargar, descargar_bytes

URL = "https://feinaactiva.gencat.cat/api/offers/offers-xml"
XML = b"<?xml version='1.0'?><ofertes>" + b"<g><ad><id>A</id></ad></g>" * 10 + b"</ofertes>"


class Resp:
    def __init__(self, cuerpo, status=200, url=URL):
        self.buf, self.status, self._u = io.BytesIO(cuerpo), status, url
        self.pedidos = []

    def read(self, n=-1):
        self.pedidos.append(n)
        return self.buf.read(n)

    def geturl(self):
        return self._u

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Red:
    def __init__(self, status=200, cuerpo=XML, robots="User-agent: *\nAllow: /\n", final=None):
        self.status, self.cuerpo, self.robots, self.final = status, cuerpo, robots, final
        self.llamadas, self.resp = [], None

    def __call__(self, req, timeout=None):
        self.llamadas.append((req, timeout))
        if req.full_url.endswith("/robots.txt"):
            if isinstance(self.robots, Exception):
                raise self.robots
            return Resp(self.robots.encode(), url=req.full_url)
        if self.status != 200:
            raise urllib.error.HTTPError(req.full_url, self.status, "x", {}, io.BytesIO(self.cuerpo))
        self.resp = Resp(self.cuerpo, url=self.final or req.full_url)
        return self.resp

    @property
    def paginas(self):
        return [r for r, _ in self.llamadas if not r.full_url.endswith("/robots.txt")]


@pytest.fixture
def red(monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})

    def instalar(**kw):
        r = Red(**kw)
        monkeypatch.setattr(descarga, "_abrir", r)
        return r
    return instalar


def test_devuelve_bytes_crudos(red):
    r = red()
    out = descargar_bytes(URL)
    assert isinstance(out, bytes) and out == XML
    assert len(r.paginas) == 1
    assert r.paginas[0].get_header("User-agent") == USER_AGENT
    assert r.paginas[0].get_header("Accept-encoding") is None   # no se pide gzip
    assert not r.paginas[0].has_header("Cookie") and not r.paginas[0].has_header("Authorization")


def test_timeout_largo_solo_en_la_pagina(red):
    r = red()
    descargar_bytes(URL)
    t = {q.full_url.rsplit("/", 1)[-1]: to for q, to in r.llamadas}
    assert t["robots.txt"] == descarga.TIMEOUT and t["offers-xml"] == descarga.TIMEOUT_BYTES


def test_tope_de_bytes_excedido(red):
    r = red(cuerpo=b"x" * 101)
    with pytest.raises(ErrorDescarga, match="tope"):
        descargar_bytes(URL, max_bytes=100)
    assert r.resp.pedidos == [101]   # nunca lee mas de max_bytes + 1


def test_tope_exacto_pasa(red):
    red(cuerpo=b"x" * 100)
    assert descargar_bytes(URL, max_bytes=100) == b"x" * 100


def test_tope_no_es_bloqueo(red):
    red(cuerpo=b"x" * 500)
    with pytest.raises(ErrorDescarga) as e:
        descargar_bytes(URL, max_bytes=10)
    assert not isinstance(e.value, Bloqueado)


def test_robots_prohibido_no_pide_la_pagina(red):
    r = red(robots="User-agent: *\nDisallow: /\n")
    with pytest.raises(Bloqueado):
        descargar_bytes(URL)
    assert r.paginas == []


def test_robots_403_es_bloqueo(red):
    err = urllib.error.HTTPError("https://feinaactiva.gencat.cat/robots.txt", 403, "x", {}, io.BytesIO(b""))
    r = red(robots=err)
    with pytest.raises(Bloqueado):
        descargar_bytes(URL)
    assert r.paginas == []


def test_robots_ilegible_es_error_no_bloqueo(red):
    red(robots=OSError("x"))
    with pytest.raises(ErrorDescarga) as e:
        descargar_bytes(URL)
    assert not isinstance(e.value, Bloqueado)


@pytest.mark.parametrize("status", [403, 429, 451, 503])
def test_status_de_bloqueo(red, status):
    r = red(status=status, cuerpo=b"")
    with pytest.raises(Bloqueado):
        descargar_bytes(URL)
    assert len(r.paginas) == 1   # sin reintentos


def test_500_es_error_de_descarga(red):
    red(status=500, cuerpo=b"")
    with pytest.raises(ErrorDescarga):
        descargar_bytes(URL)


def test_captcha_en_cuerpo_pequeno(red):
    red(cuerpo=b"<html>Please solve the CAPTCHA</html>")
    with pytest.raises(Bloqueado):
        descargar_bytes(URL)


def test_redireccion_a_otro_host_para(red):
    red(final="https://otro-host.test/offers.xml")
    with pytest.raises(Bloqueado, match="otro host"):
        descargar_bytes(URL)


def test_error_de_red_no_filtra_url(red, monkeypatch):
    def boom(req, timeout=None):
        if req.full_url.endswith("/robots.txt"):
            return Resp(b"")
        raise TimeoutError(req.full_url + "?token=SECRETO")
    monkeypatch.setattr(descarga, "_robots", {})
    monkeypatch.setattr(descarga, "_abrir", boom)
    with pytest.raises(ErrorDescarga) as e:
        descargar_bytes(URL)
    assert "SECRETO" not in str(e.value)


# ---- `descargar` (texto) sigue igual
def test_descargar_sigue_devolviendo_str(red):
    red(cuerpo=b"<html><body>" + b"ofertas " * 20 + b"</body></html>")
    out = descargar(URL)
    assert isinstance(out, str) and out.startswith("<html>")


def test_descargar_sigue_usando_timeout_normal(red):
    r = red()
    descargar(URL)
    assert {to for _, to in r.llamadas} == {descarga.TIMEOUT}


def test_descargar_sigue_parando_en_429(red):
    red(status=429, cuerpo=b"")
    with pytest.raises(Bloqueado):
        descargar(URL)


def test_descargar_no_tiene_tope_de_bytes_nuevo():
    import inspect
    assert list(inspect.signature(descargar).parameters) == ["url"]
    assert list(inspect.signature(descargar_bytes).parameters) == ["url", "max_bytes"]
    assert inspect.signature(descargar_bytes).parameters["max_bytes"].default == 50_000_000


# ---- servidor local real (127.0.0.1)
class _H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        rutas = self.server.rutas
        self.server.visitas.append(self.path)
        codigo, cab, cuerpo = rutas.get(self.path, (404, {}, b""))
        self.send_response(codigo)
        for k, v in cab.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


@pytest.fixture
def servidores():
    lista = []

    def nuevo(rutas):
        s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
        s.rutas, s.visitas = {"/robots.txt": (200, {}, b"User-agent: *\nAllow: /\n"), **rutas}, []
        threading.Thread(target=s.serve_forever, daemon=True).start()
        lista.append(s)
        return s
    yield nuevo
    for s in lista:
        s.shutdown()
        s.server_close()


def _base(s):
    return f"http://127.0.0.1:{s.server_address[1]}"


def test_local_ok_y_tope(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    s = servidores({"/x.xml": (200, {}, XML)})
    assert descargar_bytes(_base(s) + "/x.xml") == XML
    with pytest.raises(ErrorDescarga, match="tope"):
        descargar_bytes(_base(s) + "/x.xml", max_bytes=10)


@pytest.mark.parametrize("codigo", [403, 429])
def test_local_bloqueo(servidores, monkeypatch, codigo):
    monkeypatch.setattr(descarga, "_robots", {})
    s = servidores({"/x.xml": (codigo, {}, b"no")})
    with pytest.raises(Bloqueado):
        descargar_bytes(_base(s) + "/x.xml")
    assert s.visitas.count("/x.xml") == 1


def test_local_robots_prohibido(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    s = servidores({"/x.xml": (200, {}, XML), "/robots.txt": (200, {}, b"User-agent: *\nDisallow: /\n")})
    with pytest.raises(Bloqueado):
        descargar_bytes(_base(s) + "/x.xml")
    assert "/x.xml" not in s.visitas


def test_local_redireccion_a_otro_host(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    destino = servidores({"/robado.xml": (200, {}, XML)})
    origen = servidores({"/x.xml": (302, {"Location": _base(destino) + "/robado.xml"}, b"")})
    with pytest.raises(Bloqueado, match="otro host"):
        descargar_bytes(_base(origen) + "/x.xml")
    assert destino.visitas == []


def test_local_redireccion_no_deberia_visitar_otro_host(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    destino = servidores({"/robado.xml": (200, {}, XML)})
    origen = servidores({"/x.xml": (302, {"Location": _base(destino) + "/robado.xml"}, b"")})
    with pytest.raises(Bloqueado):
        descargar_bytes(_base(origen) + "/x.xml")
    assert destino.visitas == []


# ---- _Redireccion
def test_redireccion_mismo_host_prohibido_por_robots_no_hace_get(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    s = servidores({"/x.xml": (302, {"Location": "/privado.xml"}, b""), "/privado.xml": (200, {}, XML),
                    "/robots.txt": (200, {}, b"User-agent: *\nDisallow: /privado\n")})
    with pytest.raises(Bloqueado, match="robots"):
        descargar_bytes(_base(s) + "/x.xml")
    assert "/privado.xml" not in s.visitas


def test_redireccion_mismo_host_permitido_se_sigue(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    s = servidores({"/x.xml": (302, {"Location": "/y.xml"}, b""), "/y.xml": (200, {}, XML)})
    assert descargar_bytes(_base(s) + "/x.xml") == XML
    assert s.visitas.count("/y.xml") == 1


def test_redireccion_mas_de_3_saltos_es_error(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    rutas = {f"/r{i}": (302, {"Location": f"/r{i + 1}"}, b"") for i in range(10)}
    rutas["/r10"] = (200, {}, XML)
    s = servidores(rutas)
    with pytest.raises(ErrorDescarga):
        descargar_bytes(_base(s) + "/r0")
    assert "/r4" not in s.visitas


def test_redireccion_3_saltos_exactos_pasa(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    s = servidores({"/r0": (302, {"Location": "/r1"}, b""), "/r1": (302, {"Location": "/r2"}, b""),
                    "/r2": (302, {"Location": "/r3"}, b""), "/r3": (200, {}, XML)})
    assert descargar_bytes(_base(s) + "/r0") == XML


def test_robots_que_redirige_a_otro_host_es_bloqueo(servidores, monkeypatch):
    monkeypatch.setattr(descarga, "_robots", {})
    destino = servidores({"/robots.txt": (200, {}, b"User-agent: *\nAllow: /\n")})
    origen = servidores({"/x.xml": (200, {}, XML),
                         "/robots.txt": (301, {"Location": _base(destino) + "/robots.txt"}, b"")})
    with pytest.raises(Bloqueado):
        descargar_bytes(_base(origen) + "/x.xml")
    assert destino.visitas == [] and "/x.xml" not in origen.visitas
