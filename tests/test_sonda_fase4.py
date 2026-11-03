"""Tests de la ampliacion Fase 4 de scripts/sonda_portales.py (sin red)."""
import io
import json
import re
import urllib.error
from datetime import datetime, timezone

import pytest

from tests.test_sonda import sonda  # reutiliza el modulo cargado por ruta

SECRETO = "VALOR_SECRETO"


# ---------- texto_plano ----------
def test_texto_plano_quita_script_style_etiquetas():
    html = ("<html><head><title>T</title><style>p{color:red}</style></head><body>"
            "<script>var x='JS';</script><p>Hola <b>mundo</b></p><noscript>NS</noscript></body></html>")
    t = sonda.texto_plano(html)
    assert t == "Hola mundo"


def test_texto_plano_colapsa_espacios():
    assert sonda.texto_plano("<p>a \n\n  b\t\tc</p>\n<p> d </p>") == "a b c d"


def test_texto_plano_max_chars():
    assert sonda.texto_plano("<p>" + "x" * 100 + "</p>", max_chars=10) == "x" * 10


@pytest.mark.parametrize("vacio", ["", None])
def test_texto_plano_vacio(vacio):
    assert sonda.texto_plano(vacio) == ""


# ---------- resumen_json ----------
def _oferta(i=0, **extra):
    d = {"title": f"Dev {i}", "location": "Barcelona, Spain"}
    d.update(extra)
    return d


@pytest.mark.parametrize("obj,n", [
    ([_oferta(1), _oferta(2)], 2),                          # Lever: lista
    ({"jobs": [_oferta(1), _oferta(2), _oferta(3)]}, 3),    # Greenhouse / Ashby / Remotive
    ({"data": [_oferta(1)], "links": {"next": None}}, 1),   # Arbeitnow
])
def test_resumen_json_formatos(obj, n):
    r = sonda.resumen_json(json.dumps(obj))
    assert r["parsea"] is True
    assert r["n_items"] == n
    assert "title" in r["campos"]
    assert r["n_ubic_bcn_es"] == n


def test_resumen_json_ashby_con_otras_claves():
    obj = {"apiVersion": "1", "jobs": [_oferta(1), _oferta(2)]}
    r = sonda.resumen_json(json.dumps(obj))
    assert r["n_items"] == 2


def test_resumen_json_dict_sin_lista():
    r = sonda.resumen_json(json.dumps({"a": 1, "b": 2}))
    assert r["parsea"] is True
    assert r["n_items"] == 2
    assert r["n_ubic_bcn_es"] is None


@pytest.mark.parametrize("malo", ['{"jobs": [{"title": "x"', "no es json", "", "[1, 2,"])
def test_resumen_json_invalido_no_lanza(malo):
    r = sonda.resumen_json(malo)
    assert r["parsea"] is False
    assert r["n_items"] is None
    assert r["campos"] == []


def test_resumen_json_none_no_lanza():
    assert sonda.resumen_json(None)["parsea"] is False


def test_resumen_json_campos_solo_nombres_no_valores():
    items = [{"title": SECRETO, "email": SECRETO, "location": SECRETO,
              "anidado": {"clave_interna": SECRETO}}]
    r = sonda.resumen_json(json.dumps({"jobs": items}))
    assert r["campos"]
    for c in r["campos"]:
        assert SECRETO not in c
    assert "clave_interna" in r["campos"]
    assert SECRETO not in json.dumps(r)


def test_resumen_json_tope_30_campos():
    item = {f"campo{i}": i for i in range(100)}
    r = sonda.resumen_json(json.dumps([item]))
    assert len(r["campos"]) == sonda.MAX_CAMPOS == 30
    assert len(set(r["campos"])) == 30


# ---------- resumen_xml ----------
def test_resumen_xml_valido():
    xml = ("<?xml version='1.0'?><offers><offer><title>A</title><city>BCN</city></offer>"
           "<offer><title>B</title></offer></offers>")
    r = sonda.resumen_xml(xml)
    assert r["parsea"] is True
    assert r["n_items"] == 2
    assert r["campos"][:2] == ["offers", "offer"]
    assert "title" in r["campos"] and "city" in r["campos"]
    assert "A" not in r["campos"]


def test_resumen_xml_namespace_se_recorta():
    r = sonda.resumen_xml('<r xmlns:x="urn:x"><x:job/></r>')
    assert "job" in r["campos"]


