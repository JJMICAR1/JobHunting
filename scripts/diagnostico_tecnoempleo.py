"""Diagnóstico (solo a mano, workflow `fixture`): recorre el listado de Tecnoempleo con la
descarga educada del pipeline e imprime SOLO el HTML de las tarjetas problemáticas
(sin ubicación o descartadas), para convertirlas en fixtures. No toca la BD."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bs4 import BeautifulSoup  # noqa: E402

from jobhunting.descarga import descargar  # noqa: E402
from jobhunting.portales.tecnoempleo.parser import _ficha  # noqa: E402
from jobhunting.portales.tecnoempleo.scraper import recorrer  # noqa: E402

MAX_POR_TIPO = 3


def main():
    paginas = []

    def fetch(url):
        html = descargar(url)
        paginas.append((url, html))
        return html

    rec = recorrer(fetch=fetch)
    print(f"paginas={rec.paginas} ofertas={len(rec.ofertas)} descartadas={rec.n_descartadas}")
    vistos = {"sin_ubicacion": 0, "descartada": 0}
    for url, html in paginas:
        pag = re.search(r"pagina=(\d+)", url)
        soup = BeautifulSoup(html, "html.parser")
        for t in soup.find_all("div", class_="bg-white"):
            if not ({"p-3", "border", "rounded", "mb-3"} <= set(t.get("class", []))
                    and "location.href" in (t.get("onclick") or "")):
                continue
            try:
                o = _ficha(t)
                tipo = None if o.ubicacion else "sin_ubicacion"
            except Exception:
                tipo = "descartada"
            if tipo and vistos[tipo] < MAX_POR_TIPO:
                vistos[tipo] += 1
                print(f"=====TARJETA {tipo} pagina={pag.group(1) if pag else 1}=====")
                print(str(t))
    print("resumen", vistos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
