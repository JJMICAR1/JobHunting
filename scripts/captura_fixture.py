"""Captura una página pública de Tecnoempleo para usarla como fixture de tests.

Solo a mano (workflow `fixture`). Una petición, respeta robots.txt, sin reintentos.
Escribe el HTML en `fixture.html` e imprime un bloque gzip+base64 en el log.
"""
import base64
import gzip
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sonda_portales import robots_permitido  # noqa: E402

USER_AGENT = "JobHuntingBot/0.1 (+https://github.com/JJMICAR1/JobHunting)"
URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.tecnoempleo.com/ofertas-trabajo/?provincia=9"


def main():
    if not URL.startswith("https://www.tecnoempleo.com/"):
        print("Solo se permite tecnoempleo.com")
        return 1
    if robots_permitido(URL) is not True:
        print("robots.txt no lo permite o no se pudo leer; paro.")
        return 1
    time.sleep(2)
    req = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        print("status", r.status, "url_final", r.geturl())
        body = r.read()
    Path("fixture.html").write_bytes(body)
    b64 = base64.b64encode(gzip.compress(body, 9)).decode()
    print("bytes", len(body), "b64", len(b64))
    print("-----FIXTURE-INICIO-----")
    for i in range(0, len(b64), 76):
        print(b64[i:i + 76])
    print("-----FIXTURE-FIN-----")
    return 0


if __name__ == "__main__":
    sys.exit(main())
