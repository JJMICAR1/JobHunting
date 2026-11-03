"""Lectura segura de XML externo (sin red): rechaza DTD/ENTITY, UTF-16, exceso de bytes y de tiempo.

Se usa como "fichero" para ET.iterparse. Compartido por el parser de Feina Activa y el diagnostico.
"""
from __future__ import annotations

import re
import time

TOPE_BYTES = 200 * 1024 * 1024      # tope de bytes por defecto
TOPE_SEGUNDOS = 300                 # tope de tiempo de lectura por defecto
_RE_DTD = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


class XmlRechazado(Exception):
    pass


class LectorSeguro:
    """Fichero de solo lectura: rechaza DTD/ENTITY, UTF-16, exceso de bytes y de tiempo."""

    def __init__(self, fuente, tope=TOPE_BYTES, segundos=TOPE_SEGUNDOS):
        self.f, self.tope, self.total, self.cola = fuente, tope, 0, b""
        self.limite = time.monotonic() + segundos

    def read(self, n=65536):
        chunk = self.f.read(n)
        if not chunk:
            return chunk
        if self.total == 0 and b"\x00" in chunk[:4096]:
            raise XmlRechazado("codificacion no soportada (nulos en los primeros 4 KB)")
        self.total += len(chunk)
        if self.total > self.tope:
            raise XmlRechazado("supera el tope de bytes")
        if time.monotonic() > self.limite:
            raise XmlRechazado("supera el tope de tiempo")
        if _RE_DTD.search(self.cola + chunk):
            raise XmlRechazado("DOCTYPE/ENTITY rechazado")
        self.cola = (self.cola + chunk)[-16:]
        return chunk
