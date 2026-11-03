"""Clasificación de respuestas de portales (compartida por la sonda y la descarga). Sin red."""
MARCAS_BLOQUEO = ["captcha", "cf-chl", "challenge-platform", "datadome",
                  "px-captcha", "access denied", "perimeterx"]
STATUS_BLOQUEO = {403, 429, 451, 503}
# Cloudflare inyecta /cdn-cgi/challenge-platform/ también en páginas normales: las marcas
# del HTML solo cuentan si la página es pequeña o es el aviso "Just a moment".
MAX_BYTES_BLOQUEO = 50_000
MARCAS_LOGIN = ["login", "signin", "authwall"]


def clasificar(status, url_final, html, esperadas=None):
    """Devuelve (estado, señales) sin tocar la red.

    `esperadas`: palabras que indican un HTML de ofertas (por defecto ESPERADAS_GENERICAS).
    """
    senales = []
    bajo = (html or "").lower()
    url_baja = (url_final or "").lower()
    if status in STATUS_BLOQUEO:
        senales.append(f"http_{status}")
    pagina_de_aviso = len(bajo) < MAX_BYTES_BLOQUEO or "just a moment" in bajo
    for m in MARCAS_BLOQUEO:
        if m in bajo:
            senales.append(m if pagina_de_aviso else f"ignorada:{m}")
    if status in STATUS_BLOQUEO or any(m in MARCAS_BLOQUEO for m in senales):
        return "bloqueado", senales
    for m in MARCAS_LOGIN:
        if m in url_baja:
            senales.append(f"url_{m}")
    if any(s.startswith("url_") for s in senales):
        return "redirige_login", senales
    if status is None or status != 200:
        return "error", senales + [f"http_{status}"]
    vistas = [p for p in (esperadas or ESPERADAS_GENERICAS) if p in bajo]
    senales += [f"palabra:{p}" for p in vistas]
    if vistas:
        return "funciona", senales
    return "necesita_js", senales


ESPERADAS_GENERICAS = ["oferta", "empleo", "trabajo", "job", "vacante"]
