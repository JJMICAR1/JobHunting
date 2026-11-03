"""Parser del listado de Tecnoempleo. Recibe HTML, devuelve fichas; no hace red."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

from jobhunting.modelo import Oferta, OfertaInvalida

PORTAL = "tecnoempleo"
BASE = "https://www.tecnoempleo.com/"
_RE_ID = re.compile(r"rf-[0-9a-f]+$")
_RE_FECHA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_RE_TOTAL = re.compile(r"^\s*([\d.]+)\s+Ofertas?\b", re.I)


class ParserRoto(Exception):
    """El HTML no tiene la estructura de listado esperada (posible cambio del portal)."""


@dataclass
class ResultadoListado:
    ofertas: list[Oferta] = field(default_factory=list)
    total_anunciado: int | None = None
    url_siguiente: str | None = None
    n_descartadas: int = 0
    motivos_descarte: dict = field(default_factory=dict)  # motivo -> n (sin datos de la oferta)


def _txt(s: str | None) -> str:
    return " ".join((s or "").split())


def _limpiar_url(href: str) -> str:
    url = urldefrag(urljoin(BASE, href.strip()))[0]
    p = urlsplit(url)
    return f"https://{p.netloc}{p.path}"


def _ficha(tarjeta) -> Oferta:
    a = tarjeta.select_one("h3 a[href]")
    if a is None:
        raise OfertaInvalida("sin enlace de título")
    url = _limpiar_url(a["href"])
    m = _RE_ID.search(url)
    if not m:
        raise OfertaInvalida("sin id rf-")
    titulo = _txt(a.get("title") or a.get_text())
    emp = tarjeta.select_one("a.text-primary.link-muted")
    empresa = _txt(emp.get_text()) if emp else None
    ubicacion, fecha = None, None
    span = tarjeta.select_one("span.d-block.d-lg-none")
    if span:
        b = span.find("b")
        if b:
            ubicacion = _txt(b.get_text())
            resto = b.next_sibling
            mod = re.match(r"\s*(\([^)]*\))", resto) if isinstance(resto, str) else None
            if mod:
                ubicacion += " " + mod.group(1)
        # solo el texto propio del span (sin badges ni sueldo): hasta el primer <br>
        propio = []
        for n in span.children:
            if getattr(n, "name", None) == "br":
                break
            propio.append(n.get_text() if hasattr(n, "get_text") else str(n))
        f = _RE_FECHA.search(" ".join(propio))
        if f:
            d, mth, y = map(int, f.groups())
            try:
                fecha = datetime(y, mth, d, tzinfo=timezone.utc)
            except ValueError:
                fecha = None
    return Oferta(portal=PORTAL, id_portal=m.group(0), titulo=titulo, url=url,
                  empresa=empresa or None, ubicacion=ubicacion or None, fecha_publicacion=fecha)


def parsear_listado(html: str) -> ResultadoListado:
    soup = BeautifulSoup(html or "", "html.parser")
    h1 = soup.find("h1")
    m = _RE_TOTAL.match(h1.get_text()) if h1 else None
    total = int(m.group(1).replace(".", "")) if m else None
    tarjetas = [d for d in soup.find_all("div", class_="bg-white")
                if {"p-3", "border", "rounded", "mb-3"} <= set(d.get("class", []))
                and "location.href" in (d.get("onclick") or "")]
    if not tarjetas and m is None:
        raise ParserRoto("sin tarjetas de oferta ni h1 de ofertas")
    res = ResultadoListado(total_anunciado=total)
    vistos = set()
    for t in tarjetas:
        try:
            o = _ficha(t)
        except (OfertaInvalida, KeyError, TypeError) as e:
            res.n_descartadas += 1
            motivo = f"{type(e).__name__}: {e}"[:80]
            res.motivos_descarte[motivo] = res.motivos_descarte.get(motivo, 0) + 1
            continue
        if o.clave not in vistos:  # dedup dentro de la página
            vistos.add(o.clave)
            res.ofertas.append(o)
    nxt = soup.find("link", rel="next")
    if nxt is None:
        nxt = next((a for a in soup.find_all("a", href=True)
                    if _txt(a.get_text()).lower() == "siguiente"), None)
    if nxt is not None and nxt.get("href"):
        res.url_siguiente = urljoin(BASE, nxt["href"])
    return res
