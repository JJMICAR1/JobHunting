"""Recuento de mercado diario por Telegram (solo enviar, Bot API). Lee la vista `v_mercado_hoy`.

Uso: python -m jobhunting.mercado --entorno prod|dev [--dry-run]
     (DATABASE_URL, TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID por entorno; nunca se imprimen)
Salida: 0 ok (o sin token/chat_id: se imprime el mensaje y se avisa); 1 error de BD o de Telegram.
Solo lee (no migra): si la vista no existe, error claro. Sin reintentos.

La URL de la API lleva el token: ningún error se imprime con su mensaje, solo con su tipo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone

MAX_CARACTERES = 4000   # el límite de Telegram es 4096
TIMEOUT = 20
FUENTE_FEINA = "feinaactiva"
HORA_ULTIMA_OPORTUNIDAD = 13   # UTC: tras el ultimo respaldo del pipeline (12:53)


@dataclass(frozen=True)
class Fila:
    dia: date
    portal: str
    n_vistas: int
    n_nuevas: int
    n_desaparecidas: int | None
    n_unicas: int
    d_vistas_1d: int | None
    d_vistas_7d: int | None
    d_unicas_1d: int | None
    d_unicas_7d: int | None


def leer(conn) -> list[Fila]:
    """Una fila por portal (su último día). Lanza RuntimeError claro si falta la vista."""
    import psycopg

    try:
        filas = conn.execute(
            "SELECT dia, portal, n_vistas, n_nuevas, n_desaparecidas, n_unicas, "
            "d_vistas_1d, d_vistas_7d, d_unicas_1d, d_unicas_7d FROM v_mercado_hoy ORDER BY portal"
        ).fetchall()
    except psycopg.errors.UndefinedTable:
        raise RuntimeError("no existe la vista v_mercado_hoy (falta la migración 004)") from None
    return [Fila(*f) for f in filas]


def _d(v: int | None) -> str:
    return "—" if v is None else f"{v:+d}"


def _fecha(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def formatear(filas, entorno: str, hoy_utc: date | datetime) -> str:
    """Texto plano (sin parse_mode), siempre < 4096 caracteres."""
    hoy = hoy_utc.date() if isinstance(hoy_utc, datetime) else hoy_utc
    pref = "[dev] " if entorno == "dev" else ""
    cab = f"{pref}Mercado {hoy.isoformat()}"
    filas = list(filas)
    if not filas:
        return f"{cab}\nsin datos"
    lineas = [cab]
    for f in filas:
        marca = "" if f.dia == hoy else f" (sin datos de hoy, último: {_fecha(f.dia)})"
        lineas += [
            f"{f.portal}{marca}",
            f"  activas: {f.n_vistas} (Δ1d {_d(f.d_vistas_1d)}, Δ7d {_d(f.d_vistas_7d)})",
            f"  nuevas: {f.n_nuevas} · desaparecidas: {'—' if f.n_desaparecidas is None else f.n_desaparecidas}",
            f"  únicos: {f.n_unicas} (Δ1d {_d(f.d_unicas_1d)}, Δ7d {_d(f.d_unicas_7d)})",
        ]
    de_hoy = [f for f in filas if f.dia == hoy]
    lineas.append(f"Total hoy ({len(de_hoy)} portales): activas {sum(f.n_vistas for f in de_hoy)}, "
                  f"nuevas {sum(f.n_nuevas for f in de_hoy)}, únicos {sum(f.n_unicas for f in de_hoy)}")
    feina = [f for f in filas if f.portal == FUENTE_FEINA]
    if feina:
        lineas.append(f"Fuente Feina Activa: Generalitat de Catalunya (datos del {_fecha(feina[0].dia)})")
    return "\n".join(lineas)[:MAX_CARACTERES]


def http_telegram(url: str, datos: dict):
    """POST JSON -> (status, json). Los errores HTTP devuelven su código; el resto se propaga."""
    import urllib.error

    req = urllib.request.Request(url, method="POST", data=json.dumps(datos).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "jobhunting-mercado"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


def enviar(texto: str, token: str, chat_id: str, http=None) -> None:
    """Envía el texto. `http(url, datos) -> (status, json)`. Lanza RuntimeError sin token ni URL en el mensaje."""
    http = http or http_telegram
    try:
        st, resp = http(f"https://api.telegram.org/bot{token}/sendMessage",
                        {"chat_id": chat_id, "text": texto, "disable_web_page_preview": True})
    except Exception as e:  # el mensaje de urllib puede incluir la URL con el token
        raise RuntimeError(f"fallo de red al enviar a Telegram ({type(e).__name__})") from None
    if not 200 <= st < 300 or not (isinstance(resp, dict) and resp.get("ok")):
        raise RuntimeError(f"Telegram respondió {st} (no ok)")


def ya_enviado(conn, dia: date) -> bool:
    return conn.execute("SELECT 1 FROM avisos WHERE dia = %s AND tipo = 'mercado'", (dia,)).fetchone() is not None


def registrar_envio(conn, dia: date, ahora: datetime) -> None:
    conn.execute("INSERT INTO avisos (dia, tipo, enviado) VALUES (%s, 'mercado', %s) "
                 "ON CONFLICT (dia, tipo) DO NOTHING", (dia, ahora))
    conn.commit()


def main(argv=None, ahora=None, http=None) -> int:
    ap = argparse.ArgumentParser(prog="jobhunting.mercado")
    ap.add_argument("--entorno", choices=["prod", "dev"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="solo imprime el mensaje")
    a = ap.parse_args(argv)
    from jobhunting import db

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Falta DATABASE_URL", file=sys.stderr)
        return 1
    ahora = ahora or datetime.now(timezone.utc)
    prod_envio = a.entorno == "prod" and not a.dry_run
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    try:
        conn = db.conectar(url)
        try:
            if prod_envio and token and chat:
                db.migrar(conn)   # idempotente: garantiza la tabla avisos en prod
                conn.commit()
            filas = leer(conn)
            if prod_envio and token and chat:
                # Varios crons de respaldo: en prod se envia como mucho una vez al dia (UTC).
                if not any(f.dia == ahora.date() for f in filas):
                    print("sin datos de hoy, no se envia")
                    return 0
                from jobhunting.pipeline import PORTALES
                de_hoy = {f.portal for f in filas if f.dia == ahora.date()}
                if not set(PORTALES) <= de_hoy and ahora.hour < HORA_ULTIMA_OPORTUNIDAD:
                    print("datos incompletos, se espera al siguiente respaldo")
                    return 0
                if ya_enviado(conn, ahora.date()):
                    print("ya enviado hoy")
                    return 0
        finally:
            conn.close()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error de BD: {type(e).__name__}", file=sys.stderr)
        return 1
    texto = formatear(filas, a.entorno, ahora.date())
    print(texto)
    if a.dry_run:
        return 0
    if not token or not chat:
        print("::warning::Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID: mensaje no enviado")
        return 0
    try:
        enviar(texto, token, chat, http=http)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print("Enviado a Telegram")
    if prod_envio:
        try:
            conn = db.conectar(url)
            try:
                registrar_envio(conn, ahora.date(), ahora)
            finally:
                conn.close()
        except Exception as e:
            print(f"::warning::enviado, pero no se pudo registrar el aviso ({type(e).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
