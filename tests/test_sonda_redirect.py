"""Tests de redirecciones seguras, saltos por host bloqueado y CLI de la sonda (sin red externa)."""
import json
import re
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tests.test_sonda import sonda

RAIZ = Path(__file__).resolve().parent.parent


def _req(url="http://a.test/x"):
    return urllib.request.Request(url)


# ---------- RedirectSeguro (unitario) ----------
def _redir(h, newurl, req=None):
    return h.redirect_request(req or _req(), None, 302, "Found", {}, newurl)


def test_redirect_permitido_sigue():
    h = sonda.RedirectSeguro(robots=lambda u: True)
    nuevo = _redir(h, "http://a.test/y")
    assert nuevo is not None and nuevo.full_url == "http://a.test/y"
    assert h.bloqueo is None


def test_redirect_prohibido_devuelve_none():
    h = sonda.RedirectSeguro(robots=lambda u: False)
    assert _redir(h, "http://a.test/y") is None
    assert h.bloqueo == "redirect_prohibido_robots"


def test_redirect_robots_no_leido():
    h = sonda.RedirectSeguro(robots=lambda u: None)
    assert _redir(h, "http://a.test/y") is None
    assert h.bloqueo == "redirect_robots_no_leido"


def test_redirect_relativa_con_urljoin():
    # robots recibe la URL ya resuelta (False evita llegar al super, que en uso real
    # recibe la URL ya absoluta desde http_error_302). El flujo completo va en el test del servidor.
    vistas = []
    h = sonda.RedirectSeguro(robots=lambda u: vistas.append(u) or False)
    assert _redir(h, "../otra?q=1", _req("http://a.test/d1/d2/x")) is None
    assert vistas == ["http://a.test/d1/otra?q=1"]


def test_redirect_a_robots_txt_no_se_recomprueba():
    h = sonda.RedirectSeguro(robots=lambda u: pytest.fail("no debe consultarse"))
    assert _redir(h, "http://a.test/robots.txt") is not None


def test_redirect_limite_saltos_declarado():
    assert sonda.RedirectSeguro.max_redirections == 3 == sonda.MAX_REDIRECTS


# ---------- servidor local 127.0.0.1 ----------
@pytest.fixture
def servidor(monkeypatch):
    peticiones = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            peticiones.append(self.path)
            if self.path.startswith("/salto"):
                n = int(self.path[6:] or 0)
                self.send_response(302)
                self.send_header("Location", f"/salto{n + 1}")
                self.end_headers()
            elif self.path == "/origen":
                self.send_response(302)
                self.send_header("Location", "/destino")  # relativa
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<html><title>ok</title></html>")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    monkeypatch.setenv("no_proxy", "127.0.0.1")
    monkeypatch.setattr(sonda, "PAUSA_ROBOTS_S", 0)
    base = f"http://127.0.0.1:{srv.server_port}"
    yield base, peticiones
    srv.shutdown()
    srv.server_close()


def _robots_solo(monkeypatch, prohibe=(), valor=True):
    """robots_permitido falso: False si la ruta esta en `prohibe`, `valor` en otro caso."""
    def f(url):
        return False if any(url.endswith(p) for p in prohibe) else valor
    monkeypatch.setattr(sonda, "robots_permitido", f)


def test_servidor_redirect_permitido_sigue(servidor, monkeypatch):
    base, pet = servidor
    _robots_solo(monkeypatch)
    reg = sonda.sondear({"portal": "L", "url": base + "/origen"})
    assert reg["http_status"] == 200
    assert reg["url_final"] == base + "/destino"
    assert "redirect" in reg["senales"]
    assert pet == ["/origen", "/destino"]


def test_sondear_redirect_prohibido_sin_get_al_destino(servidor, monkeypatch):
    base, pet = servidor
    _robots_solo(monkeypatch, prohibe=("/destino",))
    reg = sonda.sondear({"portal": "L", "url": base + "/origen"})
    assert reg["estado"] == "prohibido_robots"
    assert "redirect" in reg["senales"] and "redirect_prohibido_robots" in reg["senales"]
    assert pet == ["/origen"]  # nunca se pidio /destino


