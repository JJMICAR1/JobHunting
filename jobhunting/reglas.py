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
_CLAVES = ("si", "no", "ciudades", "modalidades", "ignorar")
# Aprendizaje automatico
MIN_ETIQUETAS = 10
MIN_APARICIONES = 3
UMBRAL_SI, UMBRAL_NO = 0.7, 0.2
TOPE_APRENDIDOS = 30
STOPWORDS = frozenset("de del la el y i en para per con amb a o les els los las un una al".split())


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
    ignorar: tuple[str, ...] = ()   # terminos que el aprendizaje no usa nunca (/olvidar)

    def vacia(self) -> bool:
        """Sin criterios de puntuacion (`ignorar` no puntua)."""
        return not (self.si or self.no or self.ciudades or self.modalidades)

    def a_dict(self) -> dict:
        d = {k: list(getattr(self, k)) for k in _CLAVES if k != "ignorar"}
        if self.ignorar:
            d["ignorar"] = list(self.ignorar)
        return d

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
    "/olvidar <término>  el aprendizaje automático no lo usará nunca\n"
    "/ciudad <nombre>\n"
    "/modalidad presencial|hibrido|remoto\n"
    "/lote <1-30>  ofertas por día\n"
    "/ver  tus reglas, lo que he aprendido de tus Sí/No y el progreso\n"
    "/ayuda\n"
    "Además aprendo solo de tus Sí/No (desde 10 etiquetas); lo que escribas aquí manda sobre lo aprendido."
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
    # El progreso va primero: si el texto se recorta (4000 car.), no se pierde.
    lines = [
        f"Progreso: {p.get('total', 0)}/{p.get('meta', META)} (Sí {p.get('si', 0)}, No {p.get('no', 0)})",
        f"Sí: {l(r.si)}", f"No: {l(r.no)}", f"Ciudades: {l(r.ciudades)}", f"Modalidades: {l(r.modalidades)}",
    ]
    if r.ignorar:
        lines.append(f"Ignorados: {l(r.ignorar)}")
    a = p.get("auto")
    if a:
        lines.append("Aprendido de tus Sí/No: " + "; ".join(
            f"{n}: {l(a.get(k) or [])}" for n, k in (("Sí", "si"), ("No", "no"), ("Ciudades", "ciudades"),
                                                     ("Modalidades", "modalidades")) if a.get(k)))
    elif "auto" in p:
        lines.append(f"Aprendido de tus Sí/No: nada todavía (necesito {MIN_ETIQUETAS} etiquetas)")
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
    if cmd == "/olvidar":
        n = normalizar(arg)
        if not n:
            return reglas, "Uso: /olvidar <término>"
        if len(n) > MAX_TERMINO:
            return reglas, f"Término demasiado largo (máximo {MAX_TERMINO} caracteres)"
        if n in reglas.ignorar:
            return reglas, f"Ya estaba ignorado: {n}"
        if len(reglas.ignorar) >= MAX_LISTA:
            return reglas, f"Lista llena (máximo {MAX_LISTA} términos)"
        return _con(reglas, ignorar=reglas.ignorar + (n,)), f"Olvidado: {n} (no lo usaré al aprender)"
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


def _terminos(titulo) -> set[str]:
    """Palabras (3+ letras, sin stopwords) y bigramas contiguos del titulo normalizado."""
    toks = normalizar(titulo).split()
    ok = [len(t) >= 3 and t not in STOPWORDS for t in toks]
    t = {x for x, v in zip(toks, ok) if v}
    t |= {f"{a} {b}" for a, b, va, vb in zip(toks, toks[1:], ok, ok[1:]) if va and vb}
    return t


def _elegir(cuentas: dict, ignorar: set, umbral_si=None, umbral_no=None):
    """Terminos con suficiente evidencia segun la tasa suavizada. Mas evidencia primero, luego alfabetico."""
    si, no = [], []
    for term, (n_si, n) in cuentas.items():
        if n < MIN_APARICIONES or term in ignorar or len(term) > MAX_TERMINO:
            continue
        tasa = (n_si + 1) / (n + 2)
        if umbral_si is not None and tasa >= umbral_si:
            si.append((-n, term))
        elif umbral_no is not None and tasa <= umbral_no:
            no.append((-n, term))
    return ([t for _, t in sorted(si)[:TOPE_APRENDIDOS]], [t for _, t in sorted(no)[:TOPE_APRENDIDOS]])


def aprender(etiquetadas, ignorar=()) -> Reglas:
    """Reglas aprendidas de ofertas etiquetadas (puro, determinista).

    `etiquetadas`: dicts {titulo, empresa, ciudad, modalidad, etiqueta(bool)}. Con menos de MIN_ETIQUETAS
    devuelve Reglas vacia. Un termino con >= MIN_APARICIONES etiquetas va a `si` si su tasa suavizada
    (si+1)/(n+2) es >= 0,7 y a `no` si es <= 0,2; ciudades y modalidades, solo a la lista positiva (>= 0,7).
    Maximo TOPE_APRENDIDOS por lista. Los terminos de `ignorar` no se usan nunca.
    """
    etiquetadas = list(etiquetadas)
    if len(etiquetadas) < MIN_ETIQUETAS:
        return Reglas()
    ign = {normalizar(x) for x in ignorar}
    pal: dict[str, list[int]] = {}
    ciu: dict[str, list[int]] = {}
    mod: dict[str, list[int]] = {}

    def sumar(d, k, et):
        c = d.setdefault(k, [0, 0])
        c[0] += 1 if et else 0
        c[1] += 1

    for e in etiquetadas:
        et = bool(e["etiqueta"])
        for t in _terminos(e.get("titulo")):
            sumar(pal, t, et)
        c = normalizar(e.get("ciudad"))
        if c:
            sumar(ciu, c, et)
        m = normalizar(e.get("modalidad"))
        if m in MODALIDADES:
            sumar(mod, m, et)
    si, no = _elegir(pal, ign, UMBRAL_SI, UMBRAL_NO)
    return Reglas(si=tuple(si), no=tuple(no),
                  ciudades=tuple(_elegir(ciu, ign, UMBRAL_SI)[0]),
                  modalidades=tuple(_elegir(mod, ign, UMBRAL_SI)[0]))


def combinar(manuales: Reglas, auto: Reglas) -> Reglas:
    """Union de manuales + aprendidas. Un termino manual manda: si esta en `no` manual no entra en `si` auto, y al reves."""
    def mas(a, b, excluir):
        return a + tuple(x for x in b if x not in a and x not in excluir)
    return Reglas(si=mas(manuales.si, auto.si, manuales.no),
                  no=mas(manuales.no, auto.no, manuales.si),
                  ciudades=mas(manuales.ciudades, auto.ciudades, ()),
                  modalidades=mas(manuales.modalidades, auto.modalidades, ()),
                  ignorar=manuales.ignorar)
