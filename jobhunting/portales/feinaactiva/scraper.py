"""Descarga única del XML de Feina Activa. La red entra por `fetch` (bytes)."""
from __future__ import annotations

from dataclasses import dataclass, field

from jobhunting.descarga import Bloqueado, descargar_bytes
from jobhunting.modelo import Oferta, deduplicar
from jobhunting.portales.feinaactiva.parser import parsear_xml

URL_XML = "https://feinaactiva.gencat.cat/api/offers/offers-xml"
MAX_BYTES = 50_000_000


@dataclass
class ResultadoRecorrido:
    """Compatible con el de Tecnoempleo (mismos campos que lee el pipeline)."""
    ofertas: list[Oferta] = field(default_factory=list)
    paginas: int = 0
    total_anunciado: int | None = None
    n_descartadas: int = 0
    motivos_descarte: dict = field(default_factory=dict)
    bloqueado: bool = False
    motivo_parada: str = ""   # fin | bloqueado
    detalle: str | None = None
    n_por_grupo: dict = field(default_factory=dict)
    n_duplicadas: int = 0


def recorrer(fetch=descargar_bytes, url: str = URL_XML, max_bytes: int = MAX_BYTES,
             **_ignorados) -> ResultadoRecorrido:
    """UNA petición. ParserRoto se propaga (lo gestiona el pipeline); Bloqueado se devuelve."""
    res = ResultadoRecorrido(motivo_parada="fin")
    try:
        datos = fetch(url) if fetch is not descargar_bytes else fetch(url, max_bytes=max_bytes)
    except Bloqueado as e:
        res.bloqueado, res.motivo_parada, res.detalle = True, "bloqueado", str(e)
        return res
    res.paginas = 1
    x = parsear_xml(datos)
    res.ofertas = deduplicar(x.ofertas)
    res.total_anunciado = sum(x.n_por_grupo.values())
    res.n_descartadas, res.motivos_descarte = x.n_descartadas, x.motivos_descarte
    res.n_por_grupo, res.n_duplicadas = x.n_por_grupo, x.n_duplicadas
    return res
