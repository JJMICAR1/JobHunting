"""Parser del XML de datos abiertos de Feina Activa. Recibe bytes, devuelve fichas; no hace red.

Fuente: Generalitat de Catalunya, Feina Activa (datos abiertos; reutilización citando la fuente
y la fecha de actualización). Ficha ligera: NO se guardan content/experience/requirements/studies
ni salarios (pueden contener datos de contacto).
"""
from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from jobhunting.modelo import Oferta, OfertaInvalida, ParserRoto
from jobhunting.normalizar import _modalidad, capitalizar_nombre, separar_ubicacion
from jobhunting.xml_seguro import LectorSeguro, XmlRechazado

PORTAL = "feinaactiva"
HOST = "feinaactiva.gencat.cat"
TOPE_BYTES = 60_000_000
TOPE_SEGUNDOS = 120
_MADRID = ZoneInfo("Europe/Madrid")
_RE_ID = re.compile(r"[A-Za-z0-9_-]{1,40}$")
_RE_FECHA = re.compile(r"\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


@dataclass
class ResultadoXml:
    ofertas: list[Oferta] = field(default_factory=list)
    n_descartadas: int = 0
    motivos_descarte: dict = field(default_factory=dict)   # motivo -> n (sin datos de la oferta)
    n_por_grupo: dict = field(default_factory=dict)        # grupo -> nº de <ad> leídos
    n_duplicadas: int = 0                                  # ids repetidos (se conserva la primera)


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _txt(s: str | None) -> str:
    return " ".join((s or "").split())


def _fecha_utc(texto: str) -> datetime | None:
    """dd/mm/yyyy -> medianoche de Europe/Madrid expresada en UTC; None si no se entiende."""
    m = _RE_FECHA.match(texto or "")
    if not m:
        return None
    d, mes, y = map(int, m.groups())
    try:
        return datetime(y, mes, d, tzinfo=_MADRID).astimezone(timezone.utc)
    except ValueError:
        return None


def _url_valida(texto: str) -> str:
    p = urlsplit(texto.strip())
    if p.scheme != "https" or p.netloc != HOST:
        raise OfertaInvalida("url no https o de otro host")
    return f"https://{HOST}{p.path}" + (f"?{p.query}" if p.query else "")


def _ficha(campos: dict) -> Oferta:
    id_ = _txt(campos.get("id"))
    if not _RE_ID.match(id_):
        raise OfertaInvalida("id vacío o con formato no válido")
    titulo = _txt(campos.get("title"))
    if not titulo:
        raise OfertaInvalida("título vacío")
    url = _url_valida(_txt(campos.get("url")))
    empresa = _txt(campos.get("company")) or None
    city = _txt(campos.get("city"))
    region = _txt(campos.get("region"))
    ciudad, _ = separar_ubicacion(city)
    partes = [capitalizar_nombre(x) for x in (city, region) if x]
    if len(partes) == 2 and partes[0].lower() == partes[1].lower():
        partes = partes[:1]
    ubicacion = ", ".join(partes) or None
    # "presencial" suelto en un título es ruido: del título solo se admite remoto/híbrido.
    modalidad = _modalidad(_txt(campos.get("workingHours")))
    if modalidad is None:
        m_t = _modalidad(titulo)
        modalidad = m_t if m_t in ("remoto", "hibrido") else None
    return Oferta(portal=PORTAL, id_portal=id_, titulo=titulo, url=url, empresa=empresa,
                  ubicacion=ubicacion, fecha_publicacion=_fecha_utc(_txt(campos.get("date"))),
                  ciudad=ciudad, modalidad=modalidad)


# Solo se leen estos hijos de <ad>; el resto (content, requirements, salarios...) se ignora.
_CAMPOS = frozenset({"id", "title", "company", "city", "region", "date", "url", "workingHours"})


def parsear_xml(datos: bytes) -> ResultadoXml:
    """Streaming con iterparse + clear(). Acepta <ad> bajo cualquier grupo hijo de <ofertes>.

    ParserRoto si la raíz no es <ofertes>, el XML es ilegible/inseguro (DOCTYPE/ENTITY) o hay 0 <ad>.
    """
    res = ResultadoXml()
    vistos: set = set()
    depth, grupo, campos = 0, "", None
    fuente = LectorSeguro(io.BytesIO(datos or b""), tope=TOPE_BYTES, segundos=TOPE_SEGUNDOS)
    try:
        for ev, el in ET.iterparse(fuente, events=("start", "end")):
            tag = _local(el.tag)
            if ev == "start":
                depth += 1
                if depth == 1 and tag != "ofertes":
                    raise ParserRoto("la raíz no es <ofertes>")
                if depth == 2:
                    grupo = tag
                continue
            if tag == "ad" and depth in (2, 3):
                g = grupo if depth == 3 else "(raiz)"
                res.n_por_grupo[g] = res.n_por_grupo.get(g, 0) + 1
                campos = {_local(h.tag): h.text for h in el if _local(h.tag) in _CAMPOS}
                el.clear()
                try:
                    o = _ficha(campos)
                except OfertaInvalida as e:
                    res.n_descartadas += 1
                    motivo = str(e)[:80]
                    res.motivos_descarte[motivo] = res.motivos_descarte.get(motivo, 0) + 1
                else:
                    if o.clave in vistos:
                        res.n_duplicadas += 1
                    else:
                        vistos.add(o.clave)
                        res.ofertas.append(o)
            depth -= 1
    except ParserRoto:
        raise
    except (ET.ParseError, XmlRechazado) as e:
        raise ParserRoto(f"XML ilegible o rechazado: {type(e).__name__}") from None
    if not res.n_por_grupo:
        raise ParserRoto("el XML no contiene ningún <ad>")
    return res