def test_resumen_xml_billion_laughs_rechazado():
    bomba = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
             '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
             '<lolz>&lol2;</lolz>')
    r = sonda.resumen_xml(bomba)
    assert r == {"parsea": False, "n_items": None, "campos": []}


def test_resumen_xml_solo_entity_rechazado():
    assert sonda.resumen_xml('<!entity x "y"><a/>')["parsea"] is False


@pytest.mark.parametrize("roto", ["<a><b></a>", "", "texto", None])
def test_resumen_xml_roto(roto):
    r = sonda.resumen_xml(roto)
    assert r["parsea"] is False and r["n_items"] is None


def test_resumen_estructurado_despacha():
    assert sonda.resumen_estructurado("xml", "<a><b/></a>")["n_items"] == 1
    assert sonda.resumen_estructurado("json", "[1]")["parsea"] is True
    assert sonda.resumen_estructurado("html", "<a/>") == {}


# ---------- rows_updated_utc ----------
def test_rows_updated_utc_epoch():
    out = sonda.rows_updated_utc(json.dumps({"rowsUpdatedAt": 1700000000}))
    assert out == "2023-11-14T22:13:20+00:00"
    assert datetime.fromisoformat(out).utcoffset().total_seconds() == 0


def test_rows_updated_utc_epoch_como_cadena():
    assert sonda.rows_updated_utc('{"rowsUpdatedAt": "0"}') == "1970-01-01T00:00:00+00:00"


@pytest.mark.parametrize("texto", ['{"otro": 1}', "no json", "[1]", "", None, '{"rowsUpdatedAt": null}'])
def test_rows_updated_utc_ausente(texto):
    assert sonda.rows_updated_utc(texto) is None


# ---------- contar_ubicacion_bcn_es ----------
def test_contar_ubicacion():
    items = [
        {"location": "Barcelona"},
        {"location": {"city": "Madrid", "country": "Spain"}},
        {"office": "España"},
        {"location": "Paris, France"},
        {"title": "Barcelona Manager", "location": "Berlin"},  # fuera de claves de ubicacion
        {"city": "ESPAÑA"},
        {"location": "Espana"},
    ]
    assert sonda.contar_ubicacion_bcn_es(items) == 5


@pytest.mark.parametrize("v", [None, []])
def test_contar_ubicacion_vacio(v):
    assert sonda.contar_ubicacion_bcn_es(v) == 0


# ---------- configuracion / argumentos ----------
def test_fase2_intacta():
    assert [p["portal"] for p in sonda.PORTALES] == [
        "Jooble", "InfoJobs", "Tecnoempleo", "LinkedIn", "Glassdoor"]
    assert sonda.GRUPOS["fase2"] is sonda.PORTALES


def test_grupos_definidos():
    assert set(sonda.GRUPOS) == {"fase2", "fase4", "condiciones"}


def test_urls_https_y_sin_secretos():
    urls = [p["url"] for p in sonda.PORTALES_FASE4] + [c["url"] for c in sonda.CONDICIONES]
    assert urls
    for u in urls:
        assert u.startswith("https://"), u
        bajo = u.lower()
        for malo in ("key=", "token", "api_key", "apikey", "secret", "password", "@"):
            assert malo not in bajo, (u, malo)


def test_portales_fase4_campos_validos():
    for p in sonda.PORTALES_FASE4:
        assert p["tipo"] in ("html", "xml", "json")
        assert p["max_bytes"] == sonda.MAX_LECTURA
        assert p["esperadas"]


