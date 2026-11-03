"""guardar_ofertas por lotes (executemany returning + nextset)."""
import pytest

from jobhunting import db
from test_db import of, T1, T2


def n_filas(conn):
    return conn.execute("SELECT count(*) FROM ofertas").fetchone()[0]


def test_1201_cruza_lotes_e_idempotente(conn):
    db.migrar(conn)
    ofs = [of(i) for i in range(1201)]  # lotes 500+500+201
    assert db.guardar_ofertas(conn, ofs, T1) == (1201, 1201)
    assert db.guardar_ofertas(conn, ofs, T2) == (1201, 0)
    assert n_filas(conn) == 1201


@pytest.mark.parametrize("n", [6, 7, 8, 14, 15])
def test_limites_de_lote_pequeno(conn, monkeypatch, n):
    monkeypatch.setattr(db, "_LOTE", 7)
    db.migrar(conn)
    ofs = [of(i) for i in range(n)]
    assert db.guardar_ofertas(conn, ofs, T1) == (n, n)
    assert db.guardar_ofertas(conn, ofs, T2) == (n, 0)
    assert n_filas(conn) == n


def test_mezcla_nuevas_y_existentes_en_mismo_lote(conn, monkeypatch):
    monkeypatch.setattr(db, "_LOTE", 7)
    db.migrar(conn)
    assert db.guardar_ofertas(conn, [of(i) for i in (1, 3, 5, 8, 12)], T1) == (5, 5)
    ofs = [of(i) for i in range(16)]  # existentes intercaladas entre lotes
    assert db.guardar_ofertas(conn, ofs, T2) == (16, 11)
    assert n_filas(conn) == 16
    primeras = dict(conn.execute("SELECT id_portal, primera_vez FROM ofertas").fetchall())
    assert primeras["rf-3"] == T1 and primeras["rf-4"] == T2


def test_lista_vacia(conn):
    db.migrar(conn)
    assert db.guardar_ofertas(conn, [], T1) == (0, 0)
    assert db.guardar_ofertas(conn, iter([]), T1) == (0, 0)
    assert n_filas(conn) == 0
    assert conn.info.transaction_status.name == "IDLE"


def test_duplicados_en_entrada(conn, monkeypatch):
    monkeypatch.setattr(db, "_LOTE", 3)
    db.migrar(conn)
    ofs = [of(i % 5) for i in range(20)]
    assert db.guardar_ofertas(conn, ofs, T1) == (5, 5)
    assert n_filas(conn) == 5
    assert db.guardar_ofertas(conn, ofs, T2) == (5, 0)
