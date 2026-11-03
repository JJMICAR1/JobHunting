"""Ciudad/modalidad coherentes con `ubicacion` y empresa de respaldo (fixtures, sin red)."""
from collections import Counter

import pytest
from bs4 import BeautifulSoup

from conftest import FIXTURES
from jobhunting.normalizar import huella, separar_ubicacion
from jobhunting.portales.tecnoempleo.parser import parsear_listado


def _leer(nombre):
    return parsear_listado((FIXTURES / nombre).read_text(encoding="utf-8"))


@pytest.mark.parametrize("nombre", ["listado_catalunya_p1.html", "listado_catalunya_p2.html",
                                    "tarjetas_raras.html"])
def test_ciudad_modalidad_coherentes(nombre):
    for o in _leer(nombre).ofertas:
        assert (o.ciudad, o.modalidad) == separar_ubicacion(o.ubicacion)
        assert o.modalidad in (None, "presencial", "hibrido", "remoto")
        assert o.huella == huella(o.empresa, o.titulo, o.ciudad)


def test_recuento_ciudad_modalidad_p1_p2():
    c = Counter((o.ciudad, o.modalidad) for n in ("listado_catalunya_p1.html", "listado_catalunya_p2.html")
                for o in _leer(n).ofertas)
    # Verificado contra los fixtures: remoto son 33 (no 35); ademas Madrid 2 + 1.
    assert c == {(None, "remoto"): 33, ("Barcelona", None): 11, ("Barcelona", "hibrido"): 10,
                 ("Barcelona", "presencial"): 3, ("Madrid", None): 2, ("Madrid", "hibrido"): 1}


def test_raras_nacional_y_remoto():
    r = {o.ubicacion: (o.ciudad, o.modalidad) for o in _leer("tarjetas_raras.html").ofertas}
    assert r["España"] == (None, None)
    assert r["100% remoto"] == (None, "remoto")


def test_empresa_respaldo_desde_alt_del_logo(html_p1):
    soup = BeautifulSoup(html_p1, "html.parser")
    t = next(d for d in soup.find_all("div", class_="bg-white") if "location.href" in (d.get("onclick") or ""))
    con = parsear_listado(f"<h1>1 Ofertas</h1>{t}").ofertas[0]
    assert con.empresa == "Mytic Innova"
    t.select_one("a.text-primary.link-muted").decompose()
    for img in t.find_all("img"):
        img["alt"] = "Logo Empresa Respaldo SL"
        img["title"] = "Logo Empresa Respaldo SL"
    sin = parsear_listado(f"<h1>1 Ofertas</h1>{t}").ofertas[0]
    assert sin.empresa == "Empresa Respaldo SL"
    assert sin.id_portal == con.id_portal
