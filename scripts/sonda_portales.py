"""Sonda de viabilidad (Fase 2): ¿responde cada portal para búsquedas en Catalunya?

Una petición GET por portal, sin login ni cookies, respetando robots.txt.
No guarda el cuerpo HTML. Sale siempre con código 0 (es un informe).
"""
import argparse
import json
import re
import os
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

USER_AGENT = "JobHuntingSonda/0.1 (+https://github.com/JJMICAR1/JobHunting)"
TIMEOUT = 20
PAUSA_S = 5
PAUSA_ROBOTS_S = 2  # entre robots.txt y la búsqueda del mismo host

# Config: nombre, URL de búsqueda pública, palabras esperadas en un HTML de ofertas.
PORTALES = [
    {"portal": "Jooble", "url": "https://es.jooble.org/trabajo-empleo/Barcelona",
     "esperadas": ["jooble", "oferta", "empleo", "trabajo"]},
    {"portal": "InfoJobs", "url": "https://www.infojobs.net/ofertas-trabajo/barcelona",
     "esperadas": ["infojobs", "oferta", "empleo", "trabajo"]},
    {"portal": "Tecnoempleo", "url": "https://www.tecnoempleo.com/ofertas-trabajo/?provincia=9",
     "esperadas": ["tecnoempleo", "oferta", "empleo", "trabajo"]},
    {"portal": "LinkedIn", "url": "https://www.linkedin.com/jobs/search/?location=Barcelona",
     "esperadas": ["linkedin", "job", "empleo", "trabajo"]},
    {"portal": "Glassdoor", "url": "https://www.glassdoor.es/Empleo/barcelona-empleo-SRCH_IL.0,9_IC2677052.htm",
     "esperadas": ["glassdoor", "empleo", "oferta", "trabajo"]},
]

MAX_LECTURA = 5 * 1024 * 1024   # tope de lectura para xml/json (5 MB)
MAX_CAMPOS = 30                 # nº de nombres de campo distintos que se registran
MAX_TEXTO_CONDICIONES = 15000   # caracteres por página de condiciones
MAX_LECTURA_CONDICIONES = 2 * 1024 * 1024
MAX_LECTURA_ROBOTS = 500 * 1024  # tope de lectura de robots.txt
MAX_REDIRECTS = 3

_JSON = ["{", "[", "title", "jobs"]
_XML = ["<offer", "<oferta", "<job", "<?xml"]


def _p(portal, url, tipo="html", esperadas=None):
    return {"portal": portal, "url": url, "tipo": tipo, "max_bytes": MAX_LECTURA,
            "esperadas": esperadas or (_XML if tipo == "xml" else _JSON if tipo == "json"
                                       else [portal.split()[0].lower(), "oferta", "empleo",
                                             "trabajo", "job"])}


# Fase 4: portales nuevos. tipo: html (defecto) | xml | json.
PORTALES_FASE4 = [
    _p("Feina Activa XML", "https://feinaactiva.gencat.cat/api/offers/offers-xml", "xml"),
    _p("Feina Activa Socrata datos",
       "https://analisi.transparenciacatalunya.cat/resource/32kr-h32h.json?$limit=5", "json"),
    _p("Feina Activa Socrata meta",
       "https://analisi.transparenciacatalunya.cat/api/views/32kr-h32h.json", "json"),
    _p("Feina Activa web", "https://feinaactiva.gencat.cat/"),
    _p("Infoempleo", "https://www.infoempleo.com/trabajo/en_barcelona/"),
    _p("Ticjob", "https://www.ticjob.es/esp/busqueda?keywords=&location=barcelona"),
    _p("Indeed", "https://es.indeed.com/jobs?l=Barcelona"),
    _p("Talent.com", "https://es.talent.com/jobs?l=Barcelona"),
    _p("Jobfluent", "https://www.jobfluent.com/es/empleos-barcelona"),
    _p("Careerjet", "https://www.careerjet.es/empleo-barcelona.html"),
    _p("Welcome to the Jungle", "https://www.welcometothejungle.com/es/jobs?aroundQuery=Barcelona"),
    _p("Barcelona Activa Porta22", "https://treball.barcelonactiva.cat/porta22/cat/"),
    _p("SEPE Empleate", "https://www.empleate.gob.es/empleo/"),
    _p("EURES", "https://europa.eu/eures/portal/jv-se/search?lang=es"),
    _p("ATS Greenhouse glovo", "https://boards-api.greenhouse.io/v1/boards/glovo/jobs", "json"),
    _p("ATS Greenhouse typeform", "https://boards-api.greenhouse.io/v1/boards/typeform/jobs", "json"),
    _p("ATS Lever wallapop", "https://api.lever.co/v0/postings/wallapop?mode=json", "json"),
    _p("ATS Ashby factorial", "https://api.ashbyhq.com/posting-api/job-board/factorial", "json"),
    _p("ATS SmartRecruiters Glovo",
       "https://api.smartrecruiters.com/v1/companies/Glovo/postings?limit=5", "json"),
    _p("Feed Arbeitnow", "https://www.arbeitnow.com/api/job-board-api", "json"),
    _p("Feed Remotive", "https://remotive.com/api/remote-jobs?limit=5", "json"),
]

