"""Contrato de salida de una oferta (ficha ligera). Común a todos los portales."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


class OfertaInvalida(ValueError):
    pass


@dataclass(frozen=True)
class Oferta:
    portal: str                 # "tecnoempleo"
    id_portal: str              # id estable de la oferta en el portal
    titulo: str
    url: str                    # https, sin parámetros de seguimiento
    empresa: str | None = None
    ubicacion: str | None = None
    fecha_publicacion: datetime | None = None   # UTC, tz-aware
    capturada_en: datetime | None = None        # UTC, tz-aware (lo pone el pipeline)

    def __post_init__(self):
        validar(self)

    @property
    def clave(self) -> tuple[str, str]:
        return (self.portal, self.id_portal)


def _es_utc(d: datetime) -> bool:
    return d.tzinfo is not None and d.utcoffset() == timezone.utc.utcoffset(None)


def validar(o: Oferta) -> None:
    for campo in ("portal", "id_portal", "titulo", "url"):
        v = getattr(o, campo)
        if not isinstance(v, str) or not v.strip():
            raise OfertaInvalida(f"{campo} vacío")
    if o.portal != o.portal.lower():
        raise OfertaInvalida("portal debe ir en minúsculas")
    if not o.url.startswith("https://"):
        raise OfertaInvalida("url debe ser https")
    if len(o.titulo) > 300:
        raise OfertaInvalida("titulo demasiado largo")
    for campo in ("fecha_publicacion", "capturada_en"):
        d = getattr(o, campo)
        if d is not None and (not isinstance(d, datetime) or not _es_utc(d)):
            raise OfertaInvalida(f"{campo} debe ser datetime en UTC")


def deduplicar(ofertas):
    """Quita repetidas por (portal, id_portal), conservando la primera. Mantiene el orden."""
    vistas, salida = set(), []
    for o in ofertas:
        if o.clave not in vistas:
            vistas.add(o.clave)
            salida.append(o)
    return salida
