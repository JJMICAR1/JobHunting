from datetime import datetime, timedelta, timezone

import pytest

from jobhunting.modelo import Oferta, OfertaInvalida, deduplicar


def mk(**kw):
    base = dict(portal="tecnoempleo", id_portal="rf-1", titulo="Dev", url="https://x.com/a")
    base.update(kw)
    return Oferta(**base)


def test_valida_ok_con_fechas_utc():
    o = mk(fecha_publicacion=datetime(2026, 1, 1, tzinfo=timezone.utc),
           capturada_en=datetime.now(timezone.utc))
    assert o.clave == ("tecnoempleo", "rf-1")


@pytest.mark.parametrize("campo", ["portal", "id_portal", "titulo", "url"])
@pytest.mark.parametrize("valor", ["", "   ", None])
def test_campos_obligatorios_vacios(campo, valor):
    with pytest.raises(OfertaInvalida):
        mk(**{campo: valor})


def test_url_http_rechazada():
    with pytest.raises(OfertaInvalida):
        mk(url="http://x.com/a")


def test_portal_mayusculas_rechazado():
    with pytest.raises(OfertaInvalida):
        mk(portal="Tecnoempleo")


def test_titulo_demasiado_largo():
    with pytest.raises(OfertaInvalida):
        mk(titulo="a" * 301)


@pytest.mark.parametrize("campo", ["fecha_publicacion", "capturada_en"])
def test_fecha_naive_rechazada(campo):
    with pytest.raises(OfertaInvalida):
        mk(**{campo: datetime(2026, 1, 1)})


@pytest.mark.parametrize("campo", ["fecha_publicacion", "capturada_en"])
def test_fecha_no_utc_rechazada(campo):
    with pytest.raises(OfertaInvalida):
        mk(**{campo: datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2)))})


def test_fecha_no_datetime_rechazada():
    with pytest.raises(OfertaInvalida):
        mk(fecha_publicacion="2026-01-01")


def test_oferta_invalida_es_valueerror():
    assert issubclass(OfertaInvalida, ValueError)


def test_deduplicar_conserva_primera_y_orden():
    a, b, c = mk(id_portal="a", titulo="A1"), mk(id_portal="b"), mk(id_portal="c")
    a2 = mk(id_portal="a", titulo="A2")
    salida = deduplicar([b, a, c, a2, b])
    assert [o.id_portal for o in salida] == ["b", "a", "c"]
    assert salida[1].titulo == "A1"


def test_deduplicar_distingue_portal_y_vacio():
    assert len(deduplicar([mk(portal="x"), mk(portal="y")])) == 2
    assert deduplicar([]) == []
