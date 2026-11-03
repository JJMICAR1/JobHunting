"""Normalización independiente del portal (sin red): ubicación y huella de puesto."""
from __future__ import annotations

import hashlib
import re
import unicodedata

MODALIDADES = frozenset({"presencial", "hibrido", "remoto"})
_CONECTORES = {"de", "del", "la", "las", "el", "los", "y", "i", "e", "en", "da", "do", "dos", "das"}
_RE_PAREN_FINAL = re.compile(r"^(.*?)\s*\(([^)]*)\)\s*$")
_RE_GENERO = re.compile(r"\s*(\(\s*a\s*\)|/\s*(a|as|o|os|e|es)\b)", re.I)


def _sin_tildes(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _clave(s: str) -> str:
    return " ".join(_sin_tildes(s).lower().split())


def _modalidad(s: str) -> str | None:
    k = _clave(s)
    if "remot" in k or "teletrabajo" in k or "teletreball" in k:
        return "remoto"
    if "hibrid" in k or "semipresencial" in k:
        return "hibrido"
    if "presencial" in k:
        return "presencial"
    return None


def _cap_palabra(p: str, primera: bool) -> str:
    low = p.lower()
    if not primera and low in _CONECTORES:
        return low
    if "-" in p:
        return "-".join(_cap_palabra(x, True) for x in p.split("-"))
    if "'" in p or "’" in p:
        sep = "'" if "'" in p else "’"
        pre, _, resto = low.partition(sep)
        if len(pre) == 1 and not primera:
            return pre + sep + resto[:1].upper() + resto[1:]
        return pre[:1].upper() + pre[1:] + sep + resto[:1].upper() + resto[1:]
    return low[:1].upper() + low[1:]


def _capitalizar(texto: str) -> str:
    return " ".join(_cap_palabra(p, i == 0) for i, p in enumerate(texto.split()))


def capitalizar_nombre(texto: str) -> str:
    """'L'HOSPITALET DE LLOBREGAT' -> "L'Hospitalet de Llobregat" (conectores en minúscula)."""
    return _capitalizar(" ".join((texto or "").split()))


def separar_ubicacion(texto: str | None) -> tuple[str | None, str | None]:
    """Devuelve (ciudad, modalidad). Modalidad en {presencial, hibrido, remoto} o None.

    "España"/"España y otras" es ámbito nacional, no ciudad -> ciudad None.
    """
    if not texto or not texto.strip():
        return None, None
    t = " ".join(texto.split())
    modalidad = None
    m = _RE_PAREN_FINAL.match(t)
    if m:
        t, dentro = m.group(1).strip(), m.group(2)
        modalidad = _modalidad(dentro)
    k = _clave(t)
    if modalidad is None and ("remot" in k or "teletrabajo" in k):
        modalidad = "remoto"
        k = re.sub(r"100\s*%|remot\w*|teletrabajo|\bfull\b", " ", k)
        k = " ".join(k.split())
        t = k  # lo que quede (p. ej. "barcelona") se trata como ciudad
    if not k or k == "espana" or k.startswith("espana y otras"):
        return None, modalidad
    return _capitalizar(t), modalidad


def _norm_huella(s: str | None) -> str:
    if not s:
        return ""
    s = _RE_GENERO.sub("", s)
    s = re.sub(r"[^a-z0-9]+", " ", _sin_tildes(s).lower())
    return " ".join(s.split())


def huella(empresa: str | None, titulo: str | None, ciudad: str | None) -> str:
    """sha1[:16] de 'empresa|titulo|ciudad' normalizados.

    Dos ofertas con la misma huella son el mismo puesto publicado varias veces
    (posiblemente varias vacantes): se agrupan, no se fusionan.
    """
    base = "|".join(_norm_huella(x) for x in (empresa, titulo, ciudad))
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]
