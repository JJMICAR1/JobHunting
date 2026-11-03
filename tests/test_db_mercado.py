"""Migracion 004: n_desaparecidas y vistas v_mercado_* (requiere TEST_DATABASE_URL)."""
from datetime import date, timedelta

from conftest import utc
from jobhunting import db

HOY = date(2026, 11, 10)


def oferta(conn, i, vista_dia, portal="tecnoempleo", primera=None):
    """Oferta cuya ultima_vez cae en `vista_dia` (UTC, tz-aware)."""
    uv = utc(vista_dia.year, vista_dia.month, vista_dia.day, 10, 0)
    pv = primera or uv
    conn.execute("INSERT INTO ofertas (portal,id_portal,titulo,url,primera_vez,ultima_vez) "
                 "VALUES (%s,%s,'T','https://x/y',%s,%s)", (portal, f"{portal}-{i}", pv, uv))


def rec(conn, dia, portal, vistas, unicas=None, nuevas=0):
    conn.execute("INSERT INTO recuento_diario (dia,portal,n_vistas,n_nuevas,n_unicas) VALUES (%s,%s,%s,%s,%s)",
                 (dia, portal, vistas, nuevas, unicas if unicas is not None else vistas))


def desaparecidas(conn, dia, portal="tecnoempleo"):
    return conn.execute("SELECT n_desaparecidas FROM recuento_diario WHERE dia=%s AND portal=%s",
                        (dia, portal)).fetchone()[0]


def test_migrar_dos_veces_004(conn):
    assert "004_mercado" in db.migrar(conn)
    assert db.migrar(conn) == []
    cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns "
                                       "WHERE table_name='recuento_diario'").fetchall()}
    assert "n_desaparecidas" in cols
    vistas = {r[0] for r in conn.execute("SELECT table_name FROM information_schema.views "
                                         "WHERE table_schema = current_schema()").fetchall()}
    assert {"v_mercado_diario", "v_mercado_hoy"} <= vistas


def test_sin_recuento_previo_es_null(conn):
    db.migrar(conn)
    oferta(conn, 1, HOY)
    assert db.registrar_recuento(conn, HOY, "tecnoempleo") == (1, 1, 1)
    assert desaparecidas(conn, HOY) is None


def test_recuento_previo_de_ayer(conn):
    db.migrar(conn)
    ayer = HOY - timedelta(days=1)
    for i in (1, 2, 3):
        oferta(conn, i, ayer)       # vistas ayer, no hoy -> desaparecidas
    oferta(conn, 4, HOY)            # sigue viva
    oferta(conn, 5, HOY - timedelta(days=5))   # anterior al recuento previo: no cuenta
    rec(conn, ayer, "tecnoempleo", 3)
    db.registrar_recuento(conn, HOY, "tecnoempleo")
    assert desaparecidas(conn, HOY) == 3


def test_recuento_previo_con_hueco(conn):
    db.migrar(conn)
    ant = HOY - timedelta(days=3)
    rec(conn, ant, "tecnoempleo", 1)
    oferta(conn, 1, ant)                          # vista el dia del recuento previo: cuenta
    oferta(conn, 2, HOY - timedelta(days=2))      # en el hueco: cuenta
    oferta(conn, 3, HOY - timedelta(days=1))      # en el hueco: cuenta
    oferta(conn, 4, ant - timedelta(days=1))      # antes del recuento previo: no
    oferta(conn, 5, HOY)                          # hoy: no
    db.registrar_recuento(conn, HOY, "tecnoempleo")
    assert desaparecidas(conn, HOY) == 3


def test_recalcular_mismo_dia_idempotente(conn):
    db.migrar(conn)
    ayer = HOY - timedelta(days=1)
    rec(conn, ayer, "tecnoempleo", 2)
    oferta(conn, 1, ayer)
    oferta(conn, 2, HOY)
    r1 = db.registrar_recuento(conn, HOY, "tecnoempleo")
    estado1 = conn.execute("SELECT * FROM recuento_diario ORDER BY dia").fetchall()
    assert db.registrar_recuento(conn, HOY, "tecnoempleo") == r1
    assert conn.execute("SELECT * FROM recuento_diario ORDER BY dia").fetchall() == estado1
    assert len(estado1) == 2 and desaparecidas(conn, HOY) == 1


