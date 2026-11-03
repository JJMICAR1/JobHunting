"""Capa Postgres (Neon). Fechas siempre UTC tz-aware; se rechazan datetimes naive.

La URL de conexion llega por variable de entorno y nunca se imprime ni se registra.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg

from jobhunting.modelo import deduplicar

DIR_MIGRACIONES = Path(__file__).resolve().parent.parent / "migraciones"
ESTADOS = ("ok", "bloqueado", "error")


def _utc(d: datetime, nombre: str = "fecha") -> datetime:
    if not isinstance(d, datetime) or d.tzinfo is None or d.utcoffset() != timedelta(0):
        raise ValueError(f"{nombre} debe ser datetime tz-aware en UTC")
    return d


def conectar(url: str) -> psycopg.Connection:
    if not url:
        raise ValueError("URL de base de datos vacia")
    try:
        conn = psycopg.connect(url)
    except psycopg.Error as e:
        # No propagamos el mensaje original: podria incluir host/usuario.
        raise RuntimeError(f"no se pudo conectar a la base de datos ({type(e).__name__})") from None
    conn.execute("SET TIME ZONE 'UTC'")
    conn.commit()
    return conn


def migrar(conn: psycopg.Connection) -> list[str]:
    """Aplica migraciones pendientes en orden. Devuelve las versiones aplicadas ahora."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migraciones ("
        "version text PRIMARY KEY, aplicada timestamptz NOT NULL DEFAULT now())"
    )
    conn.commit()
    hechas = {r[0] for r in conn.execute("SELECT version FROM schema_migraciones")}
    nuevas = []
    for f in sorted(DIR_MIGRACIONES.glob("*.sql")):
        if f.name.endswith(".down.sql") or f.stem in hechas:
            continue
        with conn.transaction():
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO schema_migraciones (version, aplicada) VALUES (%s, now()) "
                "ON CONFLICT (version) DO NOTHING",
                (f.stem,),
            )
        nuevas.append(f.stem)
    return nuevas


_UPSERT = """
INSERT INTO ofertas (portal, id_portal, titulo, url, empresa, ubicacion,
                     fecha_publicacion, primera_vez, ultima_vez)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (portal, id_portal) DO UPDATE SET
    titulo = EXCLUDED.titulo,
    url = EXCLUDED.url,
    empresa = EXCLUDED.empresa,
    ubicacion = EXCLUDED.ubicacion,
    fecha_publicacion = COALESCE(EXCLUDED.fecha_publicacion, ofertas.fecha_publicacion),
    ultima_vez = GREATEST(ofertas.ultima_vez, EXCLUDED.ultima_vez)
RETURNING (xmax = 0)
"""


def guardar_ofertas(conn: psycopg.Connection, ofertas, ahora_utc: datetime) -> tuple[int, int]:
    """Upsert por (portal, id_portal). Devuelve (n_vistas, n_nuevas) de esta llamada."""
    _utc(ahora_utc, "ahora_utc")
    unicas = deduplicar(list(ofertas))
    nuevas = 0
    with conn.transaction():
        with conn.cursor() as cur:
            for o in unicas:
                cur.execute(
                    _UPSERT,
                    (o.portal, o.id_portal, o.titulo, o.url, o.empresa, o.ubicacion,
                     o.fecha_publicacion, ahora_utc, ahora_utc),
                )
                if cur.fetchone()[0]:
                    nuevas += 1
    return len(unicas), nuevas


def registrar_recuento(conn: psycopg.Connection, dia: date, portal: str) -> tuple[int, int]:
    """Recalcula en SQL el recuento del dia UTC (idempotente aunque se ejecute varias veces).

    n_vistas = ofertas con ultima_vez en ese dia; n_nuevas = ofertas con primera_vez en ese dia.
    Debe llamarse el mismo dia UTC de la captura (ultima_vez solo guarda la ultima vista).
    """
    if isinstance(dia, datetime) or not isinstance(dia, date):
        raise ValueError("dia debe ser date (UTC)")
    with conn.transaction():
        fila = conn.execute(
            """
            INSERT INTO recuento_diario (dia, portal, n_vistas, n_nuevas)
            SELECT %(dia)s, %(portal)s,
                   count(*) FILTER (WHERE (ultima_vez AT TIME ZONE 'UTC')::date = %(dia)s),
                   count(*) FILTER (WHERE (primera_vez AT TIME ZONE 'UTC')::date = %(dia)s)
            FROM ofertas WHERE portal = %(portal)s
            ON CONFLICT (dia, portal) DO UPDATE SET
                n_vistas = EXCLUDED.n_vistas, n_nuevas = EXCLUDED.n_nuevas
            RETURNING n_vistas, n_nuevas
            """,
            {"dia": dia, "portal": portal},
        ).fetchone()
    return fila[0], fila[1]


def registrar_ejecucion(conn: psycopg.Connection, portal: str, inicio: datetime, fin: datetime,
                        estado: str, n_ofertas: int = 0, detalle: str | None = None) -> int:
    _utc(inicio, "inicio")
    _utc(fin, "fin")
    if estado not in ESTADOS:
        raise ValueError(f"estado debe ser uno de {ESTADOS}")
    with conn.transaction():
        return conn.execute(
            "INSERT INTO ejecuciones (portal, inicio, fin, estado, n_ofertas, detalle) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (portal, inicio, fin, estado, n_ofertas, detalle),
        ).fetchone()[0]
