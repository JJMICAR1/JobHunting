import re
from datetime import timezone

import pytest
from bs4 import BeautifulSoup

from jobhunting.portales.tecnoempleo.parser import ParserRoto, parsear_listado


@pytest.fixture(scope="module")
def res(request):
    from conftest import FIXTURES
    return {p: parsear_listado((FIXTURES / f"listado_catalunya_p{p}.html").read_text(encoding="utf-8"))
            for p in (1, 2)}


@pytest.mark.parametrize("p", [1, 2])
def test_30_ofertas_y_contrato(res, p):
    r = res[p]
    assert len(r.ofertas) == 30
    assert r.n_descartadas == 0
    assert r.total_anunciado == 640
    ids = [o.id_portal for o in r.ofertas]
    assert len(set(ids)) == 30
    for o in r.ofertas:
        assert re.fullmatch(r"rf-[0-9a-f]+", o.id_portal)
        assert o.portal == "tecnoempleo"
        assert o.url.startswith("https://")
        assert "?" not in o.url and "#" not in o.url
        assert o.url.endswith(o.id_portal)
        assert "&" not in o.titulo or "&amp;" not in o.titulo
        assert not re.search(r"&(amp|lt|gt|quot|#\d+|[a-z]+);", o.titulo)
        assert "  " not in o.titulo and o.titulo == o.titulo.strip()
        assert o.titulo and o.empresa
        f = o.fecha_publicacion
        assert f is not None and f.tzinfo is not None and f.utcoffset().total_seconds() == 0
        assert f.tzinfo == timezone.utc
        assert (f.hour, f.minute, f.second) == (0, 0, 0)
        assert o.capturada_en is None


def test_paginas_sin_solape(res):
    a = {o.clave for o in res[1].ofertas}
    b = {o.clave for o in res[2].ofertas}
    assert not a & b


def test_url_siguiente(res):
    assert res[1].url_siguiente == "https://www.tecnoempleo.com/ofertas-trabajo/?pr=,240,252,262,276,&pagina=2"


def test_ubicaciones(res):
    ubis = [o.ubicacion for p in res.values() for o in p.ofertas]
    assert any(u and u.startswith("Barcelona") for u in ubis)
    assert any(u and "remoto" in u.lower() for u in ubis)


def test_ofertas_concretas(res):
    por_id = {o.id_portal: o for o in res[1].ofertas}
    o = por_id["rf-100312cc527e6322524a"]
    assert o.titulo == "QA Tester Funcional (Java/Cobol)"
    assert o.empresa == "Mytic Innova"
    assert o.ubicacion == "Barcelona (Híbrido)"
    assert o.url == ("https://www.tecnoempleo.com/qa-tester-funcional-java-cobol-mytic-innova/"
                     "sql/rf-100312cc527e6322524a")
    o2 = {o.id_portal: o for o in res[2].ofertas}["rf-8d821de0e217c3d7ca42"]
    assert (o2.titulo, o2.empresa, o2.ubicacion) == ("Técnico/a Sistemas", "Sosmatic", "100% remoto")


@pytest.mark.parametrize("html", ["", None, "<html><body><p>hola</p></body></html>", "xyz aleatorio"])
def test_html_vacio_o_aleatorio_parser_roto(html):
    with pytest.raises(ParserRoto):
        parsear_listado(html)


def test_tarjeta_corrupta_se_descarta(html_p1):
    soup = BeautifulSoup(html_p1, "html.parser")
    tarjetas = [d for d in soup.find_all("div", class_="bg-white")
                if {"p-3", "border", "rounded", "mb-3"} <= set(d.get("class", []))
                and "location.href" in (d.get("onclick") or "")]
    assert len(tarjetas) == 30
    tarjetas[4].find("h3").decompose()                     # sin enlace de titulo
    a = tarjetas[7].select_one("h3 a[href]")
    a["href"] = "/sin-id-valido"                           # sin id rf-
    r = parsear_listado(str(soup))
    assert r.n_descartadas == 2
    assert len(r.ofertas) == 28
    assert r.total_anunciado == 640


def test_pagina_repetida_dentro_de_la_pagina_se_deduplica(html_p1):
    # Duplicar el contenido de las tarjetas no debe producir ids repetidos.
    r = parsear_listado(html_p1)
    assert len({o.clave for o in r.ofertas}) == len(r.ofertas)


# --- Tarjetas raras: ubicacion sin <b>, ids alfanumericos no hex ---------------

@pytest.fixture(scope="module")
def raras():
    from conftest import FIXTURES
    return parsear_listado((FIXTURES / "tarjetas_raras.html").read_text(encoding="utf-8"))


def test_raras_recuento(raras):
    assert len(raras.ofertas) == 4
    assert raras.n_descartadas == 0
    assert raras.total_anunciado == 614


def test_raras_ubicaciones_exactas(raras):
    assert [o.ubicacion for o in raras.ofertas] == [
        "España", "EspaÑa y otras", "100% remoto", "100% remoto"]


def test_raras_ids_no_hex_aceptados(raras):
    ids = {o.id_portal for o in raras.ofertas}
    assert "rf-1ab0lc47b4701m42c7y7" in ids
    assert "rf-f095e837el53cs7c6ega" in ids
    for o in raras.ofertas:
        assert re.fullmatch(r"rf-[0-9a-z]+", o.id_portal)
        assert o.url.endswith(o.id_portal)


def test_raras_fechas_utc(raras):
    from datetime import datetime
    esperadas = [datetime(2026, 10, 29, tzinfo=timezone.utc),
                 datetime(2026, 10, 27, tzinfo=timezone.utc),
                 datetime(2025, 2, 24, tzinfo=timezone.utc),
                 datetime(2023, 10, 30, tzinfo=timezone.utc)]
    assert [o.fecha_publicacion for o in raras.ofertas] == esperadas
    assert all(o.fecha_publicacion.tzinfo == timezone.utc for o in raras.ofertas)


def test_raras_empresa(raras):
    assert raras.ofertas[0].empresa == "Michael Page"


def test_raras_sueldo_tras_br_no_entra_en_ubicacion(raras):
    o = raras.ofertas[3]
    assert o.id_portal == "rf-f095e837el53cs7c6ega"
    assert o.ubicacion == "100% remoto"
    assert "€" not in o.ubicacion and "21.000" not in o.ubicacion
    assert o.fecha_publicacion.year == 2023


def test_fixtures_p1_p2_todas_con_ubicacion(res):
    for p in (1, 2):
        sin = [o.id_portal for o in res[p].ofertas if not o.ubicacion]
        assert sin == [], f"p{p} ofertas sin ubicacion: {sin}"


def test_regresion_selector_tarjetas_no_usa_clases_inexistentes():
    """Issue #14: el selector de tarjetas apuntaba a una clase que no existe en el HTML real."""
    from pathlib import Path
    html = (Path(__file__).parent / "fixtures/tecnoempleo/listado_catalunya_p1.html").read_text(encoding="utf-8")
    assert "bg-blanco" not in html
    assert len(parsear_listado(html).ofertas) > 0
