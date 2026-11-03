"""Tests de scripts/sonda_portales.py (sin red)."""
import importlib.util
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parent.parent / "scripts" / "sonda_portales.py"
_spec = importlib.util.spec_from_file_location("sonda_portales", RUTA)
sonda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sonda)

URL = "https://example.test/ofertas"


@pytest.mark.parametrize("status", [403, 429, 451, 503])
def test_status_de_bloqueo(status):
    estado, senales = sonda.clasificar(status, URL, "<html>oferta</html>")
    assert estado == "bloqueado"
    assert f"http_{status}" in senales


@pytest.mark.parametrize("marca", ["captcha", "cf-chl", "datadome"])
def test_200_con_marca_de_bloqueo(marca):
    estado, senales = sonda.clasificar(200, URL, f"<html>oferta {marca.upper()}</html>")
    assert estado == "bloqueado"
    assert marca in senales


@pytest.mark.parametrize("url", ["https://x.test/login?next=/jobs",
                                 "https://www.linkedin.com/authwall?trk=1"])
def test_redirige_login(url):
    estado, _ = sonda.clasificar(200, url, "<html>oferta</html>")
    assert estado == "redirige_login"


def test_status_none_es_error():
    estado, senales = sonda.clasificar(None, None, None)
    assert estado == "error"
    assert "http_None" in senales


def test_404_es_error():
    estado, senales = sonda.clasificar(404, URL, "<html>oferta</html>")
    assert estado == "error"
    assert "http_404" in senales


def test_200_con_palabra_esperada_funciona():
    estado, senales = sonda.clasificar(200, URL, "<html>Ofertas de EMPLEO</html>")
    assert estado == "funciona"
    assert "palabra:oferta" in senales
    assert "palabra:empleo" in senales


def test_200_sin_palabras_necesita_js():
    estado, senales = sonda.clasificar(200, URL, "<html><div id='root'></div></html>")
    assert estado == "necesita_js"
    assert not any(s.startswith("palabra:") for s in senales)


def test_html_none_no_rompe():
    assert sonda.clasificar(200, URL, None)[0] == "necesita_js"
    assert sonda.clasificar(200, None, None)[0] == "necesita_js"


def test_esperadas_personalizadas():
    html = "<html>solo gatitos</html>"
    assert sonda.clasificar(200, URL, html)[0] == "necesita_js"
    estado, senales = sonda.clasificar(200, URL, html, esperadas=["gatitos"])
    assert estado == "funciona"
    assert senales == ["palabra:gatitos"]
    # las genericas dejan de aplicar
    assert sonda.clasificar(200, URL, "<html>oferta</html>", esperadas=["gatitos"])[0] == "necesita_js"


def _reg(portal, estado):
    return {"portal": portal, "url": URL, "robots_ok": True, "http_status": 200,
            "url_final": URL, "bytes": 10, "ms": 5, "senales": ["a", "b"], "estado": estado}


def test_tabla_md_cabecera_y_filas():
    regs = [_reg("Uno", "funciona"), _reg("Dos", "bloqueado")]
    lineas = sonda.tabla_md(regs).strip("\n").split("\n")
    assert len(lineas) == 2 + len(regs)
    assert lineas[0].startswith("| Portal | Estado")
    assert set(lineas[1].replace("|", "")) == {"-"}
    assert "Uno" in lineas[2] and "funciona" in lineas[2] and "a, b" in lineas[2]
    assert "Dos" in lineas[3] and "bloqueado" in lineas[3]


def test_tabla_md_vacia_solo_cabecera():
    assert len(sonda.tabla_md([]).strip("\n").split("\n")) == 2


def test_sondear_prohibido_robots_no_pide_busqueda(monkeypatch):
    def no_red(*a, **k):
        raise AssertionError("urlopen no debe llamarse")

    monkeypatch.setattr(sonda, "robots_permitido", lambda url: False)
    monkeypatch.setattr(sonda.urllib.request, "urlopen", no_red)
    reg = sonda.sondear({"portal": "P", "url": URL, "esperadas": ["x"]})
    assert reg["estado"] == "prohibido_robots"
    assert reg["robots_ok"] is False
    assert reg["http_status"] is None
    assert reg["fecha_utc"].endswith("+00:00")


def test_sondear_robots_no_leido_no_pide_busqueda(monkeypatch):
    def no_red(*a, **k):
        raise AssertionError("urlopen no debe llamarse")

    monkeypatch.setattr(sonda, "robots_permitido", lambda url: None)
    monkeypatch.setattr(sonda.urllib.request, "urlopen", no_red)
    reg = sonda.sondear({"portal": "P", "url": URL})
    assert reg["estado"] == "error"
    assert "robots_no_leido" in reg["senales"]
