"""Recuento de mercado diario por Telegram (solo enviar, Bot API). Lee la vista `v_mercado_hoy`.

Uso: python -m jobhunting.mercado --entorno prod|dev [--dry-run]
     (DATABASE_URL, TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID por entorno; nunca se imprimen)
Salida: 0 ok (o sin token/chat_id: se imprime el mensaje y se avisa); 1 error de BD o de Telegram.
Solo lee (no migra): si la vista no existe, error claro. Sin reintentos.

La URL de la API lleva el token: ningún error se imprime con su mensaje, solo con su tipo.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone

from jobhunting.telegram import http_telegram  # noqa: F401  (se reexporta: mercado.http_telegram)

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


DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
NOMBRES = {"feinaactiva": "Feina Activa", "tecnoempleo": "Tecnoempleo"}


def _n(v: int) -> str:
    return f"{v:,}".replace(",", ".")


def _pct(v: float) -> str:
    return f"{v:+.1f}".replace(".", ",") + " %"


def _fecha_larga(d: date) -> str:
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _fecha_corta(d) -> str:
    return d.strftime("%d/%m/%Y") if hasattr(d, "strftime") else str(d)


def _ofertas(n: int) -> str:
    return f"{_n(n)} oferta" + ("" if n == 1 else "s")


def _mas_menos(delta: int) -> str:
    return f"{_n(abs(delta))} " + ("más" if delta > 0 else "menos")


def _comparacion(total: int, d1: int | None, d7: int | None) -> str:
    if d1 is None and d7 is None:
        return "Es el primer día con datos, aún no hay con qué comparar."
    partes = []
    if d1 is not None:
        if d1 == 0:
            partes.append("igual que ayer")
        else:
            txt = f"{_mas_menos(d1)} que ayer"
            if total - d1 > 0:
                txt += f" ({_pct(d1 / (total - d1) * 100)})"
            partes.append(txt)
    if d7 is not None:
        partes.append("igual que hace una semana" if d7 == 0 else f"{_mas_menos(d7)} que hace una semana")
    primero = partes[0]
    if d1 is not None and d1 != 0:
        verbo = "Es" if abs(d1) == 1 else "Son"
    elif d1 is None and d7 != 0:
        verbo = "Es" if abs(d7) == 1 else "Son"
    else:
        verbo = "Es"
    return f"{verbo} {primero}" + (f" y {partes[1]}" if len(partes) > 1 else "") + "."


def formatear(filas, entorno: str, hoy_utc: date | datetime) -> str:
    """Texto plano (sin parse_mode), siempre < 4096 caracteres."""
    hoy = hoy_utc.date() if isinstance(hoy_utc, datetime) else hoy_utc
    titulo = ("🧪 [dev] " if entorno == "dev" else "📊 ") + "Mercado laboral en Catalunya"
    cab = f"{titulo}\n{_fecha_larga(hoy)}"
    filas = list(filas)
    if not filas:
        return f"{cab}\n\nHoy no hay datos todavía."
    de_hoy = [f for f in filas if f.dia == hoy]
    bloques = [cab]
    if de_hoy:
        total = sum(f.n_vistas for f in de_hoy)
        unicas = sum(f.n_unicas for f in de_hoy)
        d1 = sum(f.d_vistas_1d for f in de_hoy) if all(f.d_vistas_1d is not None for f in de_hoy) else None
        d7 = sum(f.d_vistas_7d for f in de_hoy) if all(f.d_vistas_7d is not None for f in de_hoy) else None
        act = "Hoy hay 1 oferta activa" if total == 1 else f"Hoy hay {_n(total)} ofertas activas"
        uni = "1 puesto distinto" if unicas == 1 else f"{_n(unicas)} puestos distintos"
        bloques.append(f"{act} ({uni}).\n{_comparacion(total, d1, d7)}")
        nuevas = sum(f.n_nuevas for f in de_hoy)
        ent = ("Ha entrado 1 oferta nueva" if nuevas == 1 else f"Han entrado {_n(nuevas)} ofertas nuevas")
        if all(f.n_desaparecidas is not None for f in de_hoy):
            desap = sum(f.n_desaparecidas for f in de_hoy)
            ent += " y ha desaparecido 1" if desap == 1 else f" y han desaparecido {_n(desap)}"
        bloques.append(ent + ".")
    else:
        bloques.append("Hoy no hay datos todavía.")
    lin = ["Por portal:"]
    for f in sorted(filas, key=lambda f: (f.dia != hoy, -f.n_vistas, f.portal)):
        nombre = NOMBRES.get(f.portal, f.portal)
        if f.dia != hoy:
            lin.append(f"• {nombre}: sin datos de hoy (último: {_fecha_corta(f.dia)}).")
            continue
        t = f"• {nombre}: {_ofertas(f.n_vistas)}"
        if f.d_vistas_1d is not None:
            t += f" ({f.d_vistas_1d:+d} vs ayer)"
        t += f". {_n(f.n_nuevas)} " + ("nueva" if f.n_nuevas == 1 else "nuevas")
        if f.n_desaparecidas is not None:
            t += f", {_n(f.n_desaparecidas)} " + ("retirada" if f.n_desaparecidas == 1 else "retiradas")
        lin.append(t + ".")
    bloques.append("\n".join(lin))
    feina = [f for f in filas if f.portal == FUENTE_FEINA]
    if feina:
        bloques.append(f"Fuente: Feina Activa (Generalitat de Catalunya), datos del {_fecha_corta(feina[0].dia)}.")
    return "\n\n".join(bloques)[:MAX_CARACTERES]


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
