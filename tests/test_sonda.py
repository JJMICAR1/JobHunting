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


# --- marcas de bloqueo solo cuentan en paginas pequenas o "Just a moment" ---

def _grande(extra):
    """HTML mayor que MAX_BYTES_BLOQUEO con `extra` dentro."""
    relleno = "x" * (sonda.MAX_BYTES_BLOQUEO + 10)
    return f"<html>{extra} {relleno}</html>"


def test_pagina_grande_con_challenge_platform_funciona_y_senal_ignorada():
    html = _grande("oferta /cdn-cgi/challenge-platform/scripts")
    assert len(html) > sonda.MAX_BYTES_BLOQUEO
    estado, senales = sonda.clasificar(200, URL, html)
    assert estado == "funciona"
    assert "ignorada:challenge-platform" in senales
    assert "challenge-platform" not in senales


def test_pagina_grande_con_just_a_moment_es_bloqueada():
    estado, senales = sonda.clasificar(200, URL, _grande("Just a moment... challenge-platform"))
    assert estado == "bloqueado"
    assert "challenge-platform" in senales


def test_403_grande_sigue_bloqueado():
    estado, senales = sonda.clasificar(403, URL, _grande("oferta challenge-platform"))
    assert estado == "bloqueado"
    assert "http_403" in senales


# --- resumen_html ---

def test_resumen_html_con_titulo_y_recuentos():
    r = sonda.resumen_html("<html><head><title> Ofertas  de\n empleo </title></head>"
                           "oferta Oferta empleo Just a moment</html>")
    assert r["titulo"] == "Ofertas de empleo"
    assert r["n_oferta"] == 3
    assert r["n_empleo"] == 2
    assert r["n_just_a_moment"] == 1


def test_resumen_html_sin_titulo():
    r = sonda.resumen_html("<html>oferta</html>")
    assert r["titulo"] == ""
    assert r["n_oferta"] == 1


def test_resumen_html_none():
    assert sonda.resumen_html(None) == {"titulo": "", "n_oferta": 0, "n_empleo": 0,
                                        "n_just_a_moment": 0}


def test_resumen_html_titulo_con_barra_vertical_y_largo():
    r = sonda.resumen_html("<title>A | B</title>")
    assert "|" not in r["titulo"] and r["titulo"] == "A / B"
    largo = sonda.resumen_html("<title>" + "y" * 200 + "</title>")["titulo"]
    assert len(largo) <= 80
