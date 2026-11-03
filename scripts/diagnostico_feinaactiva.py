"""Diagnóstico del XML de datos abiertos de Feina Activa (Generalitat). Solo librería estándar.

Informe de ESTRUCTURA (nunca valores personales): robots.txt, UN GET con tope, parseo en
streaming sin DTD/entidades, estadísticas por ruta, formas de ejemplo y licencia/aviso legal.
No guarda el XML. Sale siempre con código 0 y escribe también en GITHUB_STEP_SUMMARY.
"""
import gzip
import hashlib
import os
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sonda_portales  # noqa: E402
from sonda_portales import USER_AGENT, RedirectSeguro, texto_plano  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from jobhunting.xml_seguro import LectorSeguro, XmlRechazado  # noqa: E402,F401

URL_XML = "https://feinaactiva.gencat.cat/api/offers/offers-xml"
URL_LICENCIAS = "https://administraciodigital.gencat.cat/ca/dades/dades-obertes/informacio-practica/llicencies/"
URL_PORTAL = "https://feinaactiva.gencat.cat/"

from jobhunting.xml_seguro import TOPE_BYTES, TOPE_SEGUNDOS  # noqa: E402  (en red y descomprimidos)
TIMEOUT = 60
MAX_LECTURA_ROBOTS = 500 * 1024
MAX_LECTURA_HTML = 2 * 1024 * 1024
MAX_CHARS_PAGINA = 12000
PAUSA_S = 5
PAUSA_ROBOTS_S = 2

MAX_RUTAS = 2000
MAX_HASHES = 5000
MAX_CATEGORICO = 60
MAX_NIVEL = 4                       # profundidad máxima (raíz=0) donde se busca la oferta
LARGO_FORMA = 40
PERSONAL_EXACTO = {"dni", "nif"}
PERSONAL_PREFIJO = ("email", "mail", "telefon", "phone", "contact", "persona", "nom", "cognom",
                    "nombre", "apellido", "adreca", "adreça", "direccion", "address",
                    "responsable", "cif", "mobil", "movil", "fax", "web", "url")
_RE_6DIG = re.compile(r"\d{6}")
_RE_LEGAL = re.compile(r"av[ií]s\s+legal|aviso\s+legal|condicions\s+d.\s*[uú]s|"
                       r"condiciones\s+de\s+uso|legal", re.I)


# ---------------------------------------------------------------- funciones puras

def forma_valor(s, largo=LARGO_FORMA):
    """Letras -> 'a', mayúsculas -> 'A', dígitos -> '9'; espacios colapsados; recorta."""
    out = []
    for c in " ".join(str(s).split()):
        if c.isdigit():
            out.append("9")
        elif c.isalpha():
            out.append("A" if c.isupper() else "a")
        else:
            out.append(c)
    return "".join(out)[:largo]


def parece_personal(ruta):
    """True si algún segmento/palabra de la ruta sugiere datos personales."""
    tokens = []
    for seg in re.split(r"[^0-9A-Za-z]+", str(ruta)):
        seg = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", seg)  # camelCase
        tokens += [t.lower() for t in seg.split() if t]
    return any(t in PERSONAL_EXACTO or t.startswith(PERSONAL_PREFIJO) for t in tokens)


def es_categorico_seguro(valores, n_no_vacias=None):
    """True si el campo es claramente categórico: <=60 distintos, apariciones no vacías
    >= 5 x distintos, valores <=30 caracteres, sin '@', 'http', 'www.', >=7 dígitos en
    total ni más de 3 palabras."""
    distintos = set(valores)
    if not distintos or len(distintos) > MAX_CATEGORICO:
        return False
    if n_no_vacias is None:
        n_no_vacias = sum(valores.values()) if hasattr(valores, "values") else len(valores)
    if n_no_vacias < 5 * len(distintos):
        return False
    for v in distintos:
        v = str(v)
        bajo = v.lower()
        if (len(v) > 30 or "@" in v or "http" in bajo or "www." in bajo
                or sum(c.isdigit() for c in v) >= 7 or len(v.split()) > 3):
            return False
    return True


