"""Parser de Feina Activa con el XML sintetico guardado (sin red)."""
from datetime import datetime, timezone
from pathlib import Path

import dataclasses
import pytest

from jobhunting.modelo import Oferta, ParserRoto, validar
from jobhunting.portales.feinaactiva.parser import parsear_xml

XML = (Path(__file__).parent / "fixtures" / "feinaactiva" / "ofertas_muestra.xml").read_bytes()
SENTINELA = "contacto@ejemplo.test"


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def res():
    return parsear_xml(XML)


@pytest.fixture(scope="module")
def por_id(res):
    return {o.id_portal: o for o in res.ofertas}


def ad(id_="X1", **kw):
    c = {"id": id_, "title": "Titulo", "company": "Emp", "city": "GIRONA", "region": "GIRONA",
         "date": "05/06/2026", "url": f"https://feinaactiva.gencat.cat/oferta/{id_}",
         "workingHours": "Jornada completa"}
    c.update(kw)
    return "<ad>" + "".join(f"<{k}>{v}</{k}>" for k, v in c.items() if v is not None) + "</ad>"


def doc(*ads, raiz="ofertes", grupo="g"):
    return f"<{raiz}><{grupo}>{''.join(ads)}</{grupo}></{raiz}>".encode()


def test_recuentos(res):
    assert len(res.ofertas) == 5
    assert res.n_descartadas == 2
    assert res.n_duplicadas == 1
    assert res.n_por_grupo == {"feinaactiva": 6, "sicas": 2}
    assert sum(res.n_por_grupo.values()) == 5 + 2 + 1
    assert res.motivos_descarte == {"url no https o de otro host": 1, "título vacío": 1}


def test_ids_en_orden_y_primera_duplicada_conservada(res, por_id):
    assert [o.id_portal for o in res.ofertas] == ["FA00000001", "FA00000002", "FA00000003",
                                                  "SI00000001", "SI00000002"]
    assert "repetida" not in por_id["FA00000001"].titulo
    assert "FA00000004" not in por_id and "FA00000005" not in por_id


def test_campos_oferta_1(por_id):
    o = por_id["FA00000001"]
    assert o.portal == "feinaactiva"
    assert o.titulo == "Tècnic/a de màrqueting digital"
    assert o.url == "https://feinaactiva.gencat.cat/oferta/FA00000001"
    assert o.empresa == "Empresa Ficticia Alfa SL"
    assert o.ciudad == "Barcelona" and o.ubicacion == "Barcelona"   # ciudad == region: sin repetir
    assert o.modalidad is None
    assert o.capturada_en is None


def test_fechas_utc_medianoche_madrid(por_id):
    # horario de invierno (+1) y de verano (+2)
    assert por_id["FA00000001"].fecha_publicacion == utc(2026, 11, 2, 23)
    # 29/03/2026 y 25/10/2026: dias de cambio de hora; la medianoche aun tiene el offset anterior
    assert por_id["FA00000002"].fecha_publicacion == utc(2026, 3, 28, 23)
    assert por_id["FA00000003"].fecha_publicacion == utc(2026, 10, 24, 22)
    assert por_id["SI00000002"].fecha_publicacion == utc(2026, 3, 25, 23)   # 26/03, antes del cambio
    assert por_id["SI00000001"].fecha_publicacion == utc(2026, 10, 29, 23)  # 30/10, ya invierno


@pytest.mark.parametrize("dia,esperado", [
    ("28/03/2026", utc(2026, 3, 27, 23)),
    ("29/03/2026", utc(2026, 3, 28, 23)),
    ("30/03/2026", utc(2026, 3, 29, 22)),   # primer dia con +2
    ("24/10/2026", utc(2026, 10, 23, 22)),
    ("25/10/2026", utc(2026, 10, 24, 22)),
    ("26/10/2026", utc(2026, 10, 25, 23)),  # primer dia con +1
    ("1/2/2026", utc(2026, 1, 31, 23)),
])
def test_fecha_cambio_de_hora(dia, esperado):
    o = parsear_xml(doc(ad(date=dia))).ofertas[0]
    assert o.fecha_publicacion == esperado
    assert o.fecha_publicacion.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("fecha", ["", "2026-06-05", "31/02/2026", "32/01/2026", "abc"])
def test_fecha_invalida_es_none(fecha):
    o = parsear_xml(doc(ad(date=fecha))).ofertas[0]
    assert o.fecha_publicacion is None


def test_ciudad_capitalizada_con_apostrofo(por_id):
    o = por_id["FA00000002"]
    assert o.ciudad == "L'Hospitalet de Llobregat"
    assert o.ubicacion == "L'Hospitalet de Llobregat, Barcelona"
    assert por_id["SI00000002"].ciudad == "Castell-Platja d'Aro"
    assert por_id["FA00000003"].ciudad == "Sant Cugat del Vallès"


def test_empresa_vacia_es_none(por_id):
    assert por_id["FA00000002"].empresa is None
    assert parsear_xml(doc(ad(company="   "))).ofertas[0].empresa is None
    assert parsear_xml(doc(ad(company=None))).ofertas[0].empresa is None


def test_modalidad_teletreball(por_id):
    assert por_id["SI00000001"].modalidad == "remoto"
    assert por_id["FA00000003"].modalidad is None   # "Torns"


def test_presencial_en_titulo_es_ruido():
    o = parsear_xml(doc(ad(title="Cambrer presencial", workingHours="Jornada completa"))).ofertas[0]
    assert o.modalidad is None


