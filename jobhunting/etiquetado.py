"""Bot de etiquetado Si/No en GitHub Actions: recoge clics y comandos y envia un lote diario.

Uso: python -m jobhunting.etiquetado --entorno prod|dev [--dry-run]
     (DATABASE_URL, TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID por entorno; nunca se imprimen)
Salida: 0 ok (o sin token/chat_id: se imprime lo que se haria); 1 error de BD o de Telegram.
Diseno: docs/ETIQUETADO.md. Los criterios (reglas) viven en la tabla `config`, nunca en el repo.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import date, datetime, time, timedelta, timezone

from jobhunting import reglas as R
from jobhunting import telegram as tg

TIPO_AVISO = "etiquetado"
LOTE_DEFECTO = 10
FRACCION_REGLAS = 0.7
UPDATES_PERMITIDOS = ["message", "callback_query"]
PREFIJO = {"prod": "p", "dev": "d"}


# --- BD (funciones pequenas) ---

def _jsonb(v):
    from psycopg.types.json import Jsonb
    return Jsonb(v)


def leer_config(conn, clave: str, defecto=None):
    import psycopg
    try:
        f = conn.execute("SELECT valor FROM config WHERE clave = %s", (clave,)).fetchone()
    except psycopg.errors.UndefinedTable:
        raise RuntimeError("no existe la tabla config (falta la migración 006)") from None
    return defecto if f is None else f[0]


def guardar_config(conn, clave: str, valor, ahora: datetime) -> None:
    conn.execute("INSERT INTO config (clave, valor, actualizado) VALUES (%s, %s, %s) "
                 "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = EXCLUDED.actualizado",
                 (clave, _jsonb(valor), ahora))


def leer_reglas(conn) -> R.Reglas:
    try:
        return R.Reglas.desde_dict(leer_config(conn, "reglas", None))
    except ValueError:
        raise RuntimeError("config.reglas tiene un formato no válido") from None


def leer_lote(conn) -> int:
    v = leer_config(conn, "lote", LOTE_DEFECTO)
    return v if isinstance(v, int) and not isinstance(v, bool) and R.LOTE_MIN <= v <= R.LOTE_MAX else LOTE_DEFECTO


def hay_ofertas_de_hoy(conn, dia: date) -> bool:
    ini, fin = _rango(dia)
    return conn.execute("SELECT 1 FROM ofertas WHERE ultima_vez >= %s AND ultima_vez < %s LIMIT 1",
                        (ini, fin)).fetchone() is not None


def _rango(dia: date):
    ini = datetime.combine(dia, time.min, tzinfo=timezone.utc)
    return ini, ini + timedelta(days=1)


_COLS = ("portal", "id_portal", "titulo", "empresa", "ciudad", "modalidad", "url", "ultima_vez")


def candidatas(conn, dia: date) -> list[dict]:
    """Ofertas vistas ese dia UTC y nunca enviadas, en orden estable."""
    ini, fin = _rango(dia)
    filas = conn.execute(
        "SELECT o.portal, o.id_portal, o.titulo, o.empresa, o.ciudad, o.modalidad, o.url, o.ultima_vez "
        "FROM ofertas o WHERE o.ultima_vez >= %s AND o.ultima_vez < %s "
        "AND NOT EXISTS (SELECT 1 FROM envios_etiquetado e WHERE e.portal = o.portal AND e.id_portal = o.id_portal) "
        "ORDER BY o.portal, o.id_portal", (ini, fin)).fetchall()
    return [dict(zip(_COLS, f)) for f in filas]


def enviados_hoy(conn, dia: date) -> int:
    ini, fin = _rango(dia)
    return conn.execute("SELECT count(*) FROM envios_etiquetado WHERE enviado >= %s AND enviado < %s",
                        (ini, fin)).fetchone()[0]


def registrar_envio(conn, portal: str, id_portal: str, ahora: datetime, muestra: str, nota: float | None) -> int | None:
    """Reserva el envio (id para los botones). None si esa oferta ya se envio (como mucho una vez)."""
    f = conn.execute(
        "INSERT INTO envios_etiquetado (portal, id_portal, enviado, muestra, nota) VALUES (%s,%s,%s,%s,%s) "
        "ON CONFLICT (portal, id_portal) DO NOTHING RETURNING id", (portal, id_portal, ahora, muestra, nota)).fetchone()
    return f[0] if f else None


def fijar_message_id(conn, envio_id: int, message_id: int) -> None:
    conn.execute("UPDATE envios_etiquetado SET message_id = %s WHERE id = %s", (message_id, envio_id))


def borrar_envio(conn, envio_id: int) -> None:
    """Deshace una reserva cuyo mensaje no llego a enviarse."""
    conn.execute("DELETE FROM envios_etiquetado WHERE id = %s AND message_id IS NULL", (envio_id,))


def guardar_etiqueta(conn, envio_id: int, etiqueta: bool, ahora: datetime) -> bool:
    """Upsert (gana el ultimo clic). False si el envio no existe."""
    f = conn.execute(
        "INSERT INTO etiquetas (portal, id_portal, etiqueta, etiquetada, envio_id) "
        "SELECT portal, id_portal, %s, %s, id FROM envios_etiquetado WHERE id = %s "
        "ON CONFLICT (portal, id_portal) DO UPDATE SET etiqueta = EXCLUDED.etiqueta, "
        "etiquetada = EXCLUDED.etiquetada, envio_id = EXCLUDED.envio_id RETURNING 1",
        (etiqueta, ahora, envio_id)).fetchone()
    return f is not None


def progreso(conn) -> dict:
    t, si = conn.execute("SELECT count(*), count(*) FILTER (WHERE etiqueta) FROM etiquetas").fetchone()
    return {"total": t, "si": si, "no": t - si, "meta": R.META, "lote": leer_lote(conn)}


def aviso_hecho(conn, dia: date) -> bool:
    return conn.execute("SELECT 1 FROM avisos WHERE dia = %s AND tipo = %s", (dia, TIPO_AVISO)).fetchone() is not None


def registrar_aviso(conn, dia: date, ahora: datetime) -> None:
    conn.execute("INSERT INTO avisos (dia, tipo, enviado) VALUES (%s, %s, %s) ON CONFLICT (dia, tipo) DO NOTHING",
                 (dia, TIPO_AVISO, ahora))


# --- seleccion y formato (puros) ---

def seleccionar(cands: list[dict], reglas: R.Reglas, lote: int, dia: date) -> list[dict]:
    """70 % de mejor nota (empate: mas reciente) y el resto al azar. Mismo dia -> mismo lote.

    Devuelve las candidatas con las claves extra `muestra` ('reglas'|'azar'), `nota` y `motivos`.
    """
    punt = []
    for c in cands:
        nota, motivos = R.puntuar(c["titulo"], c["empresa"], c.get("ciudad"), c.get("modalidad"), reglas)
        punt.append({**c, "nota": nota, "motivos": motivos, "muestra": "azar"})
    n = min(lote, len(punt))
    n_reglas = 0 if reglas.vacia() else min(round(lote * FRACCION_REGLAS), n)
    mejores = sorted(punt, key=lambda c: (-c["nota"], -c["ultima_vez"].timestamp(), c["portal"], c["id_portal"]))[:n_reglas]
    for c in mejores:
        c["muestra"] = "reglas"
    elegidas = {(c["portal"], c["id_portal"]) for c in mejores}
    resto = [c for c in punt if (c["portal"], c["id_portal"]) not in elegidas]
    azar = random.Random(dia.toordinal()).sample(resto, min(n - len(mejores), len(resto)))
    return mejores + azar


def formatear(c: dict, entorno: str, con_reglas: bool) -> str:
    """Texto plano de una oferta."""
    lineas = [("[dev] " if entorno == "dev" else "") + c["titulo"]]
    if c.get("empresa"):
        lineas.append(c["empresa"])
    ubic = " · ".join(x for x in (c.get("ciudad"), c.get("modalidad")) if x)
    if ubic:
        lineas.append(ubic)
    extra = []
    if con_reglas:
        extra.append(f"Nota {c['nota']:.1f}".replace(".", ",") + (": " + ", ".join(c["motivos"]) if c["motivos"] else ""))
    if c["muestra"] == "azar":
        extra.append("[azar]")
    if extra:
        lineas.append(" ".join(extra))
    lineas.append(c["url"])
    return "\n".join(lineas)


def teclado(entorno: str, envio_id: int) -> dict:
    p = PREFIJO[entorno]
    return {"inline_keyboard": [[{"text": "Sí", "callback_data": f"{p}:s:{envio_id}"},
                                 {"text": "No", "callback_data": f"{p}:n:{envio_id}"}]]}


def parsear_callback(data: str, entorno: str):
    """(etiqueta_bool, envio_id) o None si no es de este entorno o esta mal formado."""
    partes = (data or "").split(":")
    if len(partes) != 3 or partes[0] != PREFIJO[entorno] or partes[1] not in ("s", "n") or not partes[2].isdigit():
        return None
    return partes[1] == "s", int(partes[2])


# --- recoger ---

def _intentar(fn, *a):
    """Respuestas cosmeticas a Telegram: un fallo (salvo el limite 429) no impide guardar el estado."""
    try:
        fn(*a)
    except tg.LimiteTelegram:
        raise
    except RuntimeError as e:
        print(f"::warning::{e}")


def recoger(conn, entorno: str, token: str, chat: str, ahora: datetime, http=None) -> int:
    """Procesa clics y comandos pendientes. Devuelve cuantos updates se miraron."""
    datos = {"timeout": 0, "allowed_updates": UPDATES_PERMITIDOS}
    prod = entorno == "prod"
    if prod:
        off = leer_config(conn, "telegram_offset", None)
        if isinstance(off, int) and not isinstance(off, bool):
            datos["offset"] = off
    updates = tg.llamar(token, "getUpdates", datos, http) or []
    ultimo = None
    try:
        for u in updates:
            _procesar(conn, u, entorno, token, chat, ahora, http)
            ultimo = u["update_id"]
    finally:
        if prod and ultimo is not None:   # en dev solo se mira: no se confirma nada
            guardar_config(conn, "telegram_offset", ultimo + 1, ahora)
    return len(updates)


def _procesar(conn, u: dict, entorno: str, token: str, chat: str, ahora: datetime, http) -> None:
    cq = u.get("callback_query")
    if cq:
        msg = cq.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != chat:
            return
        r = parsear_callback(cq.get("data"), entorno)
        if r is None:
            return
        etiqueta, envio_id = r
        ok = guardar_etiqueta(conn, envio_id, etiqueta, ahora)
        marca = "Sí ✅" if etiqueta else "No ❌"
        _intentar(tg.llamar, token, "answerCallbackQuery",
                  {"callback_query_id": cq.get("id"), "text": marca if ok else "Oferta desconocida"}, http)
        if ok and msg.get("message_id") is not None:
            _intentar(tg.llamar, token, "editMessageText",
                      {"chat_id": chat, "message_id": msg["message_id"],
                       "text": f"{msg.get('text') or ''}\n\n{marca}", "reply_markup": {"inline_keyboard": []},
                       "disable_web_page_preview": True}, http)
        return
    m = u.get("message")
    if not m or entorno != "prod" or str((m.get("chat") or {}).get("id")) != chat:
        return
    texto = m.get("text") or ""
    if not texto.startswith("/"):
        return
    reglas = leer_reglas(conn)
    lote = R.parsear_lote(texto)
    if isinstance(lote, int):
        guardar_config(conn, "lote", lote, ahora)
        resp = f"Lote: {lote} al día"
    else:
        prog = progreso(conn)
        nuevas, resp = R.aplicar_comando(reglas, texto, prog)
        if nuevas != reglas:
            guardar_config(conn, "reglas", nuevas.a_dict(), ahora)
    _intentar(tg.llamar, token, "sendMessage", {"chat_id": chat, "text": resp}, http)


# --- enviar lote ---

def enviar_lote(conn, entorno: str, token: str | None, chat: str | None, ahora: datetime,
                dry_run: bool, http=None) -> int:
    """Envia (o, sin token / en dry-run, solo imprime) el lote del dia. Devuelve cuantas ofertas trata."""
    dia = ahora.date()
    real = bool(token and chat) and not dry_run
    if real and aviso_hecho(conn, dia):
        print("lote de hoy ya enviado")
        return 0
    if not hay_ofertas_de_hoy(conn, dia):
        print("sin ofertas vistas hoy, no se envía lote")
        return 0
    reglas, lote = leer_reglas(conn), leer_lote(conn)
    pendientes = lote - (enviados_hoy(conn, dia) if real else 0)   # reanuda un lote cortado a medias
    if pendientes <= 0:
        if real:
            registrar_aviso(conn, dia, ahora)
        return 0
    elegidas = seleccionar(candidatas(conn, dia), reglas, pendientes, dia)
    if not elegidas:
        print("sin candidatas nuevas")
        return 0
    enviadas = 0
    for c in elegidas:
        texto = formatear(c, entorno, not reglas.vacia())
        if not real:
            print(f"--- [{c['muestra']}] ---\n{texto}\n")
            continue
        envio_id = registrar_envio(conn, c["portal"], c["id_portal"], ahora, c["muestra"], c["nota"])
        if envio_id is None:
            continue
        try:
            res = tg.llamar(token, "sendMessage",
                            {"chat_id": chat, "text": texto, "disable_web_page_preview": True,
                             "reply_markup": teclado(entorno, envio_id)}, http)
        except RuntimeError:
            borrar_envio(conn, envio_id)
            raise
        if isinstance(res, dict) and res.get("message_id") is not None:
            fijar_message_id(conn, envio_id, res["message_id"])
        enviadas += 1
    if real:
        registrar_aviso(conn, dia, ahora)
        print(f"Enviadas {enviadas} ofertas a Telegram")
    else:
        print(f"(sin envío) {len(elegidas)} ofertas en el lote")
    return len(elegidas)


def main(argv=None, ahora=None, http=None) -> int:
    ap = argparse.ArgumentParser(prog="jobhunting.etiquetado")
    ap.add_argument("--entorno", choices=["prod", "dev"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="no escribe en la BD ni en Telegram")
    a = ap.parse_args(argv)
    from jobhunting import db

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("Falta DATABASE_URL", file=sys.stderr)
        return 1
    ahora = ahora or datetime.now(timezone.utc)
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    real = bool(token and chat) and not a.dry_run
    if not real and not a.dry_run:
        print("::warning::Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID: solo se muestra lo que se haría")
    try:
        conn = db.conectar(url)
        try:
            if real:
                db.migrar(conn)   # idempotente
                recoger(conn, a.entorno, token, chat, ahora, http)
            enviar_lote(conn, a.entorno, token, chat, ahora, a.dry_run, http)
        finally:
            conn.close()
    except tg.LimiteTelegram:
        print("::warning::Telegram respondió 429: se para sin reintentos")
        return 0
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error de BD: {type(e).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