def sanea_linea(s):
    """Líneas de salida seguras para el log de Actions: prefijo '| ' y sin '::'."""
    return "\n".join("| " + l.replace("::", ": :") for l in str(s).split("\n"))


def _nombre_local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


class _Ruta:
    __slots__ = ("n", "nv", "suma", "mx", "hashes", "saturado", "formas", "valores", "niv")

    def __init__(self):
        self.n = self.nv = self.suma = self.mx = 0
        self.hashes, self.saturado = set(), False
        self.formas = []
        self.valores = Counter()   # None cuando supera MAX_CATEGORICO distintos
        self.niv = {}              # nivel -> [ultimo id de ancestro, nº de ancestros distintos]


def _registrar(r, v, pila):
    r.nv += 1
    r.suma += len(v)
    r.mx = max(r.mx, len(v))
    if len(r.hashes) < MAX_HASHES:
        r.hashes.add(hashlib.blake2b(v.encode("utf-8", "replace"), digest_size=8).digest())
    else:
        r.saturado = True
    if len(r.formas) < 3:
        f = forma_valor(v)
        if f not in r.formas:
            r.formas.append(f)
    if r.valores is not None:
        r.valores[v[:200]] += 1
        if len(r.valores) > MAX_CATEGORICO:
            r.valores = None
    for k in range(1, min(MAX_NIVEL, len(pila) - 1) + 1):
        e = r.niv.setdefault(k, [0, 0])
        if e[0] != pila[k][1]:
            e[0] = pila[k][1]
            e[1] += 1


def resumen_estructura(eventos):
    """Consume eventos ('start', tag, {attrs}) / ('end', tag, texto) y devuelve el resumen.

    No hace red. La oferta es la ruta repetida más superficial (profundidad >=1).
    """
    rutas, pila, contador, raiz, truncado = {}, [], 0, None, False

    def get(ruta):
        nonlocal truncado
        r = rutas.get(ruta)
        if r is None:
            if len(rutas) >= MAX_RUTAS:
                truncado = True
                return None
            r = rutas[ruta] = _Ruta()
        return r

    for ev in eventos:
        if ev[0] == "start":
            _, tag, attrs = ev
            contador += 1
            pila.append((tag, contador))
            ruta = "/".join(t for t, _ in pila)
            if len(pila) == 1:
                raiz = tag
            r = get(ruta)
            if r:
                r.n += 1
            for a, v in (attrs or {}).items():
                ra = get(f"{ruta}@{_nombre_local(a)}")
                if ra:
                    ra.n += 1
                    v = (v or "").strip()
                    if v:
                        _registrar(ra, v, pila)
        elif ev[0] == "end" and pila:
            v = (ev[2] or "").strip()
            if v:
                r = rutas.get("/".join(t for t, _ in pila))
                if r:
                    _registrar(r, v, pila)
            pila.pop()

    elementos = {p: r for p, r in rutas.items() if "@" not in p}
    repetidas = sorted(((p.count("/"), -r.n, p) for p, r in elementos.items()
                        if r.n > 1 and 1 <= p.count("/") <= MAX_NIVEL))
    oferta = repetidas[0][2] if repetidas else None
    res = {"raiz": raiz, "ruta_oferta": oferta, "n_ofertas": rutas[oferta].n if oferta else 0,
           "candidatos": [(p, -n) for d, n, p in repetidas[:5] if d == repetidas[0][0]],
           "campos": [], "otros": {},
           "n_rutas": len(rutas), "rutas_truncadas": truncado}
    if not oferta:
        return res
    def campos_de(oferta):
        N, nivel = rutas[oferta].n, oferta.count("/")
        campos = []
        for p, r in sorted(rutas.items()):
            if p.startswith(oferta + "/"):
                rel = p[len(oferta) + 1:]
            elif p.startswith(oferta + "@"):
                rel = p[len(oferta):]
            else:
                continue
            con_valor = r.niv.get(nivel, [0, 0])[1]
            campo = {"ruta": rel, "apariciones": r.n, "no_vacias": r.nv,
                     "pct_no_vacio": round(100.0 * con_valor / N, 1),
                     "len_media": round(r.suma / r.nv, 1) if r.nv else 0, "len_max": r.mx,
                     "distintos": len(r.hashes), "distintos_tope": r.saturado,
                     "formas": list(r.formas), "personal": parece_personal(rel),
                     "categorico": None}
            if (r.valores is not None and not campo["personal"] and not r.saturado
                    and es_categorico_seguro(r.valores, r.nv)):
                campo["categorico"] = r.valores.most_common()
            campos.append(campo)
        return campos

    res["campos"] = campos_de(oferta)
    for ruta_c, _ in res["candidatos"]:   # el resto de candidatos (p. ej. sicas/ad)
        if ruta_c != oferta:
            res["otros"][ruta_c] = campos_de(ruta_c)
    return res