def test_sondear_redirect_robots_no_leido_es_error(servidor, monkeypatch):
    base, pet = servidor
    f = lambda u: True if u.endswith("/origen") else None  # noqa: E731
    monkeypatch.setattr(sonda, "robots_permitido", f)
    reg = sonda.sondear({"portal": "L", "url": base + "/origen"})
    assert reg["estado"] == "error"
    assert "redirect_robots_no_leido" in reg["senales"]
    assert pet == ["/origen"]


def test_condicion_redirect_prohibido_sin_get_al_destino(servidor, monkeypatch):
    base, pet = servidor
    _robots_solo(monkeypatch, prohibe=("/destino",))
    out = sonda.condicion({"nombre": "X", "url": base + "/origen"})
    assert "redirect_prohibido_robots" in out
    assert pet == ["/origen"]


def test_condicion_redirect_permitido(servidor, monkeypatch):
    base, pet = servidor
    _robots_solo(monkeypatch)
    out = sonda.condicion({"nombre": "X", "url": base + "/origen"})
    assert "(200)" in out and pet == ["/origen", "/destino"]


def test_mas_de_tres_saltos_se_corta(servidor, monkeypatch):
    base, pet = servidor
    _robots_solo(monkeypatch)
    reg = sonda.sondear({"portal": "L", "url": base + "/salto0"})
    assert reg["http_status"] in (301, 302, 303, 307, 308) or reg["estado"] == "error"
    assert len(pet) <= 4  # origen + 3 saltos como maximo
    assert reg["estado"] != "ok"


# ---------- host_de / es_host_bloqueado / registro_omitido ----------
@pytest.mark.parametrize("url,esperado", [
    ("https://www.Portal.ES/a?b=1", "www.portal.es"),
    ("http://127.0.0.1:8080/x", "127.0.0.1:8080"),
    ("", ""), (None, ""), ("sinhost", ""),
])
def test_host_de(url, esperado):
    assert sonda.host_de(url) == esperado


@pytest.mark.parametrize("reg,esperado", [
    ({"http_status": 403}, True), ({"http_status": 429}, True),
    ({"estado": "bloqueado"}, True), ({"http_status": 404, "estado": "ok"}, False),
    ({"http_status": 200, "estado": "ok"}, False), ({}, False),
])
def test_es_host_bloqueado(reg, esperado):
    assert sonda.es_host_bloqueado(reg) is esperado


def test_registro_omitido():
    r = sonda.registro_omitido("P", "https://p.test/x")
    assert r["estado"] == "omitido_host_bloqueado"
    assert r["senales"] == ["host_bloqueado_previo"]
    assert (r["portal"], r["url"], r["http_status"], r["bytes"]) == ("P", "https://p.test/x", None, 0)
    assert r["fecha_utc"].endswith("+00:00")
    assert not sonda.es_host_bloqueado(r)


# ---------- main: salto por host bloqueado ----------
def test_main_fase4_omite_segunda_url_mismo_host(tmp_path, monkeypatch):
    cfgs = [{"portal": "A1", "url": "https://h.test/1"},
            {"portal": "A2", "url": "https://h.test/2"}]
    monkeypatch.setitem(sonda.GRUPOS, "fase4", cfgs)
    llamadas, pausas = [], []

    def falso(cfg):
        llamadas.append(cfg["url"])
        return {"portal": cfg["portal"], "url": cfg["url"], "robots_ok": True, "http_status": 403,
                "url_final": cfg["url"], "bytes": 0, "ms": 0, "senales": [], "estado": "bloqueado",
                "fecha_utc": "x"}
    monkeypatch.setattr(sonda, "sondear", falso)
    monkeypatch.setattr(sonda.time, "sleep", lambda s: pausas.append(s))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert sonda.main(["--grupo", "fase4"]) == 0
    regs = json.loads((tmp_path / "sonda.json").read_text(encoding="utf-8"))
    assert llamadas == ["https://h.test/1"]
    assert regs[1]["estado"] == "omitido_host_bloqueado"
    assert pausas == []  # ni pausa ni peticion para la omitida


