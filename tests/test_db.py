from datetime import date, datetime, timedelta, timezone

import pytest

from conftest import utc
from jobhunting import db
from jobhunting.modelo import Oferta

T1 = utc(2026, 11, 3, 8, 0)
T2 = utc(2026, 11, 3, 20, 0)


def of(i, **kw):
    base = dict(portal="tecnoempleo", id_portal=f"rf-{i}", titulo=f"Oferta {i}",
                url=f"https://www.tecnoempleo.com/x/rf-{i}", empresa="ACME", ubicacion="Barcelona",
                fecha_publicacion=utc(2026, 11, 3))
    base.update(kw)
    return Oferta(**base)


def esquema(conn):
    return conn.execute(
        "SELECT table_name, column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() ORDER BY 1, 2").fetchall()


def test_migrar_dos_veces(conn):
    nuevas = db.migrar(conn)
    assert nuevas == ["001_inicial", "002_ciudad_modalidad_huella"]
    e1 = esquema(conn)
    assert db.migrar(conn) == []
    assert esquema(conn) == e1
    assert conn.execute("SELECT count(*) FROM schema_migraciones").fetchone()[0] == 2
    tablas = {r[0] for r in e1}
    assert {"ofertas", "recuento_diario", "ejecuciones", "schema_migraciones"} <= tablas


def test_conectar_url_vacia():
    with pytest.raises(ValueError):
        db.conectar("")


def test_conectar_error_no_filtra_url():
    with pytest.raises(RuntimeError) as e:
        db.conectar("postgresql://usuario:s3cr3t@localhost:1/nada")
    assert "s3cr3t" not in str(e.value) and "usuario" not in str(e.value)


def test_guardar_dos_veces_idempotente(conn):
    db.migrar(conn)
    ofs = [of(i) for i in range(5)]
    assert db.guardar_ofertas(conn, ofs, T1) == (5, 5)
    assert db.guardar_ofertas(conn, ofs, T2) == (5, 0)
    filas = conn.execute("SELECT id_portal, primera_vez, ultima_vez FROM ofertas").fetchall()
    assert len(filas) == 5
    for _, primera, ultima in filas:
        assert primera == T1
        assert ultima == T2


def test_guardar_deduplica_y_actualiza_campos(conn):
    db.migrar(conn)
    assert db.guardar_ofertas(conn, [of(1), of(1, titulo="otro")], T1) == (1, 1)
    db.guardar_ofertas(conn, [of(1, titulo="Nuevo titulo", fecha_publicacion=None)], T2)
    t, fp = conn.execute("SELECT titulo, fecha_publicacion FROM ofertas").fetchone()
    assert t == "Nuevo titulo"
    assert fp == utc(2026, 11, 3)  # COALESCE conserva la fecha previa


def test_ultima_vez_no_retrocede(conn):
    db.migrar(conn)
    db.guardar_ofertas(conn, [of(1)], T2)
    db.guardar_ofertas(conn, [of(1)], T1)
    assert conn.execute("SELECT ultima_vez FROM ofertas").fetchone()[0] == T2


def test_fechas_devueltas_en_utc(conn):
    db.migrar(conn)
    db.guardar_ofertas(conn, [of(1)], T1)
    v = conn.execute("SELECT primera_vez FROM ofertas").fetchone()[0]
    assert v.utcoffset() == timedelta(0)


def test_naive_rechazado(conn):
    db.migrar(conn)
    naive = datetime(2026, 11, 3, 8, 0)
    with pytest.raises(ValueError):
        db.guardar_ofertas(conn, [of(1)], naive)
    with pytest.raises(ValueError):
        db.guardar_ofertas(conn, [of(1)], datetime(2026, 11, 3, tzinfo=timezone(timedelta(hours=2))))
    with pytest.raises(ValueError):
        db.registrar_ejecucion(conn, "tecnoempleo", naive, T1, "ok")
    with pytest.raises(ValueError):
        db.registrar_ejecucion(conn, "tecnoempleo", T1, naive, "ok")
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 0


def test_registrar_recuento_idempotente(conn):
    db.migrar(conn)
    db.guardar_ofertas(conn, [of(i) for i in range(4)], T1)
    dia = date(2026, 11, 3)
    assert db.registrar_recuento(conn, dia, "tecnoempleo") == (4, 4, 4)
    db.guardar_ofertas(conn, [of(i) for i in range(4)], T2)
    assert db.registrar_recuento(conn, dia, "tecnoempleo") == (4, 4, 4)
    assert db.registrar_recuento(conn, dia, "tecnoempleo") == (4, 4, 4)
    assert conn.execute("SELECT count(*) FROM recuento_diario").fetchone()[0] == 1


def test_recuento_dia_siguiente(conn):
    db.migrar(conn)
    db.guardar_ofertas(conn, [of(1), of(2)], T1)
    db.guardar_ofertas(conn, [of(2), of(3)], T1 + timedelta(days=1))
    assert db.registrar_recuento(conn, date(2026, 11, 4), "tecnoempleo") == (2, 1, 2)


def test_recuento_dia_datetime_rechazado(conn):
    db.migrar(conn)
    with pytest.raises(ValueError):
        db.registrar_recuento(conn, T1, "tecnoempleo")


def test_registrar_ejecucion_estado_invalido(conn):
    db.migrar(conn)
    with pytest.raises(ValueError):
        db.registrar_ejecucion(conn, "tecnoempleo", T1, T2, "raro")
    i = db.registrar_ejecucion(conn, "tecnoempleo", T1, T2, "ok", 3, None)
    assert isinstance(i, int)
