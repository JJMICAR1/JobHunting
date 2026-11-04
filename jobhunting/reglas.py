"""Reglas de puntuacion y comandos de Telegram (puro: sin BD ni red).

Formato de `config.reglas`: {"si": [...], "no": [...], "ciudades": [...], "modalidades": [...]}.
Todo se compara normalizado (minusculas, sin tildes) y por palabra o frase completa, no por subcadena.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from jobhunting.normalizar import _sin_tildes

MAX_TERMINO = 60
MAX_LISTA = 200
MODALIDADES = ("presencial", "hibrido", "remoto")
LOTE_MIN, LOTE_MAX = 1, 30
META = 100
PTS_SI, PTS_NO, PTS_CIUDAD, PTS_MODALIDAD = 1.0, -3.0, 0.5, 0.5
_CLAVES = ("si", "no", "ciudades", "modalidades")


def normalizar(s: str | None) -> str:
    """Minusculas, sin tildes; todo lo que no sea letra, cifra, '+' o '#' pasa a espacio."""
    if not s:
        return ""
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", _sin_tildes(s).lower()).split())


def _contiene(texto_norm: str, termino_norm: str) -> bool:
    return bool(termino_norm) and f" {termino_norm} " in f" {texto_norm} "


@dataclass(frozen=True)
class Reglas:
    si: tuple[str, ...] = ()
    no: tuple[str, ...] = ()
    ciudades: tuple[str, ...] = ()
    modalidades: tuple[str, ...] = ()

    def vacia(self) -> bool:
        return not (self.si or self.no or self.ciudades or self.modalidades)

    def a_dict(self) -> dict:
        return {k: list(getattr(self, k)) for k in _CLAVES}

    @classmethod
    def desde_dict(cls, d) -> "Reglas":
        """Valida y normaliza. Lanza ValueError si el formato no es correcto."""
        if d is None:
            return cls()
        if not isinstance(d, dict):
            raise ValueError("las reglas deben ser un objeto")
        extra = set(d) - set(_CLAVES)
        if extra:
            raise ValueError(f"claves desconocidas: {sorted(extra)}")
        campos = {}
        for k in _CLAVES:
            v = d.get(k, [])
            if not isinstance(v, (list, tuple)) or not all(isinstance(x, str) for x in v):
                raise ValueError(f"'{k}' debe ser una lista de textos")
            vistos: list[str] = []
            for x in v:
                n = normalizar(x)
                if not n or len(n) > MAX_TERMINO:
                    raise ValueError(f"término no válido en '{k}'")
                if k == "modalidades" and n not in MODALIDADES:
                    raise ValueError(f"modalidad no válida: {n}")
                if n not in vistos:
                    vistos.append(n)
            if len(vistos) > MAX_LISTA:
                raise ValueError(f"'{k}' supera {MAX_LISTA} términos")
            campos[k] = tuple(vistos)
        return cls(**campos)


def puntuar(titulo, empresa, ciudad, modalidad, reglas: Reglas) -> tuple[float, list[str]]:
    """Nota y motivos. si: +1 (titulo); no: -3 (titulo o empresa); ciudad/modalidad: +0,5 si coinciden."""
    t, e = normalizar(titulo), normalizar(empresa)
    nota = 0.0
    motivos: list[str] = []
    for x in reglas.si:
        if _contiene(t, x):
            nota += PTS_SI
            motivos.append(x)
    for x in reglas.no:
        if _contiene(t, x) or _contiene(e, x):
            nota += PTS_NO
            motivos.append(f"-{x}")
    c = normalizar(ciudad)
    if reglas.ciudades and c and c in reglas.ciudades:
        nota += PTS_CIUDAD
        motivos.append(ciudad.strip())
    m = normalizar(modalidad)
    if reglas.modalidades and m and m in reglas.modalidades:
        nota += PTS_MODALIDAD
        motivos.append(m)
    return nota, motivos


AYUDA = (
    "Comandos:\n"
    "/si <término>  suma al título\n"
    "/no <término>  resta (título o empresa)\n"
    "/quitar <término>  lo quita de las listas\n"
    "/ciudad <nombre>\n"
    "/modalidad presencial|hibrido|remoto\n"
    "/lote <1-30>  ofertas por día\n"
    "/ver  reglas y progreso\n"
    "/ayuda"
)


def parsear_lote(texto: str) -> int | str | None:
    """None si no es /lote; int si es valido; str (mensaje de error) si el argumento no sirve."""
    cmd, arg = _partir(texto)
    if cmd != "/lote":
        return None
    try:
        n = int(arg)
    except ValueError:
        return f"Uso: /lote <{LOTE_MIN}-{LOTE_MAX}>"
    if not LOTE_MIN <= n <= LOTE_MAX:
        return f"Uso: /lote <{LOTE_MIN}-{LOTE_MAX}>"
    return n


def _partir(texto: str) -> tuple[str, str]:
    partes = (texto or "").strip().split(None, 1)
    if not partes:
        return "", ""
    cmd = partes[0].split("@", 1)[0].lower()
    return cmd, partes[1].strip() if len(partes) > 1 else ""


def _ver(r: Reglas, progreso: dict) -> str:
    def l(xs):
        return ", ".join(xs) if xs else "(vacío)"
    p = progreso or {}
    lines = [
        f"Sí: {l(r.si)}", f"No: {l(r.no)}", f"Ciudades: {l(r.ciudades)}", f"Modalidades: {l(r.modalidades)}",
        f"Progreso: {p.get('total', 0)}/{p.get('meta', META)} (Sí {p.get('si', 0)}, No {p.get('no', 0)})",
    ]
    if "lote" in p:
        lines.append(f"Lote: {p['lote']} al día")
    return "\n".join(lines)


def _con(r: Reglas, **cambios) -> Reglas:
    return Reglas(**{**{k: getattr(r, k) for k in _CLAVES}, **cambios})


def aplicar_comando(reglas: Reglas, texto: str, progreso: dict | None = None) -> tuple[Reglas, str]:
    """Aplica un comando y devuelve (reglas_nuevas, respuesta). Idempotente (conjuntos).

    `/lote` no cambia las reglas (el lote vive en otra clave de config): ver `parsear_lote`.
    """
    cmd, arg = _partir(texto)
    if cmd in ("/ayuda", "/start", "/help"):
        return reglas, AYUDA
    if cmd == "/ver":
        return reglas, _ver(reglas, progreso or {})
    if cmd == "/lote":
        n = parsear_lote(texto)
        return reglas, n if isinstance(n, str) else f"Lote: {n} al día"
    if cmd in ("/si", "/no", "/ciudad"):
        clave, otra = {"/si": ("si", "no"), "/no": ("no", "si"), "/ciudad": ("ciudades", None)}[cmd]
        n = normalizar(arg)
        if not n:
            return reglas, f"Uso: {cmd} <término>"
        if len(n) > MAX_TERMINO:
            return reglas, f"Término demasiado largo (máximo {MAX_TERMINO} caracteres)"
        actual = getattr(reglas, clave)
        if n in actual:
            return reglas, f"Ya estaba: {n}"
        if len(actual) >= MAX_LISTA:
            return reglas, f"Lista llena (máximo {MAX_LISTA} términos)"
        cambios = {clave: actual + (n,)}
        if otra:  # un termino no puede sumar y restar a la vez: el ultimo comando gana
            cambios[otra] = tuple(x for x in getattr(reglas, otra) if x != n)
        return _con(reglas, **cambios), f"Añadido a {clave}: {n}"
    if cmd == "/modalidad":
        n = normalizar(arg)
        if n not in MODALIDADES:
            return reglas, "Uso: /modalidad presencial|hibrido|remoto"
        if n in reglas.modalidades:
            return reglas, f"Ya estaba: {n}"
        return _con(reglas, modalidades=reglas.modalidades + (n,)), f"Añadida modalidad: {n}"
    if cmd == "/quitar":
        n = normalizar(arg)
        if not n:
            return reglas, "Uso: /quitar <término>"
        cambios = {k: tuple(x for x in getattr(reglas, k) if x != n) for k in _CLAVES}
        if all(cambios[k] == getattr(reglas, k) for k in _CLAVES):
            return reglas, f"No estaba: {n}"
        return _con(reglas, **cambios), f"Quitado: {n}"
    return reglas, "Comando no reconocido. /ayuda"