def test_url_otro_host_descartada():
    r = parsear_xml(doc(ad("A1"), ad("A2", url="https://exemple.test/oferta/A2")))
    assert [o.id_portal for o in r.ofertas] == ["A1"] and r.n_descartadas == 1


@pytest.mark.parametrize("url", [
    "http://feinaactiva.gencat.cat/o/1",
    "https://feinaactiva.gencat.cat.evil.test/o/1",
    "https://user@evil.test/o/1",
    "https://evil.test@feinaactiva.gencat.cat/o/1",
    "javascript:alert(1)",
    "",
])
def test_url_peligrosa_descartada(url):
    r = parsear_xml(doc(ad("A1"), ad("A2", url=url)))
    assert [o.id_portal for o in r.ofertas] == ["A1"]


def test_url_conserva_query_sin_fragmento():
    o = parsear_xml(doc(ad(url="https://feinaactiva.gencat.cat/o/1?a=1#frag"))).ofertas[0]
    assert o.url == "https://feinaactiva.gencat.cat/o/1?a=1"


@pytest.mark.parametrize("id_", ["", "a b", "x" * 41, "a/b", "a;b"])
def test_id_invalido_descartado(id_):
    r = parsear_xml(doc(ad("OK1"), ad(id_)))
    assert [o.id_portal for o in r.ofertas] == ["OK1"] and r.n_descartadas == 1


def test_centinela_email_no_aparece_en_ningun_campo(res):
    assert SENTINELA.encode() in XML          # el fixture lo contiene en <content>
    for o in res.ofertas:
        for f in dataclasses.fields(o):
            assert SENTINELA not in str(getattr(o, f.name))
        assert "@" not in repr(o)
    assert SENTINELA not in repr(res)


def test_no_se_guardan_campos_ignorados(res):
    txt = repr(res)
    for palabra in ("Descripció", "Requisits", "Batxillerat", "18000", "24000"):
        assert palabra not in txt


def test_raiz_incorrecta():
    with pytest.raises(ParserRoto):
        parsear_xml(doc(ad(), raiz="jobs"))


@pytest.mark.parametrize("datos", [
    b"<ofertes></ofertes>",
    b"<ofertes><g><otro/></g></ofertes>",
    b"<ofertes><g><x><ad><id>A</id></ad></x></g></ofertes>",   # <ad> demasiado profundo
    b"",
    None,
])
def test_cero_ad(datos):
    with pytest.raises(ParserRoto):
        parsear_xml(datos)


def test_ad_directamente_bajo_raiz_se_cuenta():
    r = parsear_xml(("<ofertes>" + ad("R1") + "</ofertes>").encode())
    assert r.n_por_grupo == {"(raiz)": 1} and len(r.ofertas) == 1


def test_todo_descartado_no_es_parser_roto():
    r = parsear_xml(doc(ad(title="")))
    assert r.ofertas == [] and r.n_descartadas == 1


@pytest.mark.parametrize("cuerpo", [
    b'<?xml version="1.0"?><!DOCTYPE ofertes [<!ENTITY e "x">]><ofertes><g><ad><id>A</id></ad></g></ofertes>',
    b'<ofertes><!ENTITY e "x"><g><ad/></g></ofertes>',
    b"<!doctype ofertes><ofertes><g><ad/></g></ofertes>",
])
def test_doctype_entity_rechazado(cuerpo):
    with pytest.raises(ParserRoto):
        parsear_xml(cuerpo)


def test_doctype_partido_entre_trozos_rechazado():
    """El patron puede caer justo en la frontera de lectura de 64 KB."""
    relleno = b"<!-- " + b"x" * (65536 - 5 - 4) + b" -->"
    cuerpo = b"<ofertes>" + relleno
    cuerpo = cuerpo[:65536 - 4] + b"<!DOCTYPE a>" + b"<g><ad/></g></ofertes>"
    with pytest.raises(ParserRoto):
        parsear_xml(cuerpo)


@pytest.mark.parametrize("cuerpo", [
    b"<ofertes><g><ad><id>A</id></ad>",            # sin cerrar
    b"esto no es xml",
    b"<ofertes><g></ofertes>",
    b"<ofertes><g><ad><id>&desconocida;</id></ad></g></ofertes>",
])
def test_xml_roto(cuerpo):
    with pytest.raises(ParserRoto):
        parsear_xml(cuerpo)


def test_utf16_rechazado():
    with pytest.raises(ParserRoto):
        parsear_xml(doc(ad()).decode().encode("utf-16"))


def test_contrato_de_salida(res):
    for o in res.ofertas:
        assert isinstance(o, Oferta)
        validar(o)
        for campo in ("portal", "id_portal", "titulo", "url"):
            assert isinstance(getattr(o, campo), str) and getattr(o, campo).strip()
        assert o.portal == "feinaactiva"
        assert o.url.startswith("https://feinaactiva.gencat.cat/")
        assert o.empresa is None or (isinstance(o.empresa, str) and o.empresa.strip())
        assert o.fecha_publicacion is not None and o.fecha_publicacion.utcoffset().total_seconds() == 0
        assert o.fecha_publicacion.tzinfo is timezone.utc
        assert o.modalidad in (None, "presencial", "hibrido", "remoto")
        assert o.ciudad and o.ubicacion


def test_idempotencia_parseo():
    a, b = parsear_xml(XML), parsear_xml(XML)
    assert a == b
    assert [o.clave for o in a.ofertas] == [o.clave for o in b.ofertas]
    assert len({o.clave for o in a.ofertas}) == len(a.ofertas)
