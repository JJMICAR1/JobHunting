import pytest

from conftest import utc
from jobhunting import db, pipeline
from jobhunting.descarga import Bloqueado
from jobhunting.portales.tecnoempleo.scraper import URL_BASE

URL2 = "https://www.tecnoempleo.com/ofertas-trabajo/?pr=,240,252,262,276,&pagina=2"


class Fetch:
    def __init__(self, paginas):
        self.paginas, self.urls = paginas, []

    def __call__(self, url):
        self.urls.append(url)
        r = self.paginas[url]
        if isinstance(r, Exception):
            raise r
        return r


def reloj(*instantes):
    it = iter(instantes)
    ultimo = [instantes[-1]]

    def ahora():
        try:
            ultimo[0] = next(it)
        except StopIteration:
            pass
        return ultimo[0]
    return ahora


def sin_siguiente(html):
    from bs4 import BeautifulSoup
    s = BeautifulSoup(html, "html.parser")
    for n in s.find_all("link", rel="next"):
        n.decompose()
    for n in s.find_all("a"):
        if n.get_text().strip().lower() == "siguiente":
            n.decompose()
    return str(s)


def estado(conn):
    return {
        "ofertas": conn.execute("SELECT portal,id_portal,titulo,url,primera_vez FROM ofertas ORDER BY 1,2").fetchall(),
        "recuento": conn.execute("SELECT * FROM recuento_diario ORDER BY 1,2").fetchall(),
    }


@pytest.fixture
def fetch_ok(html_p1, html_p2):
    return lambda: Fetch({URL_BASE: html_p1, URL2: sin_siguiente(html_p2)})


def run(fetch, url, **kw):
    kw.setdefault("sleep", lambda s: None)
    kw.setdefault("ahora", reloj(utc(2026, 11, 3, 8), utc(2026, 11, 3, 8, 1), utc(2026, 11, 3, 8, 2)))
    return pipeline.ejecutar(fetch=fetch, database_url=url, **kw)


def test_idempotencia_dos_ejecuciones(conn, db_url, fetch_ok, capsys):
    assert run(fetch_ok(), db_url) == 0
    e1 = estado(conn)
    assert len(e1["ofertas"]) == 60
    assert e1["recuento"][0][2:4] == (60, 60) and 0 < e1["recuento"][0][4] <= 60
    assert run(fetch_ok(), db_url,
               ahora=reloj(utc(2026, 11, 3, 20), utc(2026, 11, 3, 20, 1), utc(2026, 11, 3, 20, 2))) == 0
    assert estado(conn) == e1  # mismo estado, sin duplicados
    ejec = conn.execute("SELECT estado, n_ofertas FROM ejecuciones").fetchall()
    assert ejec == [("ok", 60), ("ok", 60)]
    assert conn.execute("SELECT count(*) FROM schema_migraciones").fetchone()[0] == 5
    out = capsys.readouterr()
    assert db_url not in out.out + out.err


def test_bloqueado_a_mitad(conn, db_url, html_p1, capsys):
    f = Fetch({URL_BASE: html_p1, URL2: Bloqueado("http_429")})
    assert run(f, db_url) == 2
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 30
    assert conn.execute("SELECT count(*) FROM recuento_diario").fetchone()[0] == 0
    est, n, det = conn.execute("SELECT estado, n_ofertas, detalle FROM ejecuciones").fetchone()
    assert (est, n) == ("bloqueado", 30) and "429" in det
    assert db_url not in capsys.readouterr().out


def test_bloqueado_en_primera_pagina(conn, db_url):
    assert run(Fetch({URL_BASE: Bloqueado("http_403")}), db_url) == 2
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 0
    assert conn.execute("SELECT estado FROM ejecuciones").fetchone()[0] == "bloqueado"


def test_parser_roto(conn, db_url):
    assert run(Fetch({URL_BASE: "<html>cambio de portal</html>"}), db_url) == 1
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 0
    est, det = conn.execute("SELECT estado, detalle FROM ejecuciones").fetchone()
    assert est == "error" and "parser roto" in det


def test_error_inesperado_registra_error(conn, db_url):
    def fetch(url):
        raise RuntimeError("boom")
    assert run(fetch, db_url) == 1
    assert conn.execute("SELECT estado FROM ejecuciones").fetchone()[0] == "error"


def test_sin_database_url(capsys):
    assert pipeline.ejecutar(fetch=Fetch({}), database_url=None) == 1


def test_bd_inaccesible_no_filtra_url(capsys):
    url = "postgresql://usuario:s3cr3t@localhost:1/nada"
    assert pipeline.ejecutar(fetch=Fetch({}), database_url=url) == 1
    out = capsys.readouterr()
    assert "s3cr3t" not in out.out + out.err and url not in out.out + out.err


def test_dry_run_sin_bd(fetch_ok, capsys):
    f = fetch_ok()
    assert pipeline.ejecutar(fetch=f, dry_run=True, database_url=None, sleep=lambda s: None) == 0
    assert f.urls == [URL_BASE, URL2]
    out = capsys.readouterr().out
    assert "n_ofertas: 60" in out and "total_anunciado: 640" in out


def test_dry_run_no_toca_bd(conn, db_url, fetch_ok):
    assert pipeline.ejecutar(fetch=fetch_ok(), dry_run=True, database_url=db_url,
                             sleep=lambda s: None) == 0
    n = conn.execute("SELECT count(*) FROM information_schema.tables "
                     "WHERE table_name = 'ofertas' AND table_schema = current_schema()").fetchone()[0]
    assert n == 0


def test_main_dry_run(monkeypatch, fetch_ok):
    monkeypatch.setattr(pipeline, "descargar", fetch_ok())  # no se usa: ejecutar tiene fetch por defecto
    # main usa el fetch por defecto (red real): solo comprobamos que ejecutar se invoca con dry_run
    llamado = {}
    monkeypatch.setattr(pipeline, "ejecutar", lambda **kw: llamado.update(kw) or 0)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    assert pipeline.main(["--dry-run"]) == 0
    assert llamado["dry_run"] is True