# Páginas de condiciones/licencias (solo se vuelca su texto público al log).
CONDICIONES = [
    {"nombre": "InfoJobs condiciones API",
     "url": "https://developer.infojobs.net/legal/legal/terms-of-use.xhtml"},
    {"nombre": "InfoJobs quick start",
     "url": "https://developer.infojobs.net/documentation/quick-start/index.xhtml"},
    {"nombre": "Jooble API", "url": "https://jooble.org/api/about"},
    {"nombre": "Jooble ayuda REST",
     "url": "https://jooblehelpcenter.freshdesk.com/en/support/solutions/articles/60001448238-rest-api-documentation"},
    {"nombre": "Feina Activa dataset datos.gob.es",
     "url": "https://datos.gob.es/es/catalogo/a09002970-portal-feina-activa-ofertas-de-empleo"},
    {"nombre": "Licencia datos abiertos Generalitat",
     "url": "https://web.gencat.cat/ca/menu-ajuda/ajuda/avis_legal/"},
    {"nombre": "Careerjet API partners", "url": "https://www.careerjet.es/partners/api"},
    {"nombre": "Adzuna API terms", "url": "https://developer.adzuna.com/docs/terms_of_service"},
]

GRUPOS = {"fase2": PORTALES, "fase4": PORTALES_FASE4, "condiciones": CONDICIONES}

from jobhunting.bloqueo import (  # noqa: E402
    ESPERADAS_GENERICAS, MARCAS_BLOQUEO, MARCAS_LOGIN, MAX_BYTES_BLOQUEO, STATUS_BLOQUEO,
    clasificar,
)


def resumen_html(html):
    """Datos no personales para revisar a mano: título y recuentos de palabras."""
    bajo = (html or "").lower()
    m = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.I | re.S)
    titulo = " ".join(m.group(1).split())[:80] if m else ""
    return {"titulo": titulo.replace("|", "/"),
            "n_oferta": bajo.count("oferta"), "n_empleo": bajo.count("empleo"),
            "n_just_a_moment": bajo.count("just a moment")}