def formatear_estructura(res):
    """Resumen -> lista de líneas de texto (sin valores salvo categóricos seguros)."""
    L = [f"Raiz: {res['raiz']}",
         f"Oferta (ruta repetida mas superficial): {res['ruta_oferta']}  n_ofertas={res['n_ofertas']}",
         f"Candidatos (ruta, n): {res['candidatos']}",
         f"Rutas distintas: {res['n_rutas']}" + ("  (TRUNCADO a %d)" % MAX_RUTAS
                                                if res["rutas_truncadas"] else "")]
    if not res["ruta_oferta"]:
        L.append("No se detecta un elemento oferta repetido.")
        return L
    todos = [(res["ruta_oferta"], res["campos"])] + list(res.get("otros", {}).items())
    for ruta_c, campos in todos:
        L += ["", f"== Campos de {ruta_c} ==",
              "ruta | apar | %ofertas_no_vacio | len_media | len_max | distintos | formas"]
        for c in campos:
            d = f"{c['distintos']}{'+' if c['distintos_tope'] else ''}"
            L.append(f"{c['ruta']} | {c['apariciones']} | {c['pct_no_vacio']} | {c['len_media']} "
                     f"| {c['len_max']} | {d} | " + " ; ".join(c["formas"]))
    cats = [(r, c) for r, cs in todos for c in cs if c["categorico"]]
    L += ["", "== Recuento por valor (<=60 distintos, solo categoricos claros) =="]
    for r, c in cats:
        L.append(f"{r}:{c['ruta']}: " + ", ".join(f"{v[:60]}={n}" for v, n in c["categorico"]))
    L += ["", "== Rutas que sugieren datos personales (decidir que NO guardar) =="]
    pers = [(r, c) for r, cs in todos for c in cs if c["personal"]]
    L += [f"{c['ruta']}: {c['pct_no_vacio']}% no vacio" for r, c in pers] or ["(ninguna)"]
    return L


