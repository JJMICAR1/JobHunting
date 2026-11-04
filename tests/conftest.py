"""Fixtures comunes: sin red por defecto y BD de pruebas opcional (TEST_DATABASE_URL)."""
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tecnoempleo"


@pytest.fixture(autouse=True)
def _sin_red(request, monkeypatch):
    """Cualquier intento de red falla, salvo en tests live o con BD local."""
    if request.node.get_closest_marker("live"):
        return
    real = socket.socket.connect

    def connect(self, addr, *a, **k):
        # Se permiten solo sockets locales (Postgres de pruebas / unix).
        if isinstance(addr, tuple) and addr[0] not in ("localhost", "127.0.0.1", "::1"):
            raise AssertionError(f"intento de red en test: {addr!r}")
        return real(self, addr, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", connect)


@pytest.fixture(autouse=True)
def _cache_robots_limpia():
    """La cache de robots.txt de la sonda no debe filtrarse entre tests."""
    from tests import test_sonda
    test_sonda.sonda.vaciar_cache_robots()
    yield
    test_sonda.sonda.vaciar_cache_robots()


@pytest.fixture(scope="session")
def html_p1():
    return (FIXTURES / "listado_catalunya_p1.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def html_p2():
    return (FIXTURES / "listado_catalunya_p2.html").read_text(encoding="utf-8")


@pytest.fixture
def db_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL no definida")
    return url


@pytest.fixture
def conn(db_url):
    from jobhunting import db
    c = db.conectar(db_url)
    c.execute("DROP TABLE IF EXISTS ofertas, recuento_diario, ejecuciones, avisos, schema_migraciones CASCADE")
    yield c
    c.execute("DROP TABLE IF EXISTS ofertas, recuento_diario, ejecuciones, avisos, schema_migraciones CASCADE")
    c.close()


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)
