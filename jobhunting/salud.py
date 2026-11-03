"""Salud del pipeline: detecta portales rotos, caídas y crons que no corrieron, y sincroniza issues.

Uso: python -m jobhunting.salud --entorno prod|dev [--max-horas 28] [--sin-issues]
     (DATABASE_URL, GITHUB_TOKEN y GITHUB_REPOSITORY por entorno; nunca se imprimen)
Salida: 0 evaluado (haya o no alertas; las alertas van a issues); 1 error de BD o de la API de GitHub.

La evaluación (`evaluar`) es pura y determinista: recibe las ejecuciones y la hora y devuelve alertas.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from jobhunting.pipeline import PORTALES

TIPOS = ("sin_ejecucion", "error", "bloqueado", "cero", "caida", "descartes", "incompleto")
MAX_HORAS = 28          # el cron es diario (05:17 UTC) y puede retrasarse
UMBRAL_CAIDA = 0.5      # alerta si hoy < 50 % de la mediana de las últimas ejecuciones ok
MIN_HISTORIAL = 3       # ejecuciones ok previas necesarias para juzgar una caída
VENTANA = 7             # ejecuciones ok previas que entran en la mediana
UMBRAL_DESCARTES = 0.10  # alerta si se descarta > 10 % de las tarjetas
UMBRAL_INCOMPLETO = 0.80  # alerta si se guarda < 80 % del total que anuncia el portal


@dataclass(frozen=True)
class Ejecucion:
    portal: str
    fin: datetime
    estado: str
    n_ofertas: int = 0
    detalle: str | None = None
    n_descartadas: int = 0
    total_anunciado: int | None = None


@dataclass(frozen=True)
class Alerta:
    portal: str
    tipo: str
    mensaje: str

    @property
    def clave(self) -> str:
        return f"{self.portal}: {self.tipo}"


def _utc(d: datetime) -> datetime:
    if d.tzinfo is None or d.utcoffset() != timedelta(0):
        raise ValueError("las fechas deben ser tz-aware en UTC")
    return d


def evaluar_portal(portal: str, ejecuciones, ahora: datetime, max_horas: float | None = MAX_HORAS) -> list[Alerta]:
    """Alertas de un portal. `ejecuciones`: todas las del portal, en cualquier orden.
    max_horas=None desactiva la comprobación de latido (p. ej. en dev, que no tiene cron)."""
    _utc(ahora)
    ejs = sorted((e for e in ejecuciones if e.portal == portal), key=lambda e: _utc(e.fin), reverse=True)
    if not ejs:
        if max_horas is None:
            return []
        return [Alerta(portal, "sin_ejecucion", "No hay ninguna ejecución registrada.")]
    ult = ejs[0]
    if max_horas is not None and ahora - ult.fin > timedelta(hours=max_horas):
        horas = (ahora - ult.fin).total_seconds() / 3600
        return [Alerta(portal, "sin_ejecucion",
                       f"La última ejecución terminó hace {horas:.0f} h ({ult.fin:%Y-%m-%d %H:%M} UTC); "
                       f"el máximo es {max_horas:g} h. ¿Se ha desactivado o retrasado el cron?")]
    if ult.estado == "error":
        return [Alerta(portal, "error", f"La última ejecución falló: {ult.detalle or 'sin detalle'}.")]
    if ult.estado == "bloqueado":
        return [Alerta(portal, "bloqueado",
                       f"El portal bloqueó la descarga: {ult.detalle or 'sin detalle'}. "
                       "No se reintenta ni se salta la protección (regla 7).")]
    alertas = []
    n = ult.n_ofertas
    if n == 0:
        alertas.append(Alerta(portal, "cero",
                              "La última ejecución terminó bien pero guardó 0 ofertas: "
                              "probable selector o formato cambiado."))
    else:
        previas = [e.n_ofertas for e in ejs[1:] if e.estado == "ok" and e.n_ofertas > 0][:VENTANA]
        if len(previas) >= MIN_HISTORIAL:
            med = statistics.median(previas)
            if n < UMBRAL_CAIDA * med:
                alertas.append(Alerta(portal, "caida",
                                      f"Hoy {n} ofertas frente a una mediana de {med:g} en las últimas "
                                      f"{len(previas)} ejecuciones (< {UMBRAL_CAIDA:.0%})."))
    vistas = n + ult.n_descartadas
    if vistas and ult.n_descartadas > UMBRAL_DESCARTES * vistas:
        alertas.append(Alerta(portal, "descartes",
                              f"Se descartaron {ult.n_descartadas} de {vistas} tarjetas "
                              f"(> {UMBRAL_DESCARTES:.0%}): probable campo con selector roto."))
    if n and ult.total_anunciado and n < UMBRAL_INCOMPLETO * ult.total_anunciado:
        alertas.append(Alerta(portal, "incompleto",
                              f"Se guardaron {n} ofertas de {ult.total_anunciado} anunciadas "
                              f"(< {UMBRAL_INCOMPLETO:.0%}): probable paginación rota."))
    return alertas


def evaluar(ejecuciones, ahora: datetime, portales=PORTALES, max_horas: float | None = MAX_HORAS) -> list[Alerta]:
    ejecuciones = list(ejecuciones)
    return [a for p in portales for a in evaluar_portal(p, ejecuciones, ahora, max_horas)]


def cargar_ejecuciones(conn, portales=PORTALES, por_portal: int = VENTANA + 1) -> list[Ejecucion]:
    """Las `por_portal` ejecuciones más recientes de cada portal."""
    filas = conn.execute(
        """
        SELECT portal, fin, estado, n_ofertas, detalle, n_descartadas, total_anunciado FROM (
            SELECT *, row_number() OVER (PARTITION BY portal ORDER BY fin DESC) AS rn
            FROM ejecuciones WHERE portal = ANY(%s)
        ) t WHERE rn <= %s
        """,
        (list(portales), por_portal),
    ).fetchall()
    return [Ejecucion(*f) for f in filas]


def resumen(alertas, entorno: str) -> str:
    if not alertas:
        return f"## Salud ({entorno}): todo bien\n"
    return f"## Salud ({entorno}): {len(alertas)} alerta(s)\n" + "".join(
        f"- **{a.clave}**: {a.mensaje}\n" for a in alertas)


def main(argv=None, ahora=None, github=None) -> int:
    ap = argparse.ArgumentParser(prog="jobhunting.salud")
    ap.add_argument("--entorno", choices=["prod", "dev"], required=True)
    ap.add_argument("--max-horas", type=float, default=MAX_HORAS,
                    help="latido: horas máximas sin ejecución; 0 lo desactiva")
    ap.add_argument("--sin-issues", action="store_true", help="solo evalúa e imprime")
    a = ap.parse_args(argv)
    from jobhunting import alertas as gh_alertas
    from jobhunting import db

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Falta DATABASE_URL", file=sys.stderr)
        return 1
    try:
        conn = db.conectar(url)
        try:
            db.migrar(conn)
            ejs = cargar_ejecuciones(conn)
        finally:
            conn.close()
    except Exception as e:
        print(f"Error de BD: {type(e).__name__}", file=sys.stderr)
        return 1
    ahora = ahora or datetime.now(timezone.utc)
    lista = evaluar(ejs, ahora, max_horas=a.max_horas or None)
    texto = resumen(lista, a.entorno)
    print(texto)
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(texto + "\n")
    if a.sin_issues:
        return 0
    try:
        cambios = gh_alertas.sincronizar(lista, a.entorno, http=github)
    except Exception as e:
        print(f"Error al sincronizar issues: {type(e).__name__}: {str(e)[:200]}", file=sys.stderr)
        return 1
    print(f"Issues: {cambios['abiertos']} abiertos, {cambios['cerrados']} cerrados, "
          f"{cambios['sin_cambios']} sin cambios")
    return 0


if __name__ == "__main__":
    sys.exit(main())
