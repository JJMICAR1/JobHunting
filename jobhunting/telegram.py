"""Cliente minimo de la Bot API de Telegram (solo stdlib).

La URL lleva el token: ningun error se propaga con su mensaje original, solo con su tipo.
"""
from __future__ import annotations

import json
import urllib.request

TIMEOUT = 20


class LimiteTelegram(RuntimeError):
    """Telegram respondio 429: hay que parar, sin reintentos."""


def http_telegram(url: str, datos: dict):
    """POST JSON -> (status, json). Los errores HTTP devuelven su código; el resto se propaga."""
    import urllib.error

    req = urllib.request.Request(url, method="POST", data=json.dumps(datos).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "jobhunting-bot"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        return e.code, None


def llamar(token: str, metodo: str, datos: dict, http=None):
    """Llama a un metodo de la Bot API y devuelve `result`.

    `http(url, datos) -> (status, json)`. Lanza RuntimeError sin token ni URL en el mensaje
    (429 incluido: no hay reintentos).
    """
    http = http or http_telegram
    try:
        st, resp = http(f"https://api.telegram.org/bot{token}/{metodo}", datos)
    except Exception as e:  # el mensaje de urllib puede incluir la URL con el token
        raise RuntimeError(f"fallo de red en Telegram {metodo} ({type(e).__name__})") from None
    if st == 429:
        raise LimiteTelegram(f"Telegram {metodo} respondió 429 (límite de peticiones)")
    if not 200 <= st < 300 or not (isinstance(resp, dict) and resp.get("ok")):
        raise RuntimeError(f"Telegram {metodo} respondió {st} (no ok)")
    return resp.get("result")
