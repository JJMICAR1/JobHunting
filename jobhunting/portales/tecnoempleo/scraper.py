"""Recorrido paginado del listado de Tecnoempleo (Catalunya). La red entra por `fetch`."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from jobhunting.descarga import Bloqueado, descargar, crawl_delay
from jobhunting.modelo import Oferta, deduplicar
from jobhunting.portales.tecnoempleo.parser import parsear_listado

URL_BASE = "https://www.tecnoempleo.com/ofertas-trabajo/?pr=,240,252,262,276,"


@dataclass
class ResultadoRecorrido:
    ofertas: list[Oferta] = field(default_factory=list)
    paginas: int = 0
    total_anunciado: int | None = None
    n_descartadas: int = 0
    motivos_descarte: dict = field(default_factory=dict)
    bloqueado: bool = False
    motivo_parada: str = ""   # fin | max_paginas | bloqueado | sin_nuevas
    detalle: str | None = None


def recorrer(fetch=descargar, max_paginas: int = 30, pausa_s: float = 5,
             sleep=time.sleep, url_base: str = URL_BASE) -> ResultadoRecorrido:
    """Sigue `url_siguiente`. Un ParserRoto del parser se propaga (lo gestiona el pipeline)."""
    res = ResultadoRecorrido(motivo_parada="fin")
    vistos: set = set()
    url = url_base
    while url:
        if res.paginas >= max_paginas:
            res.motivo_parada = "max_paginas"
            break
        if res.paginas:
            # Con la descarga real se respeta el Crawl-delay de robots.txt si es mayor.
            sleep(max(pausa_s, crawl_delay(url)) if fetch is descargar else pausa_s)
        try:
            html = fetch(url)
        except Bloqueado as e:
            res.bloqueado, res.motivo_parada, res.detalle = True, "bloqueado", str(e)
            break
        pag = parsear_listado(html)
        res.paginas += 1
        res.n_descartadas += pag.n_descartadas
        for k, v in pag.motivos_descarte.items():
            res.motivos_descarte[k] = res.motivos_descarte.get(k, 0) + v
        if res.total_anunciado is None:
            res.total_anunciado = pag.total_anunciado
        nuevas = [o for o in pag.ofertas if o.clave not in vistos]
        vistos.update(o.clave for o in nuevas)
        res.ofertas.extend(nuevas)
        if not nuevas:
            res.motivo_parada = "sin_nuevas"
            break
        url = pag.url_siguiente
    res.ofertas = deduplicar(res.ofertas)
    return res
