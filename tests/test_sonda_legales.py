"""Tests del grupo 'legales' de scripts/sonda_portales.py (sin red)."""
import io
import urllib.error

from tests.test_sonda import sonda

BASE = "https://www.infoempleo.com/"
DOM = "infoempleo.com"


def _html(*hrefs_textos):
    return "<html><body>" + "".join(f'<a href="{h}">{t}</a>' for h, t in hrefs_textos) + "</body></html>"


# ---------- enlaces_legales ----------
def test_enlaces_mismo_dominio_y_subdominio():
    h = _html(("/aviso-legal", "Aviso legal"), ("https://ayuda.infoempleo.com/terms", "Terms"))
    assert sonda.enlaces_legales(h, BASE, DOM) == [
        "https://www.infoempleo.com/aviso-legal", "https://ayuda.infoempleo.com/terms"]


def test_enlaces_otro_dominio_no():
    h = _html(("https://otro.com/aviso-legal", "Aviso legal"))
    assert sonda.enlaces_legales(h, BASE, DOM) == []


def test_enlaces_dominio_parecido_no():
    h = _html(("https://evil-infoempleo.com/legal", "Legal"),
              ("https://infoempleo.com.evil.com/legal", "Legal"))
    assert sonda.enlaces_legales(h, BASE, DOM) == []


def test_enlaces_deduplica_y_quita_fragmento():
    h = _html(("/legal#a", "Legal"), ("/legal#b", "Aviso legal"), ("/legal", "Legal"))
    assert sonda.enlaces_legales(h, BASE, DOM) == ["https://www.infoempleo.com/legal"]


def test_enlaces_maximo_dos():
    h = _html(("/legal1", "Legal"), ("/legal2", "Legal"), ("/legal3", "Legal"))
    assert len(sonda.enlaces_legales(h, BASE, DOM)) == 2
    assert len(sonda.enlaces_legales(h, BASE, DOM, maximo=3)) == 3


def test_enlaces_mayusculas():
    h = _html(("/X", "AVISO LEGAL"), ("/CONDICIONES-USO", "otro"))
    assert sonda.enlaces_legales(h, BASE, DOM) == [
        "https://www.infoempleo.com/X", "https://www.infoempleo.com/CONDICIONES-USO"]


# ---------- coincidencias ----------
def test_coincidencias_contexto():
    t = "a" * 200 + " Scraping " + "b" * 200
    r = sonda.coincidencias(t, ["scraping"], 100)
    assert len(r) == 1 and r[0][0] == "scraping"
    assert "Scraping" in r[0][1] and len(r[0][1]) <= 110 and r[0][1].startswith("a")


def test_coincidencias_varias_claves():
    r = sonda.coincidencias("prohibido scraping y robots; otro robots", ["scraping", "robots"], 40)
    assert [c for c, _ in r].count("robots") == 2
    assert [c for c, _ in r].count("scraping") == 1


def test_coincidencias_ninguna():
    assert sonda.coincidencias("texto inocente", ["scraping"], 50) == []
    assert sonda.coincidencias("", ["scraping"], 50) == []


# ---------- dominio_registrable / sanea_linea ----------
def test_dominio_registrable():
    assert sonda.dominio_registrable("foo.example.co.uk") == "example.co.uk"
    assert sonda.dominio_registrable("es.talent.com") == "talent.com"
    assert sonda.dominio_registrable("www.infoempleo.com:443") == "infoempleo.com"
    assert sonda.dominio_registrable("talent.com") == "talent.com"


def test_sanea_linea_neutraliza_dobles_dos_puntos():
    s = sonda.sanea_linea("::error::boom\n::warning::x")
    assert "::" not in s
    assert all(l.startswith("| ") for l in s.split("\n"))


# ---------- LEGALES ----------
def test_legales_urls_https():
    assert sonda.LEGALES
    for c in sonda.LEGALES:
        assert c["url"].startswith("https://"), c


# ---------- main_legales con opener falso ----------
class _Resp:
    def __init__(self, status, cuerpo):
        self.status, self._b = status, cuerpo.encode()

    def read(self, n=-1):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _instalar(monkeypatch, respuestas):
    """respuestas: url -> (status, html). Devuelve la lista de URLs pedidas."""
    pedidas = []

    class Opener:
        def open(self, req, timeout=None):
            url = req.full_url
            pedidas.append(url)
            st, cuerpo = respuestas.get(url, (404, ""))
            if st >= 400:
                raise urllib.error.HTTPError(url, st, "err", {}, io.BytesIO(b""))
            return _Resp(st, cuerpo)

    monkeypatch.setattr(sonda, "_OPENER_FACTORY", lambda *a, **k: Opener())
    monkeypatch.setattr(sonda, "robots_permitido", lambda url: True)
    monkeypatch.setattr(sonda.time, "sleep", lambda s: None)
    return pedidas


def _portadas(monkeypatch, cfgs):
    monkeypatch.setattr(sonda, "LEGALES", cfgs)


def test_main_legales_403_salta_host(monkeypatch, capsys):
    _portadas(monkeypatch, [{"nombre": "A", "url": "https://www.a.com/"},
                            {"nombre": "A2", "url": "https://www.a.com/otra"}])
    pedidas = _instalar(monkeypatch, {"https://www.a.com/": (403, "")})
    sonda.main_legales()
    assert pedidas == ["https://www.a.com/"]  # la 2a portada del mismo host no se pide
    out = capsys.readouterr().out
    assert "omitido_host_bloqueado" in out


def test_main_legales_maximo_dos_paginas_y_prefijo(monkeypatch, capsys):
    _portadas(monkeypatch, [{"nombre": "B", "url": "https://www.b.com/"}])
    home = _html(("/l1", "Legal"), ("/l2", "Legal"), ("/l3", "Legal"))
    pedidas = _instalar(monkeypatch, {
        "https://www.b.com/": (200, home),
        "https://www.b.com/l1": (200, "<p>Prohibido el scraping ::error::x</p>"),
        "https://www.b.com/l2": (200, "<p>nada</p>"),
        "https://www.b.com/l3": (200, "<p>no</p>"),
    })
    sonda.main_legales()
    assert pedidas == ["https://www.b.com/", "https://www.b.com/l1", "https://www.b.com/l2"]
    out = capsys.readouterr().out
    lineas = [l for l in out.split("\n") if l != ""]
    assert lineas and all(l.startswith("| ") for l in lineas), lineas
    assert "::" not in out
    assert "[scrap]" in out
