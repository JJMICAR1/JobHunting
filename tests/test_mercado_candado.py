"""Candado de un envio al dia en prod (tabla avisos), con http falso y BD de pruebas."""
from datetime import date, datetime, timezone

import pytest

from jobhunting import db, mercado

DIA = date(2026, 11, 10)
TOKEN, CHAT = "123456:TOKEN-FALSO-abcdef", "987654321"


def ahora(h=6):
    return datetime(2026, 11, 10, h, 0, tzinfo=timezone.utc)


class Http:
    def __init__(self):
        self.n = 0

    def __call__(self, url, datos):
        self.n += 1
        return 200, {"ok": True}


@pytest.fixture
def entorno(conn, db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    db.migrar(conn)
    return conn


def recuento(conn, portal, dia=DIA):
    conn.execute("INSERT INTO recuento_diario (dia,portal,n_vistas,n_nuevas,n_unicas) VALUES (%s,%s,50,5,45)",
                 (dia, portal))


def avisos(conn):
    return conn.execute("SELECT dia, tipo FROM avisos").fetchall()


def test_envia_y_registra_una_sola_vez(entorno):
    recuento(entorno, "tecnoempleo")
    recuento(entorno, "feinaactiva")
    h = Http()
    assert mercado.main(["--entorno", "prod"], ahora=ahora(), http=h) == 0
    assert h.n == 1 and avisos(entorno) == [(DIA, "mercado")]
    assert entorno.execute("SELECT enviado FROM avisos").fetchone()[0] == ahora()
    assert mercado.main(["--entorno", "prod"], ahora=ahora(9), http=h) == 0
    assert h.n == 1 and len(avisos(entorno)) == 1


def test_sin_datos_de_hoy_no_envia_ni_registra(entorno, capsys):
    recuento(entorno, "tecnoempleo", date(2026, 11, 9))
    h = Http()
    for hora in (6, 14):
        assert mercado.main(["--entorno", "prod"], ahora=ahora(hora), http=h) == 0
    assert h.n == 0 and avisos(entorno) == []
    assert "sin datos de hoy" in capsys.readouterr().out


def test_incompleto_antes_de_las_13_espera(entorno, capsys):
    recuento(entorno, "tecnoempleo")
    h = Http()
    assert mercado.main(["--entorno", "prod"], ahora=ahora(12), http=h) == 0
    assert h.n == 0 and avisos(entorno) == []
    assert "incompletos" in capsys.readouterr().out


def test_incompleto_a_las_13_envia_y_registra(entorno):
    assert mercado.HORA_ULTIMA_OPORTUNIDAD == 13
    recuento(entorno, "tecnoempleo")
    h = Http()
    assert mercado.main(["--entorno", "prod"], ahora=ahora(13), http=h) == 0
    assert h.n == 1 and avisos(entorno) == [(DIA, "mercado")]


def test_completo_envia_aunque_sea_temprano_y_otro_dia_envia_otra_vez(entorno):
    for p in ("tecnoempleo", "feinaactiva"):
        recuento(entorno, p)
    h = Http()
    mercado.main(["--entorno", "prod"], ahora=ahora(), http=h)
    for p in ("tecnoempleo", "feinaactiva"):
        recuento(entorno, p, date(2026, 11, 11))
    d2 = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc)
    mercado.main(["--entorno", "prod"], ahora=d2, http=h)
    assert h.n == 2 and len(avisos(entorno)) == 2


def test_dev_envia_siempre_y_no_registra(entorno):
    recuento(entorno, "tecnoempleo")
    h = Http()
    for _ in range(2):
        assert mercado.main(["--entorno", "dev"], ahora=ahora(6), http=h) == 0
    assert h.n == 2 and avisos(entorno) == []


def test_dev_sin_datos_de_hoy_tambien_envia(entorno):
    recuento(entorno, "tecnoempleo", date(2026, 11, 9))
    h = Http()
    assert mercado.main(["--entorno", "dev"], ahora=ahora(), http=h) == 0
    assert h.n == 1


def test_prod_dry_run_no_envia_ni_registra(entorno):
    recuento(entorno, "tecnoempleo")
    recuento(entorno, "feinaactiva")
    h = Http()
    assert mercado.main(["--entorno", "prod", "--dry-run"], ahora=ahora(), http=h) == 0
    assert h.n == 0 and avisos(entorno) == []


def test_si_el_insert_falla_solo_avisa(entorno, monkeypatch, capsys):
    recuento(entorno, "tecnoempleo")
    recuento(entorno, "feinaactiva")

    def roto(conn, dia, ahora):
        raise RuntimeError("fallo SECRETO")
    monkeypatch.setattr(mercado, "registrar_envio", roto)
    h = Http()
    assert mercado.main(["--entorno", "prod"], ahora=ahora(), http=h) == 0
    out = capsys.readouterr().out
    assert h.n == 1 and "::warning::" in out and "no se pudo registrar" in out
    assert "SECRETO" not in out and TOKEN not in out


def test_si_telegram_falla_no_registra(entorno):
    recuento(entorno, "tecnoempleo")
    recuento(entorno, "feinaactiva")
    assert mercado.main(["--entorno", "prod"], ahora=ahora(), http=lambda u, d: (500, None)) == 1
    assert avisos(entorno) == []


def test_prod_sin_migrar_migra_antes_del_candado(conn, db_url, monkeypatch):
    """BD de prod sin la tabla avisos (ni nada): main migra primero y no falla."""
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    h = Http()
    assert mercado.main(["--entorno", "prod"], ahora=ahora(), http=h) == 0
    assert h.n == 0  # sin datos de hoy
    assert conn.execute("SELECT to_regclass('avisos')").fetchone()[0] is not None


def test_prod_sin_token_no_toca_avisos(entorno, capsys):
    recuento(entorno, "tecnoempleo")
    recuento(entorno, "feinaactiva")
    import os
    os.environ.pop("TELEGRAM_BOT_TOKEN")
    assert mercado.main(["--entorno", "prod"], ahora=ahora(), http=Http()) == 0
    assert "::warning::" in capsys.readouterr().out and avisos(entorno) == []