def _main_aislado(monkeypatch, tmp_path, argv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    llamados = []
    monkeypatch.setattr(sonda.time, "sleep", lambda s: None)
    monkeypatch.setattr(sonda, "sondear", lambda cfg: (llamados.append(cfg["portal"]) or
                        {"portal": cfg["portal"], "url": cfg["url"], "robots_ok": True,
                         "http_status": 200, "url_final": cfg["url"], "bytes": 1, "ms": 1,
                         "senales": [], "estado": "ok"}))
    rc = sonda.main(argv)
    return rc, llamados


def test_main_por_defecto_es_fase2(monkeypatch, tmp_path):
    rc, llamados = _main_aislado(monkeypatch, tmp_path, [])
    assert rc == 0
    assert llamados == [p["portal"] for p in sonda.PORTALES]
    datos = json.loads((tmp_path / "sonda.json").read_text(encoding="utf-8"))
    assert len(datos) == 5


def test_main_fase4(monkeypatch, tmp_path):
    rc, llamados = _main_aislado(monkeypatch, tmp_path, ["--grupo", "fase4"])
    assert rc == 0
    assert len(llamados) == len(sonda.PORTALES_FASE4)


def test_main_grupo_desconocido_sale_con_error_argparse(monkeypatch, tmp_path):
    # Documentado: argparse (choices) aborta con SystemExit(2) desde main();
    # el bloque __main__ lo captura y termina con 0.
    with pytest.raises(SystemExit) as e:
        _main_aislado(monkeypatch, tmp_path, ["--grupo", "nada"])
    assert e.value.code == 2


def test_main_condiciones_escribe_fichero(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sonda.time, "sleep", lambda s: None)
    monkeypatch.setattr(sonda, "condicion", lambda cfg: f"===== {cfg['nombre']} =====\n")
    assert sonda.main(["--grupo", "condiciones"]) == 0
    txt = (tmp_path / "condiciones.txt").read_text(encoding="utf-8")
    for c in sonda.CONDICIONES:
        assert c["nombre"] in txt


# ---------- sondear / condicion con red falsa ----------
class _Resp:
    def __init__(self, body, status=200, url=None, ctype="application/json"):
        self._b, self.status, self._url, self.headers = body, status, url, {"Content-Type": ctype}

    def read(self, n=-1):
        return self._b if n is None or n < 0 else self._b[:n]

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _red(monkeypatch, respuesta, robots=True):
    monkeypatch.setattr(sonda, "robots_permitido", lambda u: robots)
    monkeypatch.setattr(sonda.time, "sleep", lambda s: None)

    def fake(req, timeout=None):
        if isinstance(respuesta, Exception):
            raise respuesta
        return respuesta
    monkeypatch.setattr(sonda.urllib.request, "urlopen", fake)


def test_sondear_json_200(monkeypatch):
    url = "https://x.test/api/jobs"
    cuerpo = json.dumps({"jobs": [_oferta(1), _oferta(2)]}).encode()
    _red(monkeypatch, _Resp(cuerpo, url=url))
    reg = sonda.sondear({"portal": "X", "url": url, "tipo": "json", "max_bytes": 1000,
                         "esperadas": ["jobs"]})
    assert reg["estado"] == "ok" or reg["estado"] not in ("error", "bloqueado")
    assert reg["http_status"] == 200
    assert reg["parsea"] is True and reg["n_items"] == 2
    assert reg["n_ubic_bcn_es"] == 2
    assert reg["tipo"] == "json"
    assert "truncado" not in reg
    assert reg["fecha_utc"].endswith("+00:00")


def test_sondear_cuerpo_mayor_que_max_bytes_trunca(monkeypatch):
    url = "https://x.test/api/jobs"
    _red(monkeypatch, _Resp(b"x" * 500, url=url))
    reg = sonda.sondear({"portal": "X", "url": url, "tipo": "json", "max_bytes": 100})
    assert reg["truncado"] is True
    assert reg["bytes"] == 100
    assert reg["parsea"] is False


def test_sondear_403(monkeypatch):
    url = "https://x.test/p"
    err = urllib.error.HTTPError(url, 403, "Forbidden", {}, io.BytesIO(b"denied"))
    _red(monkeypatch, err)
    reg = sonda.sondear({"portal": "X", "url": url})
    assert reg["http_status"] == 403
    assert reg["estado"] == "bloqueado"
    assert "http_403" in reg["senales"]


def test_sondear_robots_prohibido_no_hace_peticion(monkeypatch):
    _red(monkeypatch, AssertionError("no debe llamarse"), robots=False)
    reg = sonda.sondear({"portal": "X", "url": "https://x.test/p"})
    assert reg["estado"] == "prohibido_robots" and reg["robots_ok"] is False
    assert reg["http_status"] is None


def test_sondear_robots_no_leido(monkeypatch):
    _red(monkeypatch, AssertionError("no debe llamarse"), robots=None)
    reg = sonda.sondear({"portal": "X", "url": "https://x.test/p"})
    assert "robots_no_leido" in reg["senales"] and reg["estado"] == "error"


def test_sondear_excepcion_de_red(monkeypatch):
    _red(monkeypatch, TimeoutError("t"))
    reg = sonda.sondear({"portal": "X", "url": "https://x.test/p"})
    assert reg["estado"] == "error"
    assert "excepcion:TimeoutError" in reg["senales"]


def test_sondear_xml_con_doctype_no_parsea(monkeypatch):
    url = "https://x.test/o.xml"
    _red(monkeypatch, _Resp(b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>', url=url))
    reg = sonda.sondear({"portal": "X", "url": url, "tipo": "xml", "max_bytes": 1000})
    assert reg["parsea"] is False
    assert "n_items" not in reg  # n_items None se elimina


def test_sondear_metadatos_socrata_rows_updated(monkeypatch):
    url = "https://x.test/api/views/abc.json"
    _red(monkeypatch, _Resp(b'{"rowsUpdatedAt": 1700000000, "name": "n"}', url=url))
    reg = sonda.sondear({"portal": "X", "url": url, "tipo": "json", "max_bytes": 1000})
    assert reg["rowsUpdatedAt_utc"] == "2023-11-14T22:13:20+00:00"


def test_sondear_redirect_a_host_prohibido(monkeypatch):
    url, final = "https://x.test/a", "https://y.test/b"
    monkeypatch.setattr(sonda, "robots_permitido", lambda u: u != final)
    monkeypatch.setattr(sonda.time, "sleep", lambda s: None)
    monkeypatch.setattr(sonda.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(b"<html>oferta</html>", url=final, ctype="text/html"))
    reg = sonda.sondear({"portal": "X", "url": url})
    assert reg["estado"] == "prohibido_robots"
    assert "redirect" in reg["senales"] and "redirect_prohibido_robots" in reg["senales"]


def test_condicion_ok_devuelve_texto_plano(monkeypatch):
    url = "https://x.test/legal"
    html = b"<html><script>x</script><p>Condiciones   de uso</p></html>"
    _red(monkeypatch, _Resp(html, url=url, ctype="text/html"))
    out = sonda.condicion({"nombre": "N", "url": url})
    assert out.startswith(f"===== N {url} (200) =====")
    assert "Condiciones de uso" in out and "script" not in out


def test_condicion_403_sin_texto(monkeypatch):
    url = "https://x.test/legal"
    _red(monkeypatch, urllib.error.HTTPError(url, 403, "F", {}, io.BytesIO(b"x")))
    out = sonda.condicion({"nombre": "N", "url": url})
    assert "(403)" in out and "[sin texto: HTTP 403]" in out


def test_condicion_robots_prohibido(monkeypatch):
    _red(monkeypatch, AssertionError("no"), robots=False)
    assert "(prohibido_robots)" in sonda.condicion({"nombre": "N", "url": "https://x.test/l"})


def test_condicion_respeta_max_texto(monkeypatch):
    url = "https://x.test/legal"
    _red(monkeypatch, _Resp(b"<p>" + b"a" * 40000 + b"</p>", url=url, ctype="text/html"))
    out = sonda.condicion({"nombre": "N", "url": url})
    assert out.split("\n", 1)[1].count("a") == sonda.MAX_TEXTO_CONDICIONES


def test_robots_permitido_5xx_es_none_y_4xx_es_true(monkeypatch):
    def lanza(code):
        def f(req, timeout=None):
            raise urllib.error.HTTPError("https://x.test/robots.txt", code, "e", {}, io.BytesIO(b""))
        return f
    monkeypatch.setattr(sonda.urllib.request, "urlopen", lanza(404))
    assert sonda.robots_permitido("https://x.test/a") is True
    monkeypatch.setattr(sonda.urllib.request, "urlopen", lanza(503))
    assert sonda.robots_permitido("https://x.test/a") is None


# ---------- tabla_md ----------
def _reg(**kw):
    base = {"portal": "P", "estado": "ok", "http_status": 200, "robots_ok": True, "bytes": 5,
            "ms": 7, "senales": []}
    base.update(kw)
    return base


def test_tabla_md_con_y_sin_tipo_campos():
    t = sonda.tabla_md([
        _reg(portal="Viejo", titulo="T", n_oferta=3),
        _reg(portal="Nuevo", tipo="json", campos=["title", "a|b"], senales=["redirect", "x"]),
    ])
    filas = t.strip().split("\n")
    assert len(filas) == 4
    assert filas[0].endswith("| tipo | campos |")
    assert filas[2].endswith("| html |  |")          # sin tipo -> html, sin campos -> vacio
    assert filas[3].endswith("| json | title, a/b |")  # '|' escapado
    assert "redirect, x" in filas[3]
    # mismo numero de celdas en todas las filas
    assert len({f.count("|") for f in filas}) == 1


def test_tabla_md_campos_none_y_recorte():
    t = sonda.tabla_md([_reg(campos=None), _reg(campos=["c" * 60] * 5)])
    filas = t.strip().split("\n")
    assert filas[2].endswith("|  |")
    assert len(re.split(r"\| ", filas[3])[-1]) <= 125