def test_recuento_no_usa_dias_posteriores_como_previo(conn):
    """Recalcular un dia antiguo ignora recuentos posteriores (dia < hoy estricto)."""
    db.migrar(conn)
    rec(conn, HOY + timedelta(days=1), "tecnoempleo", 9)
    oferta(conn, 1, HOY)
    db.registrar_recuento(conn, HOY, "tecnoempleo")
    assert desaparecidas(conn, HOY) is None


def test_deltas_1d_7d(conn):
    db.migrar(conn)
    rec(conn, HOY - timedelta(days=7), "tecnoempleo", 100, unicas=90)
    rec(conn, HOY - timedelta(days=1), "tecnoempleo", 110, unicas=95)
    rec(conn, HOY, "tecnoempleo", 120, unicas=100)
    fila = conn.execute("SELECT d_vistas_1d, d_vistas_7d, d_unicas_1d, d_unicas_7d FROM v_mercado_diario "
                        "WHERE dia=%s", (HOY,)).fetchone()
    assert fila == (10, 20, 5, 10)


def test_deltas_null_si_falta_el_dia_exacto(conn):
    db.migrar(conn)
    rec(conn, HOY - timedelta(days=2), "tecnoempleo", 100)   # ni 1d ni 7d exactos
    rec(conn, HOY - timedelta(days=8), "tecnoempleo", 100)
    rec(conn, HOY, "tecnoempleo", 120)
    fila = conn.execute("SELECT d_vistas_1d, d_vistas_7d, d_unicas_1d, d_unicas_7d FROM v_mercado_diario "
                        "WHERE dia=%s", (HOY,)).fetchone()
    assert fila == (None, None, None, None)


def test_deltas_negativos(conn):
    db.migrar(conn)
    rec(conn, HOY - timedelta(days=1), "tecnoempleo", 50)
    rec(conn, HOY, "tecnoempleo", 40)
    assert conn.execute("SELECT d_vistas_1d FROM v_mercado_diario WHERE dia=%s", (HOY,)).fetchone()[0] == -10


def test_hoy_es_el_ultimo_dia_por_portal(conn):
    db.migrar(conn)
    rec(conn, HOY - timedelta(days=1), "tecnoempleo", 10)
    rec(conn, HOY, "tecnoempleo", 12)
    rec(conn, HOY - timedelta(days=4), "feinaactiva", 5)
    rec(conn, HOY - timedelta(days=3), "feinaactiva", 7)
    filas = conn.execute("SELECT portal, dia, n_vistas FROM v_mercado_hoy ORDER BY portal").fetchall()
    assert filas == [("feinaactiva", HOY - timedelta(days=3), 7), ("tecnoempleo", HOY, 12)]


def test_aislamiento_entre_portales(conn):
    db.migrar(conn)
    rec(conn, HOY - timedelta(days=1), "feinaactiva", 1000)   # no debe contar para tecnoempleo
    rec(conn, HOY, "tecnoempleo", 12)
    t = conn.execute("SELECT d_vistas_1d FROM v_mercado_hoy WHERE portal='tecnoempleo'").fetchone()
    assert t == (None,)
    # y desaparecidas tampoco mezcla portales
    oferta(conn, 1, HOY - timedelta(days=1), portal="feinaactiva")
    rec(conn, HOY - timedelta(days=1), "tecnoempleo", 1)
    oferta(conn, 2, HOY - timedelta(days=1), portal="tecnoempleo")
    db.registrar_recuento(conn, HOY, "tecnoempleo")
    assert desaparecidas(conn, HOY) == 1


def test_fechas_utc_tz_aware(conn):
    """El dia se toma en UTC: 23:30 UTC del dia anterior no es 'hoy'."""
    db.migrar(conn)
    conn.execute("INSERT INTO ofertas (portal,id_portal,titulo,url,primera_vez,ultima_vez) "
                 "VALUES ('tecnoempleo','a','T','https://x',%s,%s)",
                 (utc(2026, 11, 9, 23, 30), utc(2026, 11, 9, 23, 30)))
    conn.execute("INSERT INTO ofertas (portal,id_portal,titulo,url,primera_vez,ultima_vez) "
                 "VALUES ('tecnoempleo','b','T','https://x',%s,%s)",
                 (utc(2026, 11, 10, 0, 30), utc(2026, 11, 10, 0, 30)))
    rec(conn, date(2026, 11, 9), "tecnoempleo", 1)
    assert db.registrar_recuento(conn, HOY, "tecnoempleo")[0] == 1
    assert desaparecidas(conn, HOY) == 1
