"""Regresion: robots.txt con redirecciones en la sonda (servidor local 127.0.0.1, sin red externa)."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from tests.test_sonda import sonda

PERMITE = b"User-agent: *\nDisallow:\n"


def _servidor(rutas, peticiones):
    """rutas: path -> (status, headers dict, body bytes). Otro path -> 200 html."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            peticiones.append(self.path)
            st, hd, body = rutas.get(self.path, (200, {"Content-Type": "text/html"},
                                                 b"<html><title>ok</title></html>"))
            self.send_response(st)
            for k, v in hd.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def mk(monkeypatch):
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setattr(sonda, "PAUSA_ROBOTS_S", 0)
    servidores = []

    def fabrica(rutas):
        pet = []
        srv = _servidor(rutas, pet)
        servidores.append(srv)
        return f"http://127.0.0.1:{srv.server_port}", pet

    yield fabrica
    for s in servidores:
        s.shutdown()
        s.server_close()


def _redir(destino, code=302):
    return (code, {"Location": destino}, b"")


# ---- robots.txt no resuelto -> None (nunca True) ----
def test_robots_redirige_en_bucle_da_none(mk):
    base, pet = mk({"/robots.txt": _redir("/robots.txt")})
    assert sonda.robots_permitido(base + "/p") is None


def test_robots_3xx_sin_location_da_none(mk):
    base, pet = mk({"/robots.txt": (302, {}, b"")})
    assert sonda.robots_permitido(base + "/p") is None


def test_robots_cadena_de_mas_de_5_saltos_da_none(mk):
    rutas = {"/robots.txt": _redir("/r1")}
    for i in range(1, 9):
        rutas[f"/r{i}"] = _redir(f"/r{i + 1}")
    base, pet = mk(rutas)
    assert sonda.robots_permitido(base + "/p") is None
    assert len(pet) <= 7  # 1 + 5 saltos como maximo (+1 de margen)


def test_sondear_con_robots_3xx_sin_resolver_no_pide_la_url(mk):
    base, pet = mk({"/robots.txt": _redir("/robots.txt")})
    reg = sonda.sondear({"portal": "L", "url": base + "/p"})
    assert reg["robots_ok"] is None
    assert "robots_no_leido" in reg["senales"] and reg["estado"] == "error"
    assert "/p" not in pet


def test_robots_5xx_da_none_y_4xx_da_true(mk):
    base, _ = mk({"/robots.txt": (503, {}, b"")})
    assert sonda.robots_permitido(base + "/p") is None
    base, _ = mk({"/robots.txt": (404, {}, b"")})
    assert sonda.robots_permitido(base + "/p") is True


# ---- robots.txt redirigido a otro robots.txt valido ----
def test_robots_redirigido_una_vez_se_respeta_prohibe(mk):
    base, pet = mk({"/robots.txt": _redir("/otro-robots.txt"),
                    "/otro-robots.txt": (200, {}, b"User-agent: *\nDisallow: /p\n")})
    assert sonda.robots_permitido(base + "/p") is False
    assert sonda.robots_permitido(base + "/libre") is True
    reg = sonda.sondear({"portal": "L", "url": base + "/p"})
    assert reg["estado"] == "prohibido_robots"
    assert "/p" not in pet


def test_robots_redirigido_una_vez_permite(mk):
    base, pet = mk({"/robots.txt": _redir("/otro-robots.txt", 301),
                    "/otro-robots.txt": (200, {}, PERMITE)})
    reg = sonda.sondear({"portal": "L", "url": base + "/p"})
    assert reg["robots_ok"] is True and reg["http_status"] == 200
    assert "redirect" not in reg["senales"]


# ---- el bloqueo no contamina la siguiente llamada ----
def test_bloqueo_no_contamina_segunda_llamada(mk):
    base, pet = mk({"/robots.txt": (200, {}, b"User-agent: *\nDisallow: /destino\n"),
                    "/origen": _redir("/destino")})
    r1 = sonda.sondear({"portal": "L", "url": base + "/origen"})
    assert r1["estado"] == "prohibido_robots"
    assert "redirect_prohibido_robots" in r1["senales"]
    r2 = sonda.sondear({"portal": "L", "url": base + "/normal"})
    assert r2["http_status"] == 200
    assert "redirect" not in r2["senales"]
    assert not any(s.startswith("redirect_") for s in r2["senales"])
    assert r2["estado"] != "prohibido_robots"
    assert "/destino" not in pet


def test_condicion_bloqueo_no_contamina_segunda_llamada(mk):
    base, pet = mk({"/robots.txt": (200, {}, b"User-agent: *\nDisallow: /destino\n"),
                    "/origen": _redir("/destino")})
    assert "redirect_prohibido_robots" in sonda.condicion({"nombre": "X", "url": base + "/origen"})
    out = sonda.condicion({"nombre": "X", "url": base + "/normal"})
    assert "(200)" in out and "redirect_" not in out


# ---- robots del destino de un redirect que redirige a otro robots.txt permitido ----
def test_redirect_con_robots_destino_redirigido_y_permitido(mk):
    dest, pet_d = mk({"/robots.txt": _redir("/robots2.txt"),
                      "/robots2.txt": (200, {}, PERMITE)})
    orig, pet_o = mk({"/robots.txt": (200, {}, PERMITE),
                      "/origen": _redir(dest + "/destino")})
    reg = sonda.sondear({"portal": "L", "url": orig + "/origen"})
    assert reg["http_status"] == 200
    assert reg["url_final"] == dest + "/destino"
    assert "redirect" in reg["senales"]
    assert "redirect_prohibido_robots" not in reg["senales"]
    assert "redirect_robots_no_leido" not in reg["senales"]
    assert reg["estado"] not in ("prohibido_robots", "error")
    assert "/destino" in pet_d


def test_redirect_con_robots_destino_redirigido_y_prohibido(mk):
    dest, pet_d = mk({"/robots.txt": _redir("/robots2.txt"),
                      "/robots2.txt": (200, {}, b"User-agent: *\nDisallow: /destino\n")})
    orig, _ = mk({"/robots.txt": (200, {}, PERMITE), "/origen": _redir(dest + "/destino")})
    reg = sonda.sondear({"portal": "L", "url": orig + "/origen"})
    assert reg["estado"] == "prohibido_robots"
    assert "/destino" not in pet_d
