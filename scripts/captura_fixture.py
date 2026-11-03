"""Captura una página pública de Tecnoempleo para usarla como fixture de tests.

Solo a mano (workflow `fixture`). Una petición, respeta robots.txt, sin reintentos.
Hasta 3 URLs separadas por espacios. Escribe `fixture_N.html` e imprime un bloque gzip+base64 en el log.
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
# Catalunya: pr=Barcelona(240), Girona(252), Lleida(262), Tarragona(276)
URLS_DEFECTO = "https://www.tecnoempleo.com/ofertas-trabajo/?pr=,240,252,262,276,"
PAUSA_S = 5


def capturar(n, url):
    if not url.startswith("https://www.tecnoempleo.com/"):
        print("Solo se permite tecnoempleo.com")
        return 1
    if robots_permitido(url) is not True:
        print("robots.txt no lo permite o no se pudo leer; paro.")
        return 1
    time.sleep(2)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as r:
        print("status", r.status, "url_final", r.geturl())
        body = r.read()
    Path(f"fixture_{n}.html").write_bytes(body)
    b64 = base64.b64encode(gzip.compress(body, 9)).decode()
    print("bytes", len(body), "b64", len(b64))
    print(f"-----FIXTURE-{n}-INICIO-----")
    for i in range(0, len(b64), 76):
        print(b64[i:i + 76])
    print(f"-----FIXTURE-{n}-FIN-----")
    return 0


def main():
    urls = (sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else URLS_DEFECTO).split()[:3]
    for n, url in enumerate(urls, 1):
        if n > 1:
            time.sleep(PAUSA_S)
        if capturar(n, url):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