def resumen_robots(texto, ruta_url="/", agentes=("*",), usar_ua=None, max_lineas=40):
    """Líneas Disallow/Allow/Crawl-delay de los grupos de '*' y de nuestro agente."""
    ua_ours = (usar_ua or USER_AGENT).lower()
    grupos, uas, reglas, previo_regla = [], [], [], False
    for linea in (texto or "").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if ":" not in linea:
            continue
        k, v = (x.strip() for x in linea.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if previo_regla:
                grupos.append((uas, reglas))
                uas, reglas, previo_regla = [], [], False
            uas.append(v)
        elif k in ("disallow", "allow", "crawl-delay"):
            reglas.append((k, v))
            previo_regla = True
    if uas:
        grupos.append((uas, reglas))
    out = []
    for uas_g, reglas_g in grupos:
        rel = [u for u in uas_g if u in agentes or (u != "*" and u.lower() in ua_ours)]
        if not rel:
            continue
        for k, v in reglas_g:
            marca = ""
            if k in ("disallow", "allow") and v and ruta_url.startswith(v.rstrip("*")):
                marca = "   <-- aplica a la URL"
            out.append(f"[{','.join(rel)}] {k.capitalize()}: {v}{marca}")
    return out[:max_lineas] or ["(sin reglas para * ni para nuestro agente)"]


class _Enlaces(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.enlaces, self._href, self._txt = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href, self._txt = dict(attrs).get("href"), []

    def handle_data(self, data):
        if self._href is not None:
            self._txt.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.enlaces.append((self._href, " ".join("".join(self._txt).split())))
            self._href = None


def buscar_enlace_legal(html, base_url):
    """Primer enlace http(s) cuyo texto/href parezca aviso legal / condiciones de uso."""
    p = _Enlaces()
    try:
        p.feed(html or "")
        p.close()
    except Exception:
        pass
    for href, txt in p.enlaces:
        if href and _RE_LEGAL.search(f"{txt} {href}"):
            url = urljoin(base_url, href)
            u = urlparse(url)
            host = (u.hostname or "").lower()
            if u.scheme in ("http", "https") and (host == "gencat.cat"
                                                  or host.endswith(".gencat.cat")):
                return url
    return None


# ---------------------------------------------------------------- red

def cargar_robots(url):
    """(estado, texto, rp) por origen. estado: 'ok' | 'sin_robots' | 'error'.

    Descarga con el opener propio de la sonda (<=5 redirecciones, sin handler de la sonda)
    y cache por host de la sonda. 3xx sin resolver, 5xx o error = no concluyente.
    """
    p = urlparse(url)
    origen = f"{p.scheme}://{p.netloc}"
    cache = sonda_portales._ROBOTS_CACHE
    if origen not in cache:
        cache[origen] = sonda_portales._cargar_robots(origen)
    rp = cache[origen]
    if rp is True:
        return ("sin_robots", "", None)
    if rp is None:
        return ("error_no_concluyente", "", None)
    return ("ok", getattr(rp, "texto", ""), rp)


def robots_permitido(url):
    """True / False / None (no concluyente)."""
    return sonda_portales.robots_permitido(url)


class _Contador:
    """Cuenta bytes en red (antes de descomprimir) y aplica el tope."""

    def __init__(self, f, tope=TOPE_BYTES):
        self.f, self.tope, self.total = f, tope, 0

    def read(self, n=-1):
        chunk = self.f.read(n)
        self.total += len(chunk)
        if self.total > self.tope:
            raise XmlRechazado("supera el tope de bytes en red")
        return chunk


def eventos_desde_iterparse(fuente, errores):
    """iterparse en streaming -> eventos puros; libera con clear(). Errores a `errores`."""
    try:
        for ev, el in ET.iterparse(fuente, events=("start", "end")):
            tag = _nombre_local(el.tag)
            if ev == "start":
                yield ("start", tag, {_nombre_local(k): v for k, v in el.attrib.items()})
            else:
                yield ("end", tag, el.text)
                el.clear()
    except Exception as e:  # ParseError, XmlRechazado, red...
        errores.append(f"{type(e).__name__}: {str(e)[:150]}")


def _opener():
    # build_opener no añade cookies; los redirects se validan contra robots.txt
    red = RedirectSeguro(robots=robots_permitido)
    return urllib.request.build_opener(red), red


def descargar_y_resumir(url, informe):
    """UN GET, sin reintentos. Devuelve el resumen de estructura o None."""
    opener, red = _opener()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept-Encoding": "gzip"})
    t0, errores = time.monotonic(), []
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            h = r.headers
            uf = urlparse(r.geturl())
            informe(f"status={r.status} url_final={uf.scheme}://{uf.hostname}{uf.path}")
            informe(f"content-type={h.get('Content-Type')} content-encoding={h.get('Content-Encoding')} "
                    f"content-length={h.get('Content-Length')}")
            informe(f"last-modified={h.get('Last-Modified')} etag={h.get('ETag')} "
                    f"cache-control={h.get('Cache-Control')}")
            red_c = _Contador(r)
            flujo = red_c
            if (h.get("Content-Encoding") or "").lower() == "gzip":
                flujo = gzip.GzipFile(fileobj=red_c)
            lector = LectorSeguro(flujo)
            res = resumen_estructura(eventos_desde_iterparse(lector, errores))
            informe(f"bytes_red={red_c.total} bytes_xml={lector.total} "
                    f"ms={int((time.monotonic() - t0) * 1000)}")
    except urllib.error.HTTPError as e:
        informe(f"status={e.code} (sin parseo, sin reintento) ms={int((time.monotonic() - t0) * 1000)}")
        if red.bloqueo:
            informe(f"redirect bloqueado: {red.bloqueo}")
        return None
    except Exception as e:
        informe(f"excepcion en la descarga: {type(e).__name__}: {str(e)[:150]}")
        return None
    if red.bloqueo:
        informe(f"redirect bloqueado: {red.bloqueo}")
    for e in errores:
        informe(f"AVISO parseo/lectura: {e}")
    return res


def descargar_html(url):
    """GET de una página (robots + redirects seguros). -> (status, html, error)."""
    ok = robots_permitido(url)
    if ok is not True:
        return None, "", "prohibido_robots" if ok is False else "robots_no_leido"
    time.sleep(PAUSA_ROBOTS_S)
    opener, red = _opener()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.status, r.read(MAX_LECTURA_HTML).decode("utf-8", "replace"), red.bloqueo
    except urllib.error.HTTPError as e:
        return e.code, "", red.bloqueo
    except Exception as e:
        return None, "", f"excepcion:{type(e).__name__}"


def volcar_pagina(nombre, url, informe):
    """Vuelca texto plano; devuelve el HTML (o '') para buscar enlaces."""
    informe(f"===== {nombre} {url} =====")
    status, html, err = descargar_html(url)
    if err or status is None or status >= 400:
        informe(f"[sin texto: status={status} {err or ''}]")
        return "", status
    informe(f"status={status}")
    informe(texto_plano(html, MAX_CHARS_PAGINA))
    return html, status


# ---------------------------------------------------------------- principal

def main():
    salida = []

    def informe(s=""):
        s = sanea_linea(s)
        print(s, flush=True)
        salida.append(s)

    informe(f"# Diagnostico Feina Activa  {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    parar_xml = False
    try:
        informe("\n## 1. robots.txt")
        estado, texto, rp = cargar_robots(URL_XML)
        informe(f"estado={estado}")
        ruta = urlparse(URL_XML).path
        for l in resumen_robots(texto, ruta):
            informe(l)
        if rp is not None:
            informe(f"crawl-delay (nuestro agente)={rp.crawl_delay(USER_AGENT)}")
        permitido = robots_permitido(URL_XML)
        informe(f"permitido para {URL_XML}: {permitido}")
        parar_xml = permitido is not True
        if parar_xml:
            informe("PARAR: robots prohibido o no concluyente; no se descarga el XML.")
    except Exception as e:
        parar_xml = True
        informe(f"excepcion en robots: {type(e).__name__}")

    bloqueado = False
    if not parar_xml:
        try:
            informe("\n## 2-4. Descarga y estructura")
            time.sleep(PAUSA_ROBOTS_S)
            res = descargar_y_resumir(URL_XML, informe)
            if res is not None:
                for l in formatear_estructura(res):
                    informe(l)
            else:
                bloqueado = True  # error/403/429: no insistir
        except Exception as e:
            informe(f"excepcion en el analisis: {type(e).__name__}: {str(e)[:150]}")

    try:
        informe("\n## 5. Licencias y aviso legal (texto plano)")
        time.sleep(PAUSA_S)
        volcar_pagina("Licencias datos abiertos Generalitat", URL_LICENCIAS, informe)
        time.sleep(PAUSA_S)
        html, status = volcar_pagina("Feina Activa portal", URL_PORTAL, informe)
        if status in (403, 429):
            informe("Bloqueo del host: no se sigue.")
        else:
            enlace = buscar_enlace_legal(html, URL_PORTAL)
            if enlace:
                time.sleep(PAUSA_S)
                volcar_pagina("Aviso legal (enlace encontrado)", enlace, informe)
            else:
                informe("No se encontro enlace a aviso legal / condiciones de uso en el HTML "
                        "(puede ser una SPA que lo carga con JavaScript).")
    except Exception as e:
        informe(f"excepcion en paginas: {type(e).__name__}")

    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        try:
            with open(resumen, "a", encoding="utf-8") as f:
                f.write("```\n" + "\n".join(salida).replace("```", "'''") + "\n```\n")
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException as e:  # nunca romper el informe
        print(f"excepcion: {type(e).__name__}")
    sys.exit(0)