def test_main_fase4_otro_host_no_se_omite(tmp_path, monkeypatch):
    cfgs = [{"portal": "A", "url": "https://h1.test/1"}, {"portal": "B", "url": "https://h2.test/1"}]
    monkeypatch.setitem(sonda.GRUPOS, "fase4", cfgs)
    llamadas = []

    def falso(cfg):
        llamadas.append(cfg["url"])
        return {"portal": cfg["portal"], "url": cfg["url"], "robots_ok": True, "http_status": 429,
                "url_final": None, "bytes": 0, "ms": 0, "senales": [], "estado": "bloqueado",
                "fecha_utc": "x"}
    monkeypatch.setattr(sonda, "sondear", falso)
    monkeypatch.setattr(sonda.time, "sleep", lambda s: None)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.chdir(tmp_path)
    sonda.main(["--grupo", "fase4"])
    assert len(llamadas) == 2


def test_main_condiciones_omite_mismo_host_tras_403(tmp_path, monkeypatch):
    cfgs = [{"nombre": "N1", "url": "https://h.test/1"}, {"nombre": "N2", "url": "https://h.test/2"}]
    monkeypatch.setattr(sonda, "CONDICIONES", cfgs)
    llamadas, pausas = [], []
    monkeypatch.setattr(sonda, "condicion", lambda c: llamadas.append(c["url"]) or
                        f"===== {c['nombre']} {c['url']} (403) =====\n[sin texto: HTTP 403]\n")
    monkeypatch.setattr(sonda.time, "sleep", lambda s: pausas.append(s))
    monkeypatch.chdir(tmp_path)
    sonda.main(["--grupo", "condiciones"])
    assert llamadas == ["https://h.test/1"]
    assert pausas == []
    assert "omitido_host_bloqueado" in (tmp_path / "condiciones.txt").read_text(encoding="utf-8")


# ---------- robots_permitido: tope de lectura ----------
def test_robots_lee_como_maximo_max_lectura(monkeypatch):
    pedidos = []

    class R:
        def read(self, n=-1):
            pedidos.append(n)
            return b"User-agent: *\nDisallow:\n"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class Op:
        def open(self, req, timeout=None):
            return R()

    monkeypatch.setattr(sonda, "_OPENER_FACTORY", lambda *h: Op())
    assert sonda.robots_permitido("https://p.test/x") is True
    assert pedidos == [sonda.MAX_LECTURA_ROBOTS]


# ---------- CLI ----------
def test_grupo_invalido_escribe_error_actions(capsys):
    with pytest.raises(SystemExit) as e:
        sonda.main(["--grupo", "nope"])
    assert e.value.code not in (0, None)
    assert "::error::" in capsys.readouterr().err


def test_grupo_valido_no_escribe_error(capsys, tmp_path, monkeypatch):
    monkeypatch.setitem(sonda.GRUPOS, "fase2", [])
    monkeypatch.chdir(tmp_path)
    sonda.main(["--grupo", "fase2"])
    assert "::error::" not in capsys.readouterr().err


# ---------- sonda.yml ----------
def test_workflow_run_sin_inputs_interpolados():
    texto = (RAIZ / ".github/workflows/sonda.yml").read_text(encoding="utf-8")
    try:
        import yaml
        wf = yaml.safe_load(texto)
        pasos = wf["jobs"]["sonda"]["steps"]
        runs = [p["run"] for p in pasos if "run" in p]
        assert runs and all("${{ inputs." not in r and "${{inputs." not in r for r in runs)
        manual = next(p for p in pasos if "inputs.grupo" in str(p.get("env", {})))
        assert "GRUPO" in manual["env"]
    except ImportError:
        lineas = [l for l in texto.splitlines() if re.match(r"\s*run:", l)]
        assert lineas and not any("inputs." in l for l in lineas)
        assert re.search(r"GRUPO:\s*\$\{\{\s*inputs\.grupo", texto)
