"""Feina Activa + Tecnoempleo contra Postgres (TEST_DATABASE_URL): idempotencia, recuento, convivencia."""
from pathlib import Path

import pytest

from conftest import utc
from jobhunting import pipeline
from jobhunting.portales.feinaactiva import scraper as sc_fa
from jobhunting.portales.tecnoempleo.scraper import URL_BASE

XML = (Path(__file__).parent / "fixtures" / "feinaactiva" / "ofertas_muestra.xml").read_bytes()
URL2 = "https://www.tecnoempleo.com/ofertas-trabajo/?pr=,240,252,262,276,&pagina=2"
SENTINELA = "contacto@ejemplo.test"


def reloj(*instantes):
    it, ultimo = iter(instantes), [instantes[-1]]

    def ahora():
        try:
            ultimo[0] = next(it)
        except StopIteration:
            pass
        return ultimo[0]
    return ahora


def dia(h, d=3):
    return reloj(utc(2026, 11, d, h), utc(2026, 11, d, h, 1), utc(2026, 11, d, h, 2))


def fa(db_url, xml=XML, h=8, d=3):
    return pipeline.ejecutar_portal("feinaactiva", fetch=lambda u, *a, **k: xml, database_url=db_url,
                                    ahora=dia(h, d))


def tecno(db_url, html_p1, html_p2, h=9, d=3):
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html_p2, "html.parser")
    for n in s.find_all("link", rel="next"):
        n.decompose()
    for n in s.find_all("a"):
        if n.get_text().strip().lower() == "siguiente":
            n.decompose()
    pag = {URL_BASE: html_p1, URL2: str(s)}
    return pipeline.ejecutar_portal("tecnoempleo", fetch=lambda u: pag[u], database_url=db_url,
                                    sleep=lambda s: None, ahora=dia(h, d))


def estado(conn):
    return {
        "ofertas": conn.execute("SELECT portal,id_portal,titulo,url,empresa,ciudad,modalidad,"
                                "fecha_publicacion,primera_vez FROM ofertas ORDER BY 1,2").fetchall(),
        "recuento": conn.execute("SELECT * FROM recuento_diario ORDER BY 1,2").fetchall(),
    }


def test_dos_ejecuciones_no_duplican(conn, db_url):
    assert fa(db_url) == 0
    e1 = estado(conn)
    assert len(e1["ofertas"]) == 5
    assert fa(db_url, h=20) == 0   # mismo dia UTC, otra hora
    e2 = estado(conn)
    assert e2["ofertas"] == e1["ofertas"] and e2["recuento"] == e1["recuento"]
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 5
    assert conn.execute("SELECT count(*) FROM (SELECT 1 FROM ofertas GROUP BY portal,id_portal "
                        "HAVING count(*)>1) t").fetchone()[0] == 0


def test_dos_ejecuciones_otro_dia_no_duplican_y_avanza_ultima_vez(conn, db_url):
    assert fa(db_url, d=3) == 0
    antes = conn.execute("SELECT id_portal, primera_vez, ultima_vez FROM ofertas ORDER BY 1").fetchall()
    assert fa(db_url, d=4) == 0
    despues = conn.execute("SELECT id_portal, primera_vez, ultima_vez FROM ofertas ORDER BY 1").fetchall()
    assert len(despues) == 5
    for (i1, p1, u1), (i2, p2, u2) in zip(antes, despues):
        assert i1 == i2 and p1 == p2 and u2 > u1
    rec = conn.execute("SELECT dia, n_vistas, n_nuevas FROM recuento_diario ORDER BY dia").fetchall()
    assert [(r[1], r[2]) for r in rec] == [(5, 5), (5, 0)]


def test_filas_guardadas_y_fechas_utc(conn, db_url):
    assert fa(db_url) == 0
    filas = {r[0]: r for r in conn.execute(
        "SELECT id_portal, portal, empresa, ciudad, modalidad, fecha_publicacion, url FROM ofertas").fetchall()}
    assert set(filas) == {"FA00000001", "FA00000002", "FA00000003", "SI00000001", "SI00000002"}
    assert all(r[1] == "feinaactiva" for r in filas.values())
    assert filas["FA00000001"][5] == utc(2026, 11, 2, 23)
    assert filas["FA00000001"][5].utcoffset().total_seconds() == 0
    assert filas["FA00000002"][2] is None and filas["FA00000002"][3] == "L'Hospitalet de Llobregat"
    assert filas["SI00000001"][4] == "remoto"
    assert all(r[6].startswith("https://feinaactiva.gencat.cat/") for r in filas.values())


def test_sin_datos_personales_en_bd(conn, db_url):
    assert fa(db_url) == 0
    cols = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name='ofertas' "
        "AND data_type IN ('text','character varying')").fetchall()]
    assert cols
    for c in cols:
        n = conn.execute(f'SELECT count(*) FROM ofertas WHERE "{c}" ILIKE %s', (f"%{SENTINELA}%",)).fetchone()[0]
        assert n == 0
        n = conn.execute(f'SELECT count(*) FROM ofertas WHERE "{c}" LIKE %s', ("%@%",)).fetchone()[0]
        assert n == 0