class _Texto(HTMLParser):
    _SALTAR = {"script", "style", "noscript", "template", "head", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes, self._prof = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SALTAR:
            self._prof += 1

    def handle_endtag(self, tag):
        if tag in self._SALTAR and self._prof:
            self._prof -= 1

    def handle_data(self, data):
        if not self._prof:
            self.partes.append(data)


def texto_plano(html, max_chars=MAX_TEXTO_CONDICIONES):
    """HTML -> texto plano sin scripts/estilos/etiquetas, espacios colapsados, recortado."""
    p = _Texto()
    try:
        p.feed(html or "")
        p.close()
    except Exception:
        pass
    return " ".join(" ".join(p.partes).split())[:max_chars]


def _añadir_campos(campos, nombre):
    if nombre not in campos and len(campos) < MAX_CAMPOS:
        campos.append(nombre)


def _campos_json(obj, campos):
    """Recorre en anchura y añade solo nombres de clave distintos (nunca valores)."""
    cola = [obj]
    visitados = 0
    while cola and len(campos) < MAX_CAMPOS and visitados < 5000:
        x = cola.pop(0)
        visitados += 1
        if isinstance(x, dict):
            for k, v in x.items():
                _añadir_campos(campos, str(k)[:60])
                if isinstance(v, (dict, list)):
                    cola.append(v)
        elif isinstance(x, list):
            cola.extend(i for i in x[:50] if isinstance(i, (dict, list)))


def _lista_principal(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        listas = [v for v in obj.values() if isinstance(v, list)]
        if listas:
            return max(listas, key=len)
    return None


_CLAVES_UBIC = ("location", "city", "country", "ubicacion", "office", "region", "place")
_RE_UBIC = re.compile(r"barcelona|spain|espa[nñ]a", re.I)


def _textos_ubicacion(x, dentro=False, prof=0):
    """Cadenas bajo claves tipo location/city/country (genérico, sin exactitud)."""
    if prof > 6:
        return
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _textos_ubicacion(v, dentro or any(c in str(k).lower() for c in _CLAVES_UBIC), prof + 1)
    elif isinstance(x, list):
        for v in x[:50]:
            yield from _textos_ubicacion(v, dentro, prof + 1)
    elif dentro and isinstance(x, str):
        yield x


def contar_ubicacion_bcn_es(items):
    """Nº de ofertas cuyo campo de ubicación menciona Barcelona/Spain/España."""
    return sum(1 for it in (items or []) if any(_RE_UBIC.search(t) for t in _textos_ubicacion(it)))


def resumen_json(texto):
    """JSON -> {parsea, n_items, campos, n_ubic_bcn_es}. Solo nombres de campo y recuentos."""
    r = {"parsea": False, "n_items": None, "campos": [], "n_ubic_bcn_es": None}
    try:
        obj = json.loads(texto)
    except Exception:
        return r
    r["parsea"] = True
    lista = _lista_principal(obj)
    if lista is not None:
        r["n_items"] = len(lista)
        r["n_ubic_bcn_es"] = contar_ubicacion_bcn_es(lista)
    elif isinstance(obj, dict):
        r["n_items"] = len(obj)
    _campos_json(lista[:20] if lista else obj, r["campos"])
    return r


def resumen_xml(texto):
    """XML -> {parsea, n_items, campos}. n_items = hijos directos de la raíz; campos = etiquetas."""
    r = {"parsea": False, "n_items": None, "campos": []}
    if re.search(r"<!(DOCTYPE|ENTITY)", texto or "", re.I):
        return r  # no se parsean DTD/entidades
    try:
        raiz = ET.fromstring(texto)
    except Exception:
        return r
    r["parsea"] = True
    r["n_items"] = len(list(raiz))
    for el in raiz.iter():
        if len(r["campos"]) >= MAX_CAMPOS:
            break
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag:
            _añadir_campos(r["campos"], tag.rsplit("}", 1)[-1][:60])
    return r


def resumen_estructurado(tipo, texto):
    if tipo == "xml":
        return resumen_xml(texto)
    if tipo == "json":
        return resumen_json(texto)
    return {}


def rows_updated_utc(texto):
    """Metadatos Socrata -> rowsUpdatedAt (epoch s) como ISO UTC, o None."""
    try:
        v = json.loads(texto).get("rowsUpdatedAt")
        return datetime.fromtimestamp(int(v), timezone.utc).isoformat(timespec="seconds")
    except Exception:
        return None


def host_de(url):
    """Host (minúsculas, con puerto si lo hay) de una URL; '' si no se puede."""
    try:
        return (urlparse(url or "").netloc or "").lower()
    except Exception:
        return ""


def es_host_bloqueado(reg):
    """True si el registro indica bloqueo del host (403/429 o estado bloqueado)."""
    return reg.get("http_status") in (403, 429) or reg.get("estado") == "bloqueado"


def registro_omitido(portal, url):
    """Registro para una URL saltada porque su host ya devolvió bloqueo en esta ejecución."""
    return {"portal": portal, "url": url, "robots_ok": None, "http_status": None,
            "url_final": None, "bytes": 0, "ms": 0, "senales": ["host_bloqueado_previo"],
            "estado": "omitido_host_bloqueado",
            "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}


class RedirectSeguro(urllib.request.HTTPRedirectHandler):
    """Antes de seguir cada salto comprueba robots.txt del destino. Máx. MAX_REDIRECTS saltos.

    `robots` es inyectable (callable url -> True/False/None). Si no es True, no se sigue
    y `bloqueo` queda en 'redirect_prohibido_robots' o 'redirect_robots_no_leido'.
    """
    max_redirections = MAX_REDIRECTS
    max_repeats = MAX_REDIRECTS

    def __init__(self, robots=None):
        self.robots = robots
        self.bloqueo = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        destino = urljoin(req.full_url, newurl)
        if urlparse(destino).path != "/robots.txt":  # el propio robots.txt no se re-comprueba
            ok = (self.robots or robots_permitido)(destino)
            if ok is not True:
                self.bloqueo = ("redirect_prohibido_robots" if ok is False
                                else "redirect_robots_no_leido")
                return None  # urllib lanza HTTPError con la 30x original
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_REDIRECT = RedirectSeguro(robots=lambda u: robots_permitido(u))  # sin cookies


def _abrir(req):
    """urlopen con redirecciones controladas por robots.txt (sin cookies)."""
    _REDIRECT.bloqueo = None
    urllib.request.install_opener(urllib.request.build_opener(_REDIRECT))
    return urllib.request.urlopen(req, timeout=TIMEOUT)


def robots_permitido(url):
    p = urlparse(url)
    rp = urllib.robotparser.RobotFileParser()
    robots_url = f"{p.scheme}://{p.netloc}/robots.txt"
    try:
        req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            rp.parse(r.read(MAX_LECTURA_ROBOTS).decode("utf-8", "replace").splitlines())
    except urllib.error.HTTPError as e:
        # robots.txt 4xx = sin restricciones publicadas; 5xx = no concluyente
        return True if e.code < 500 else None
    except Exception:
        return None  # no se pudo leer
    return rp.can_fetch(USER_AGENT, url)


def sondear(cfg):
    url = cfg["url"]
    reg = {"portal": cfg["portal"], "url": url, "robots_ok": None, "http_status": None,
           "url_final": None, "bytes": 0, "ms": 0, "senales": [], "estado": "error",
           "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    ok = robots_permitido(url)
    reg["robots_ok"] = ok
    if ok is False:
        reg["estado"] = "prohibido_robots"
        return reg
    if ok is None:
        reg["senales"].append("robots_no_leido")
        reg["estado"] = "error"
        return reg
    time.sleep(PAUSA_ROBOTS_S)
    t0 = time.monotonic()
    html = ""
    tipo = cfg.get("tipo", "html")
    tope = cfg.get("max_bytes") or MAX_LECTURA
    reg["tipo"] = tipo
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with _abrir(req) as r:
            reg["http_status"] = r.status
            reg["url_final"] = r.geturl()
            try:
                reg["content_type"] = r.headers.get("Content-Type")
            except Exception:
                pass
            body = r.read(tope + 1)
            if len(body) > tope:
                body = body[:tope]
                reg["truncado"] = True
            reg["bytes"] = len(body)
            html = body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # sin reintentos
        reg["http_status"] = e.code
        reg["url_final"] = e.geturl()
        try:
            body = e.read(tope)
            reg["bytes"] = len(body)
            html = body.decode("utf-8", "replace")
        except Exception:
            pass
    except Exception as e:
        reg["senales"].append(f"excepcion:{type(e).__name__}")
        reg["ms"] = int((time.monotonic() - t0) * 1000)
        return reg
    reg["ms"] = int((time.monotonic() - t0) * 1000)
    if _REDIRECT.bloqueo:
        reg["senales"] += ["redirect", _REDIRECT.bloqueo]
        reg["estado"] = ("prohibido_robots" if _REDIRECT.bloqueo == "redirect_prohibido_robots"
                         else "error")
        return reg
    if reg["url_final"] and reg["url_final"] != url:
        reg["senales"].append("redirect")
        if robots_permitido(reg["url_final"]) is False:
            reg["senales"].append("redirect_prohibido_robots")
            reg["estado"] = "prohibido_robots"
            return reg
    if tipo == "html":
        reg.update(resumen_html(html))
    else:
        est = resumen_estructurado(tipo, html)
        if est.get("n_items") is None and "n_items" in est:
            est.pop("n_items")
        reg.update(est)
        if tipo == "json" and "views/" in url:
            reg["rowsUpdatedAt_utc"] = rows_updated_utc(html)
    estado, senales = clasificar(reg["http_status"], reg["url_final"], html,
                                 cfg.get("esperadas"))
    reg["estado"] = estado
    reg["senales"] += senales
    return reg


def tabla_md(regs):
    filas = ["| Portal | Estado | HTTP | robots | bytes | ms | Señales | Título | n_oferta | tipo | campos |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in regs:
        campos = ", ".join(r.get("campos") or [])[:120].replace("|", "/")
        filas.append(f"| {r['portal']} | {r['estado']} | {r['http_status']} | {r['robots_ok']} "
                     f"| {r['bytes']} | {r['ms']} | {', '.join(r['senales'])} "
                     f"| {r.get('titulo', '')} | {r.get('n_oferta', '')} "
                     f"| {r.get('tipo', 'html')} | {campos} |")
    return "\n".join(filas) + "\n"


def condicion(cfg):
    """Descarga una página de condiciones (robots -> pausa -> GET) y devuelve su bloque de texto."""
    url, nombre = cfg["url"], cfg["nombre"]
    ok = robots_permitido(url)
    if ok is not True:
        motivo = "prohibido_robots" if ok is False else "robots_no_leido"
        return f"===== {nombre} {url} ({motivo}) =====\n"
    time.sleep(PAUSA_ROBOTS_S)
    status, html = None, ""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with _abrir(req) as r:
            status = r.status
            html = r.read(MAX_LECTURA_CONDICIONES).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            html = e.read(MAX_LECTURA_CONDICIONES).decode("utf-8", "replace")
        except Exception:
            pass
    except Exception as e:
        return f"===== {nombre} {url} (excepcion:{type(e).__name__}) =====\n"
    if _REDIRECT.bloqueo:
        return f"===== {nombre} {url} ({_REDIRECT.bloqueo}) =====\n"
    cab = f"===== {nombre} {url} ({status}) =====\n"
    if status is not None and status >= 400:
        return cab + f"[sin texto: HTTP {status}]\n"
    return cab + texto_plano(html) + "\n"


def main_condiciones():
    bloques = []
    bloqueados = set()
    for i, cfg in enumerate(CONDICIONES):
        if host_de(cfg["url"]) in bloqueados:
            b = f"===== {cfg['nombre']} {cfg['url']} (omitido_host_bloqueado) =====\n"
            print(b, flush=True)
            bloques.append(b)
            continue
        if i:
            time.sleep(PAUSA_S)
        try:
            b = condicion(cfg)
            if re.search(r"\((403|429)\) =====|sin texto: HTTP (403|429)", b):
                bloqueados.add(host_de(cfg["url"]))
        except Exception as e:
            b = f"===== {cfg['nombre']} {cfg['url']} (excepcion:{type(e).__name__}) =====\n"
        print(b, flush=True)
        bloques.append(b)
    with open("condiciones.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(bloques))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--grupo", choices=sorted(GRUPOS), default="fase2")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        if e.code not in (0, None):  # error de uso: visible como anotación en Actions
            print("::error::sonda_portales: argumentos inválidos (ver stderr)", file=sys.stderr)
        raise
    if args.grupo == "condiciones":
        main_condiciones()
        return 0
    regs = []
    bloqueados = set()
    for i, cfg in enumerate(GRUPOS[args.grupo]):
        if host_de(cfg["url"]) in bloqueados:
            regs.append(registro_omitido(cfg["portal"], cfg["url"]))
            continue
        if i:
            time.sleep(PAUSA_S)
        try:
            regs.append(sondear(cfg))
            if es_host_bloqueado(regs[-1]):
                bloqueados.add(host_de(cfg["url"]))
        except Exception as e:  # nunca romper el informe
            regs.append({"portal": cfg["portal"], "url": cfg["url"], "robots_ok": None,
                         "http_status": None, "url_final": None, "bytes": 0, "ms": 0,
                         "senales": [f"excepcion:{type(e).__name__}"], "estado": "error",
                         "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    with open("sonda.json", "w", encoding="utf-8") as f:
        json.dump(regs, f, ensure_ascii=False, indent=2)
    tabla = tabla_md(regs)
    print(tabla)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(f"## Sonda de portales ({args.grupo})\n\n" + tabla)
    return 0


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        pass
    sys.exit(0)
