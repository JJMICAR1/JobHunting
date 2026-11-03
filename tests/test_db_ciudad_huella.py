"""Migracion 002, huella, grupos y vistas (requiere TEST_DATABASE_URL)."""
from datetime import date

import psycopg
import pytest

from conftest import utc
from jobhunting import db
from jobhunting.modelo import Oferta

T1 = utc(2026, 11, 3, 8, 0)


def of(i, **kw):
    base = dict(portal="tecnoempleo", id_portal=f"rf-{i}", titulo="Programador/a Java",
                url=f"https://www.tecnoempleo.com/x/rf-{i}", empresa="ACME",
                ubicacion="Barcelona (Híbrido)", ciudad="Barcelona", modalidad="hibrido")
    base.update(kw)
    return Oferta(**base)


def test_migracion_001_a_002_conserva_filas(conn):
    conn.execute("CREATE TABLE schema_migraciones (version text PRIMARY KEY, "
                 "aplicada timestamptz NOT NULL DEFAULT now())")
    conn.execute((db.DIR_MIGRACIONES / "001_inicial.sql").read_text(encoding="utf-8"))
    conn.execute("INSERT INTO schema_migraciones (version) VALUES ('001_inicial')")
    for i in range(3):
        conn.execute("INSERT INTO ofertas (portal,id_portal,titulo,url,empresa,ubicacion,primera_vez,ultima_vez) "
                     "VALUES ('tecnoempleo',%s,'T','https://x/y','E','Barcelona',%s,%s)", (f"rf-{i}", T1, T1))
    conn.execute("INSERT INTO recuento_diario (dia,portal,n_vistas,n_nuevas) VALUES ('2026-11-03','tecnoempleo',3,3)")
    assert db.migrar(conn) == ["002_ciudad_modalidad_huella", "003_ejecuciones_salud"]
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM ofertas WHERE ciudad IS NULL AND modalidad IS NULL "
                        "AND huella IS NULL").fetchone()[0] == 3
    assert conn.execute("SELECT n_vistas, n_nuevas, n_unicas FROM recuento_diario").fetchone() == (3, 3, None)
    assert db.migrar(conn) == []


def test_check_rechaza_modalidad_invalida(conn):
    db.migrar(conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO ofertas (portal,id_portal,titulo,url,primera_vez,ultima_vez,modalidad) "
                     "VALUES ('t','1','T','https://x',%s,%s,'volando')", (T1, T1))


def test_misma_huella_no_se_fusiona_y_se_agrupa(conn):
    db.migrar(conn)
    a, b = of(1), of(2, titulo="Programador Java", empresa="acme")
    assert a.huella == b.huella
    assert db.guardar_ofertas(conn, [a, b], T1) == (2, 2)
    assert conn.execute("SELECT count(*) FROM ofertas").fetchone()[0] == 2
    assert conn.execute("SELECT count(DISTINCT huella) FROM ofertas").fetchone()[0] == 1
    g = conn.execute("SELECT portal, huella, n_publicaciones, ids, ciudad FROM v_grupos_ofertas").fetchall()
    assert g == [("tecnoempleo", a.huella, 2, ["rf-1", "rf-2"], "Barcelona")]
    assert db.registrar_recuento(conn, date(2026, 11, 3), "tecnoempleo") == (2, 2, 1)
    # idempotente
    assert db.guardar_ofertas(conn, [a, b], T1) == (2, 0)
    assert db.registrar_recuento(conn, date(2026, 11, 3), "tecnoempleo") == (2, 2, 1)
    assert conn.execute("SELECT count(*) FROM v_grupos_ofertas").fetchone()[0] == 1


def test_grupos_excluye_unicas_y_huella_null(conn):
    db.migrar(conn)
    db.guardar_ofertas(conn, [of(1), of(2, empresa="OTRA")], T1)
    assert conn.execute("SELECT count(*) FROM v_grupos_ofertas").fetchone()[0] == 0


def test_v_mercado_ciudad_modalidad(conn):
    db.migrar(conn)
    ofs = [of(1), of(2),  # misma huella
           of(3, titulo="Otro", ciudad="Barcelona", modalidad=None),
           of(4, titulo="Remoto", ciudad=None, modalidad="remoto"),
           of(5, titulo="Nada", ciudad=None, modalidad=None)]
    db.guardar_ofertas(conn, ofs, T1)
    filas = set(conn.execute("SELECT portal, ciudad, modalidad, n_ofertas, n_unicas "
                             "FROM v_mercado_ciudad_modalidad").fetchall())
    assert filas == {
        ("tecnoempleo", "Barcelona", "hibrido", 2, 1),
        ("tecnoempleo", "Barcelona", "(sin indicar)", 1, 1),
        ("tecnoempleo", "(sin ciudad)", "remoto", 1, 1),
        ("tecnoempleo", "(sin ciudad)", "(sin indicar)", 1, 1),
    }


def test_upsert_corrige_ciudad_modalidad_huella_de_fila_existente(conn):
    """Caso real: filas guardadas sin ubicacion estructurada se corrigen al re-ver la oferta."""
    db.migrar(conn)
    conn.execute("INSERT INTO ofertas (portal,id_portal,titulo,url,empresa,ubicacion,primera_vez,ultima_vez) "
                 "VALUES ('tecnoempleo','rf-1','Programador/a Java','https://www.tecnoempleo.com/x/rf-1',"
                 "'ACME','Barcelona (Híbrido)',%s,%s)", (T1, T1))
    o = of(1)
    assert db.guardar_ofertas(conn, [o], utc(2026, 11, 4, 8)) == (1, 0)
    assert conn.execute("SELECT ciudad, modalidad, huella, primera_vez FROM ofertas").fetchone() == \
        ("Barcelona", "hibrido", o.huella, T1)
    assert len(o.huella) == 16


def test_recuento_cuenta_huella_null_por_fila(conn):
    db.migrar(conn)
    for i in (1, 2):
        conn.execute("INSERT INTO ofertas (portal,id_portal,titulo,url,primera_vez,ultima_vez) "
                     "VALUES ('tecnoempleo',%s,'T','https://x',%s,%s)", (f"rf-{i}", T1, T1))
    assert db.registrar_recuento(conn, date(2026, 11, 3), "tecnoempleo") == (2, 2, 2)


def test_no_quedan_vistas_entre_tests(conn):
    """El DROP ... CASCADE del conftest debe llevarse las vistas de 002."""
    n = conn.execute("SELECT count(*) FROM information_schema.views WHERE table_schema = current_schema()"
                     ).fetchone()[0]
    assert n == 0
    db.migrar(conn)
    assert conn.execute("SELECT count(*) FROM information_schema.views WHERE table_schema = current_schema()"
                        ).fetchone()[0] == 2
