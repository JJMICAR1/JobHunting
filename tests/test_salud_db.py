"""Fase 5: columnas de salud en ejecuciones, carga de ejecuciones y pipeline."""
from datetime import timedelta

from conftest import utc
from jobhunting import db, pipeline, salud
from test_pipeline import URL2, Fetch, reloj, run, sin_siguiente  # noqa: F401
from jobhunting.portales.tecnoempleo.scraper import URL_BASE

T = utc(2026, 11, 3, 8)


def columnas(conn):
    return {r[0]: r[1:] for r in conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_name='ejecuciones' AND table_schema=current_schema()")}


def test_migracion_003_columnas(conn):
    assert "003_ejecuciones_salud" in db.migrar(conn)
    c = columnas(conn)
    assert c["n_descartadas"][0] == "integer" and c["n_descartadas"][1] == "NO"
    assert c["n_descartadas"][2].strip("()") == "0"
    assert c["total_anunciado"][0] == "integer" and c["total_anunciado"][1] == "YES"
    assert db.migrar(conn) == []


def test_migracion_003_conserva_filas_antiguas(conn):
    conn.execute("CREATE TABLE schema_migraciones (version text PRIMARY KEY, "
                 "aplicada timestamptz NOT NULL DEFAULT now())")
    for v in ("001_inicial", "002_ciudad_modalidad_huella"):
        conn.execute((db.DIR_MIGRACIONES / f"{v}.sql").read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migraciones (version) VALUES (%s)", (v,))
    conn.execute("INSERT INTO ejecuciones (portal,inicio,fin,estado,n_ofertas) "
                 "VALUES ('tecnoempleo',%s,%s,'ok',5)", (T, T))
    assert db.migrar(conn) == ["003_ejecuciones_salud", "004_mercado"]
    assert conn.execute("SELECT n_ofertas, n_descartadas, total_anunciado FROM ejecuciones").fetchone() \
        == (5, 0, None)


def test_registrar_ejecucion_con_campos(conn):
    db.migrar(conn)
    db.registrar_ejecucion(conn, "tecnoempleo", T, T, "ok", 60, None, n_descartadas=7, total_anunciado=640)
    assert conn.execute("SELECT n_ofertas, n_descartadas, total_anunciado FROM ejecuciones").fetchone() \
        == (60, 7, 640)


def test_registrar_ejecucion_sin_campos(conn):
    db.migrar(conn)
    db.registrar_ejecucion(conn, "tecnoempleo", T, T, "error", detalle="x")
    assert conn.execute("SELECT n_ofertas, n_descartadas, total_anunciado, detalle FROM ejecuciones"
                        ).fetchone() == (0, 0, None, "x")


def test_cargar_ejecuciones_limite_y_recientes(conn):
    db.migrar(conn)
    for i in range(12):  # i mayor = más reciente
        db.registrar_ejecucion(conn, "tecnoempleo", T + timedelta(days=i), T + timedelta(days=i), "ok", i)
    for i in range(2):
        db.registrar_ejecucion(conn, "feinaactiva", T + timedelta(days=i), T + timedelta(days=i), "ok", 100 + i)
    db.registrar_ejecucion(conn, "otro", T, T, "ok", 1)
    r = salud.cargar_ejecuciones(conn, por_portal=5)
    te = sorted(e.n_ofertas for e in r if e.portal == "tecnoempleo")
    assert te == [7, 8, 9, 10, 11]
    assert sum(1 for e in r if e.portal == "feinaactiva") == 2
    assert not any(e.portal == "otro" for e in r)
    assert all(e.fin.utcoffset() == timedelta(0) for e in r)
    assert len(salud.cargar_ejecuciones(conn)) == 8 + 2  # por defecto VENTANA+1


def test_cargar_ejecuciones_devuelve_campos(conn):
    db.migrar(conn)
    db.registrar_ejecucion(conn, "tecnoempleo", T, T, "ok", 60, "d", n_descartadas=3, total_anunciado=100)
    e = salud.cargar_ejecuciones(conn)[0]
    assert e == salud.Ejecucion("tecnoempleo", T, "ok", 60, "d", 3, 100)


def test_pipeline_guarda_campos_de_salud(conn, db_url, html_p1, html_p2):
    f = Fetch({URL_BASE: html_p1, URL2: sin_siguiente(html_p2)})
    assert run(f, db_url) == 0
    n, desc, tot = conn.execute("SELECT n_ofertas, n_descartadas, total_anunciado FROM ejecuciones").fetchone()
    assert n == 60 and tot == 640 and isinstance(desc, int) and desc >= 0
    assert pipeline.PORTALES  # sanity


def test_pipeline_error_guarda_ceros(conn, db_url):
    assert run(Fetch({URL_BASE: "<html>x</html>"}), db_url) == 1
    assert conn.execute("SELECT n_ofertas, n_descartadas, total_anunciado FROM ejecuciones").fetchone() \
        == (0, 0, None)


def test_cargar_ejecuciones_fallback_sin_003(conn):
    db.migrar(conn)
    db.registrar_ejecucion(conn, "tecnoempleo", T, T, "ok", 60, "d", n_descartadas=3, total_anunciado=100)
    conn.execute("ALTER TABLE ejecuciones DROP COLUMN n_descartadas, DROP COLUMN total_anunciado")
    assert salud.cargar_ejecuciones(conn) == [salud.Ejecucion("tecnoempleo", T, "ok", 60, "d", 0, None)]
