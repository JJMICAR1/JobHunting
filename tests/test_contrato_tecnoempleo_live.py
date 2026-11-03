import pytest

from jobhunting.descarga import descargar
from jobhunting.portales.tecnoempleo.parser import parsear_listado
from jobhunting.portales.tecnoempleo.scraper import URL_BASE


@pytest.mark.live
def test_contrato_pagina_1_en_vivo():
    r = parsear_listado(descargar(URL_BASE))
    assert len(r.ofertas) >= 10
    assert r.total_anunciado and r.total_anunciado > 0
    for o in r.ofertas:
        assert o.url.startswith("https://") and o.id_portal.startswith("rf-")
