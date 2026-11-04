"""--solo-si-falta: portales_pendientes / ya_ejecutado_hoy (puras) y main contra BD (sin red)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import utc
from jobhunting import db, pipeline
from jobhunting.portales.tecnoempleo.scraper import URL_BASE
from tests.test_pipeline import URL2, Fetch, sin_siguiente

HOY = date(2026, 11, 4)
TE, FA = "tecnoempleo", "feinaactiva"
OK_TE = (TE, "ok", utc(2026, 11, 4, 5, 20))
OK_FA = (FA, "ok", utc(2026, 11, 4, 5, 25))


# --- puras ---
def test_todos_ok_hoy():
    assert pipeline.ya_ejecutado_hoy([OK_TE, OK_FA], HOY) is True
    assert pipeline.portales_pendientes([OK_TE, OK_FA], HOY) == []


def test_sin_filas_faltan_todos():
    assert pipeline.ya_ejecutado_hoy([], HOY) is False
    assert pipeline.portales_pendientes([], HOY) == list(pipeline.PORTALES)


def test_falta_un_portal():
    assert pipeline.ya_ejecutado_hoy([OK_TE], HOY) is False
    assert pipeline.portales_pendientes([OK_TE], HOY) == [FA]
    assert pipeline.portales_pendientes([OK_FA], HOY) == [TE]


def test_error_no_cuenta():
    filas = [OK_TE, (FA, "error", utc(2026, 11, 4, 5, 25))]
    assert pipeline.ya_ejecutado_hoy(filas, HOY) is False
    assert pipeline.portales_pendientes(filas, HOY) == [FA]


def test_bloqueado_hoy_cuenta_como_cubierto():
    filas = [OK_TE, (FA, "bloqueado", utc(2026, 11, 4, 5, 25))]
    assert pipeline.portales_pendientes(filas, HOY) == []


def test_error_y_luego_ok_cuenta():
    filas = [(TE, "error", utc(2026, 11, 4, 5, 0)), OK_TE, OK_FA]
    assert pipeline.ya_ejecutado_hoy(filas, HOY) is True


def test_ok_de_ayer_no_cuenta():
    filas = [(TE, "ok", utc(2026, 11, 3, 23, 59, 59)), OK_FA]
    assert pipeline.portales_pendientes(filas, HOY) == [TE]


def test_borde_medianoche_utc():
    assert pipeline.portales_pendientes([(TE, "ok", utc(2026, 11, 4, 0, 0, 0)), OK_FA], HOY) == []
    assert pipeline.portales_pendientes([(TE, "ok", utc(2026, 11, 3, 23, 59, 59, 999999)), OK_FA], HOY) == [TE]
    # el dia siguiente tampoco es hoy
    assert pipeline.portales_pendientes([(TE, "ok", utc(2026, 11, 5, 0, 0, 0)), OK_FA], HOY) == [TE]


def test_zonas_horarias_se_pasan_a_utc():
    madrid = timezone(timedelta(hours=1))
    # 00:30 en Madrid del 4 = 23:30 UTC del 3 -> NO es hoy
    ayer = (TE, "ok", datetime(2026, 11, 4, 0, 30, tzinfo=madrid))
    assert pipeline.portales_pendientes([ayer, OK_FA], HOY) == [TE]
    # 23:30 del 3 en UTC-2 = 01:30 UTC del 4 -> SI es hoy
    hoy = (TE, "ok", datetime(2026, 11, 3, 23, 30, tzinfo=timezone(timedelta(hours=-2))))
    assert pipeline.portales_pendientes([hoy, OK_FA], HOY) == []


def test_acepta_date():
    assert pipeline.portales_pendientes([(TE, "ok", HOY), (FA, "ok", HOY)], HOY) == []


# --- main contra BD ---
@pytest.fixture
def espia(monkeypatch):
    llamadas = []

    def falso(portal="tecnoempleo", **kw):
        llamadas.append((portal, kw))
        return 0
    monkeypatch.setattr(pipeline, "ejecutar", falso)
    return llamadas


@pytest.fixture
def prod(conn, db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    db.migrar(conn)
    return conn


def ejec(conn, portal, estado, fin=None):
    fin = fin or datetime.now(timezone.utc)
    db.registrar_ejecucion(conn, portal, fin - timedelta(minutes=1), fin, estado)


def test_main_salta_si_esta_hecho(prod, espia, capsys):
    ejec(prod, TE, "ok")
    ejec(prod, FA, "ok")
    assert pipeline.main(["--solo-si-falta"]) == 0
    assert espia == []
    assert "ya ejecutado" in capsys.readouterr().out


def test_main_ejecuta_solo_los_pendientes(prod, espia):
    ejec(prod, TE, "ok")
    assert pipeline.main(["--solo-si-falta"]) == 0
    assert [p for p, _ in espia] == [FA]
    assert espia[0][1]["dry_run"] is False and espia[0][1]["database_url"]


def test_main_error_hoy_se_reintenta(prod, espia):
    ejec(prod, TE, "error")
    ejec(prod, FA, "ok")
    pipeline.main(["--solo-si-falta"])
    assert [p for p, _ in espia] == [TE]


def test_main_bloqueado_hoy_no_se_reintenta(prod, espia):
    ejec(prod, TE, "bloqueado")
    ejec(prod, FA, "ok")
    assert pipeline.main(["--solo-si-falta"]) == 0
    assert espia == []


def test_main_ok_de_ayer_ejecuta_todo(prod, espia):
    ayer = datetime.now(timezone.utc) - timedelta(days=1, hours=1)
    ejec(prod, TE, "ok", ayer)
    ejec(prod, FA, "ok", ayer)
    pipeline.main(["--solo-si-falta"])
    assert sorted(p for p, _ in espia) == sorted(pipeline.PORTALES)


def test_main_respeta_portal(prod, espia):
    ejec(prod, TE, "ok")
    assert pipeline.main(["--solo-si-falta", "--portal", TE]) == 0
    assert espia == []
    assert pipeline.main(["--solo-si-falta", "--portal", FA]) == 0
    assert [p for p, _ in espia] == [FA]


def test_main_codigo_de_salida_peor(prod, monkeypatch):
    monkeypatch.setattr(pipeline, "ejecutar", lambda portal="x", **kw: 2 if portal == TE else 0)
    assert pipeline.main(["--solo-si-falta"]) == 2


def test_main_prod_vacia_migra_antes_de_consultar(conn, db_url, espia, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)  # `conn` ha dejado la BD sin tablas
    assert pipeline.main(["--solo-si-falta"]) == 0
    assert sorted(p for p, _ in espia) == sorted(pipeline.PORTALES)
    assert conn.execute("SELECT count(*) FROM schema_migraciones").fetchone()[0] == 5
    assert conn.execute("SELECT count(*) FROM ejecuciones").fetchone()[0] == 0


def test_main_bd_inaccesible_falla_abierto(monkeypatch, espia, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:SECRETO@localhost:1/x")
    assert pipeline.main(["--solo-si-falta"]) == 0
    assert [p for p, _ in espia] == ["todos"]
    out = capsys.readouterr()
    assert "SECRETO" not in out.out + out.err


def test_dry_run_ignora_solo_si_falta(prod, espia):
    ejec(prod, TE, "ok")
    ejec(prod, FA, "ok")
    assert pipeline.main(["--dry-run", "--solo-si-falta"]) == 0
    assert [(p, kw["dry_run"]) for p, kw in espia] == [("todos", True)]


def test_sin_la_opcion_siempre_ejecuta(prod, espia):
    ejec(prod, TE, "ok")
    ejec(prod, FA, "ok")
    pipeline.main([])
    assert [p for p, _ in espia] == ["todos"]


def test_extremo_a_extremo_idempotente(prod, monkeypatch, html_p1, html_p2):
    """Descarga falsa: falta tecnoempleo -> se ejecuta; la segunda vez ya esta hecho y no cambia nada."""
    ejec(prod, FA, "ok")
    f = Fetch({URL_BASE: html_p1, URL2: sin_siguiente(html_p2)})
    monkeypatch.setattr(pipeline, "descargar", f)
    orig = pipeline.recorrer
    monkeypatch.setattr(pipeline, "recorrer", lambda **kw: orig(**{**kw, "pausa_s": 0}))
    assert pipeline.main(["--solo-si-falta"]) == 0
    n_urls = len(f.urls)
    assert n_urls > 0
    ofertas = prod.execute("SELECT count(*) FROM ofertas").fetchone()[0]
    ejecs = prod.execute("SELECT count(*) FROM ejecuciones").fetchone()[0]
    assert ofertas == 60 and ejecs == 2
    assert pipeline.main(["--solo-si-falta"]) == 0
    assert len(f.urls) == n_urls  # no vuelve a descargar
    assert prod.execute("SELECT count(*) FROM ejecuciones").fetchone()[0] == ejecs
    assert prod.execute("SELECT count(*) FROM ofertas").fetchone()[0] == ofertas