def test_recuento_diario_por_portal(conn, db_url):
    assert fa(db_url) == 0
    r = conn.execute("SELECT dia, portal, n_vistas, n_nuevas, n_unicas FROM recuento_diario").fetchall()
    assert len(r) == 1
    assert r[0][0].isoformat() == "2026-11-03" and r[0][1] == "feinaactiva"
    assert r[0][2:4] == (5, 5)
    assert r[0][4] == 5    # 5 puestos distintos (empresa+titulo+ciudad)


def test_ejecucion_registrada_por_portal(conn, db_url):
    assert fa(db_url) == 0
    assert conn.execute("SELECT portal, estado, n_ofertas, detalle FROM ejecuciones").fetchall() == \
        [("feinaactiva", "ok", 5, None)]


def test_tecnoempleo_y_feinaactiva_conviven(conn, db_url, html_p1, html_p2):
    assert tecno(db_url, html_p1, html_p2) == 0
    solo_t = conn.execute("SELECT * FROM ofertas WHERE portal='tecnoempleo' ORDER BY id_portal").fetchall()
    rec_t = conn.execute("SELECT * FROM recuento_diario WHERE portal='tecnoempleo'").fetchall()
    assert len(solo_t) == 60
    assert fa(db_url) == 0
    # Tecnoempleo intacto
    assert conn.execute("SELECT * FROM ofertas WHERE portal='tecnoempleo' ORDER BY id_portal").fetchall() == solo_t
    assert conn.execute("SELECT * FROM recuento_diario WHERE portal='tecnoempleo'").fetchall() == rec_t
    # Feina Activa propia
    assert conn.execute("SELECT count(*) FROM ofertas WHERE portal='feinaactiva'").fetchone()[0] == 5
    por_portal = dict(conn.execute("SELECT portal, n_vistas FROM recuento_diario").fetchall())
    assert por_portal == {"tecnoempleo": 60, "feinaactiva": 5}
    # Reejecutar ambos en orden inverso no cambia nada
    antes = estado(conn)
    assert fa(db_url, h=10) == 0
    assert tecno(db_url, html_p1, html_p2, h=11) == 0
    assert estado(conn) == antes


def test_mismo_id_en_dos_portales_no_se_pisa(conn, db_url, html_p1, html_p2):
    """La clave es (portal, id_portal): un id igual en otro portal es otra oferta."""
    assert tecno(db_url, html_p1, html_p2) == 0
    conn.execute("UPDATE ofertas SET id_portal='FA00000001' WHERE id_portal=(SELECT min(id_portal) FROM ofertas)")
    assert fa(db_url) == 0
    assert conn.execute("SELECT portal FROM ofertas WHERE id_portal='FA00000001' ORDER BY 1").fetchall() == \
        [("feinaactiva",), ("tecnoempleo",)]
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 65


def test_ejecuciones_por_portal_con_todos(conn, db_url, html_p1, html_p2, monkeypatch):
    """ejecutar('todos') contra BD: un portal falla (bloqueado) y el otro guarda; cada uno su ejecucion."""
    from jobhunting.descarga import Bloqueado
    from jobhunting.portales.tecnoempleo import scraper as sc_t

    def bloqueada(url):
        raise Bloqueado("http_429")
    monkeypatch.setattr(pipeline, "recorrer",
                        lambda fetch=None, **kw: sc_t.recorrer(fetch=bloqueada, **kw))
    monkeypatch.setattr(pipeline, "descargar_bytes", lambda u, *a, **k: XML)
    assert pipeline.ejecutar(portal="todos", database_url=db_url, sleep=lambda s: None, ahora=dia(8)) == 2
    ej = dict((p, (e, n)) for p, e, n in conn.execute("SELECT portal, estado, n_ofertas FROM ejecuciones").fetchall())
    assert ej == {"tecnoempleo": ("bloqueado", 0), "feinaactiva": ("ok", 5)}
    assert conn.execute("SELECT count(*) FROM ofertas WHERE portal='feinaactiva'").fetchone()[0] == 5
    assert conn.execute("SELECT portal FROM recuento_diario").fetchall() == [("feinaactiva",)]


def test_parser_roto_registra_error_sin_filas(conn, db_url):
    assert pipeline.ejecutar_portal("feinaactiva", fetch=lambda u, *a, **k: b"<html/>", database_url=db_url,
                                    ahora=dia(8)) == 1
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 0
    p, est, det = conn.execute("SELECT portal, estado, detalle FROM ejecuciones").fetchone()
    assert (p, est) == ("feinaactiva", "error") and "parser roto" in det


def test_url_de_bd_no_se_imprime(conn, db_url, capsys):
    assert fa(db_url) == 0
    o = capsys.readouterr()
    assert db_url not in o.out + o.err
