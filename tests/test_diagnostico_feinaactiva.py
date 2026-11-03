"""Tests de scripts/diagnostico_feinaactiva.py (puro, sin red)."""
import importlib.util
import io
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))  # el script importa sonda_portales como modulo hermano
_spec = importlib.util.spec_from_file_location("diagnostico_feinaactiva",
                                               RAIZ / "scripts" / "diagnostico_feinaactiva.py")
diag = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diag)

SENTINELA = "persona@ejemplo.test"


# ---------- forma_valor ----------
@pytest.mark.parametrize("entrada,esperado", [
    ("Abc 123", "Aaa 999"),
    ("ab-12/XY", "aa-99/AA"),
    ("  a   b  ", "a a"),
    ("Ñandú 7", "Aaaaa 9"),
    ("", ""),
])
def test_forma_valor(entrada, esperado):
    assert diag.forma_valor(entrada) == esperado


def test_forma_valor_recorta_y_no_filtra_valor():
    f = diag.forma_valor("x" * 100)
    assert len(f) == diag.LARGO_FORMA
    assert diag.forma_valor("x" * 100, largo=5) == "aaaaa"
    assert SENTINELA not in diag.forma_valor(SENTINELA)
    assert diag.forma_valor(12345) == "99999"


# ---------- parece_personal ----------
@pytest.mark.parametrize("ruta", [
    "oferta/email", "oferta/Email", "oferta/telefon", "oferta/telefonContacte",
    "oferta/persona_contacte", "oferta/contacte", "oferta/dni", "oferta/NIF",
    "oferta/dadesContacte", "oferta/empresa/emailContacte", "oferta/dniTreballador",
    "oferta/phone", "@mail",
])
def test_parece_personal_positivos(ruta):
    assert diag.parece_personal(ruta) is True


@pytest.mark.parametrize("ruta", [
    "oferta/unificat", "oferta/titol", "oferta/municipi", "oferta/dataPublicacio",
    "oferta/sector", "@id", "oferta/descripcio", "oferta/dnia",
])
def test_parece_personal_negativos(ruta):
    assert diag.parece_personal(ruta) is False


# ---------- es_categorico_seguro ----------
def test_categorico_seguro_ok():
    assert diag.es_categorico_seguro(["Barcelona", "Girona"] * 5) is True


@pytest.mark.parametrize("valores", [
    [], ["a@b.c"], ["x", "http://a.b"], ["HTTPS://a.b"], ["cod 123456"], ["1234567"],
    ["a" * 31] * 5, ["Barcelona", "Girona", "Barcelona"],       # 31 chars; pocas repeticiones
    ["932 123 456"] * 10, ["uno dos tres cuatro"] * 10, ["1234 5678"] * 10,
    ["www.x.cat"] * 10, ["a@b"] * 10,
])
def test_categorico_inseguro(valores):
    assert diag.es_categorico_seguro(valores) is False


def test_categorico_limites():
    assert diag.es_categorico_seguro(["a" * 30] * 5) is True
    assert diag.es_categorico_seguro(["a" * 31] * 5) is False
    assert diag.es_categorico_seguro(["12345"] * 5) is True   # 5 digitos: permitido
    assert diag.es_categorico_seguro(["a b c"] * 5) is True   # 3 palabras: permitido
    assert diag.es_categorico_seguro(["a b c d"] * 5) is False
    assert diag.es_categorico_seguro(["x"] * 4) is False      # 4 < 5 x 1
    assert diag.es_categorico_seguro([str(i) for i in range(60)] * 5) is True
    assert diag.es_categorico_seguro([str(i) for i in range(61)] * 5) is False
    # 6 digitos en un valor y 1 en otro: el total por valor cuenta
    assert diag.es_categorico_seguro(["123456"] * 5) is True
    assert diag.es_categorico_seguro(["1234567"] * 5) is False


def test_categorico_n_no_vacias_explicito():
    v = {"Barcelona": 2, "Girona": 1}
    assert diag.es_categorico_seguro(v, n_no_vacias=3) is False
    assert diag.es_categorico_seguro(v, n_no_vacias=10) is True


def test_telefono_con_espacios_y_texto_largo_no_son_categoricos():
    assert diag.es_categorico_seguro(["932 123 456"] * 20) is False
    assert diag.es_categorico_seguro(["Carrer Major numero cinc"] * 20) is False


@pytest.mark.parametrize("campo", ["nom", "cognom", "adreca", "mobil", "web", "url", "responsable",
                                   "nomContacte", "urlOferta", "webEmpresa", "responsableRRHH"])
def test_prefijos_personales_nuevos(campo):
    assert diag.parece_personal(f"oferta/{campo}") is True


def test_sanea_linea_neutraliza_comandos_actions():
    s = diag.sanea_linea("::warning::x\nlinea")
    assert "::" not in s and s.startswith("| ")
    assert all(l.startswith("| ") for l in s.split("\n"))
    assert diag.sanea_linea("a\n::error::b").split("\n")[1] == "| : :error: :b"


# ---------- resumen_estructura ----------
XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<ofertes>
  <oferta id="1"><titol>Dev</titol><municipi>Barcelona</municipi><email>{SENTINELA}</email>
    <contacte><telefon>600123456</telefon></contacte><nota>{SENTINELA}</nota></oferta>
  <oferta id="2"><titol>Ops</titol><municipi>Girona</municipi><email>{SENTINELA}</email>
    <contacte><telefon>600123457</telefon></contacte><nota></nota></oferta>
  <oferta id="3"><titol>QA</titol><municipi>Barcelona</municipi><email/>
    <contacte><telefon>600123458</telefon></contacte></oferta>
  <oferta><titol>PM</titol><municipi/><email>{SENTINELA}</email></oferta>
</ofertes>""".encode()


def _resumen(xml=XML):
    errores = []
    res = diag.resumen_estructura(diag.eventos_desde_iterparse(io.BytesIO(xml), errores))
    assert errores == []
    return res


def _campo(res, ruta):
    return next(c for c in res["campos"] if c["ruta"] == ruta)


def test_estructura_detecta_oferta():
    res = _resumen()
    assert res["raiz"] == "ofertes"
    assert res["ruta_oferta"] == "ofertes/oferta"
    assert res["n_ofertas"] == 4
    assert res["rutas_truncadas"] is False


def test_estructura_pct_no_vacio_y_atributos():
    res = _resumen()
    assert _campo(res, "titol")["pct_no_vacio"] == 100.0
    assert _campo(res, "municipi")["pct_no_vacio"] == 75.0      # 1 de 4 vacia
    assert _campo(res, "email")["pct_no_vacio"] == 75.0         # <email/> vacio en 1 de 4
    assert _campo(res, "contacte/telefon")["pct_no_vacio"] == 75.0
    assert _campo(res, "nota")["pct_no_vacio"] == 25.0
    at = _campo(res, "@id")
    assert at["apariciones"] == 3 and at["no_vacias"] == 3
    assert at["pct_no_vacio"] == 75.0


def _xml_muchas(n=5):
    ofs = "".join(f"<oferta><municipi>{'Barcelona' if i % 2 else 'Girona'}</municipi>"
                  f"<tel>932 123 456</tel><txt>uno dos tres cuatro</txt></oferta>"
                  for i in range(n * 2))
    return f"<r>{ofs}</r>".encode()


def test_estructura_categorico_solo_con_repeticiones():
    res = _resumen(_xml_muchas())
    assert dict(_campo(res, "municipi")["categorico"]) == {"Barcelona": 5, "Girona": 5}
    assert _campo(res, "tel")["categorico"] is None
    assert _campo(res, "txt")["categorico"] is None
    salida = "\n".join(diag.formatear_estructura(res))
    assert "Barcelona=5" in salida
    assert "932" not in salida and "cuatro" not in salida


def test_estructura_pocas_repeticiones_no_se_imprimen():
    res = _resumen()
    assert _campo(res, "municipi")["categorico"] is None
    assert "Barcelona" not in "\n".join(diag.formatear_estructura(res))


def test_estructura_categorico_y_personal():
    res = _resumen()
    for r in ("email", "contacte/telefon", "contacte"):
        assert _campo(res, r)["personal"] is True
        assert _campo(res, r)["categorico"] is None
    assert _campo(res, "titol")["personal"] is False


def test_estructura_sin_oferta_repetida():
    res = _resumen(b"<a><b>x</b><c>y</c></a>")
    assert res["ruta_oferta"] is None and res["n_ofertas"] == 0 and res["campos"] == []
    assert "No se detecta" in "\n".join(diag.formatear_estructura(res))


def test_formatear_estructura_no_filtra_valores_personales():
    res = _resumen()
    salida = "\n".join(diag.formatear_estructura(res))
    assert SENTINELA not in salida
    assert "600123456" not in salida and "600123457" not in salida
    assert "ejemplo.test" not in salida
    assert "ofertes/oferta" in salida and "n_ofertas=4" in salida
    assert "email: 75.0% no vacio" in salida                    # listada como personal
    assert "Barcelona" not in salida and "Girona" not in salida  # 3 apariciones < 5 x 2 distintos


def test_campo_no_personal_con_arroba_no_sale_como_categorico():
    xml = f"<r><o><x>{SENTINELA}</x></o><o><x>{SENTINELA}</x></o></r>".encode()
    res = _resumen(xml)
    assert _campo(res, "x")["categorico"] is None
    assert SENTINELA not in "\n".join(diag.formatear_estructura(res))
    assert SENTINELA not in repr(_campo(res, "x")["formas"])


def test_atributo_personal_no_se_vuelca():
    xml = f'<r><o email="{SENTINELA}"/><o email="{SENTINELA}"/></r>'.encode()
    res = _resumen(xml)
    assert _campo(res, "@email")["personal"] is True
    assert SENTINELA not in "\n".join(diag.formatear_estructura(res))


def test_estructura_trunca_rutas():
    n = diag.MAX_RUTAS + 50
    xml = ("<r><o>" + "".join(f"<c{i}>v</c{i}>" for i in range(n)) + "</o><o/></r>").encode()
    res = _resumen(xml)
    assert res["rutas_truncadas"] is True and res["n_rutas"] == diag.MAX_RUTAS
    assert "TRUNCADO" in "\n".join(diag.formatear_estructura(res))


def test_estructura_ignora_namespaces():
    xml = b'<r xmlns="urn:x"><o><t>a</t></o><o><t>b</t></o></r>'
    res = _resumen(xml)
    assert res["ruta_oferta"] == "r/o" and _campo(res, "t")["pct_no_vacio"] == 100.0


# ---------- LectorSeguro ----------
class _Trozos:
    """Fuente que devuelve los trozos dados, uno por read()."""
    def __init__(self, *trozos):
        self.t = list(trozos)

    def read(self, n=-1):
        return self.t.pop(0) if self.t else b""


def _leer_todo(lector):
    out = b""
    while True:
        c = lector.read(10)
        if not c:
            return out
        out += c


@pytest.mark.parametrize("cuerpo", [
    b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>',
    b"<a/><!ENTITY e 'x'>",
    b"<!doctype a><a/>",
    b"<! DOCTYPE a><a/>",
])
def test_lector_rechaza_doctype_entity(cuerpo):
    with pytest.raises(diag.XmlRechazado):
        _leer_todo(diag.LectorSeguro(io.BytesIO(cuerpo)))


@pytest.mark.parametrize("corte", range(1, 9))
def test_lector_rechaza_doctype_partido_entre_trozos(corte):
    s = b"<a/><!DOCTYPE a>"
    i = s.index(b"<!DOCTYPE")
    p = i + corte  # corte dentro de '<!DOCTYPE'
    with pytest.raises(diag.XmlRechazado):
        _leer_todo(diag.LectorSeguro(_Trozos(s[:p], s[p:])))


def test_lector_doctype_partido_en_tres_trozos():
    with pytest.raises(diag.XmlRechazado):
        _leer_todo(diag.LectorSeguro(_Trozos(b"<a/><", b"!DOC", b"TYPE a>")))


def test_lector_doctype_rechazado_con_iterparse():
    errores = []
    lector = diag.LectorSeguro(io.BytesIO(b'<!DOCTYPE a [<!ENTITY e "x">]><a>&e;</a>'))
    assert list(diag.eventos_desde_iterparse(lector, errores)) == []
    assert errores and "XmlRechazado" in errores[0]


def test_lector_acepta_xml_normal_y_cuenta_bytes():
    cuerpo = b"<a><b>1</b></a>"
    lector = diag.LectorSeguro(io.BytesIO(cuerpo))
    assert _leer_todo(lector) == cuerpo and lector.total == len(cuerpo)


def test_lector_rechaza_utf16_y_tope():
    with pytest.raises(diag.XmlRechazado):
        diag.LectorSeguro(io.BytesIO("<a/>".encode("utf-16"))).read()
    with pytest.raises(diag.XmlRechazado):
        _leer_todo(diag.LectorSeguro(io.BytesIO(b"<a>" + b"x" * 100 + b"</a>"), tope=50))


# ---------- resumen_robots ----------
ROBOTS = """# comentario
User-agent: *
Disallow: /api/
Allow: /api/offers
Crawl-delay: 10

User-agent: OtroBot
Disallow: /

User-agent: JobHuntingSonda
Disallow: /privado
"""


def test_resumen_robots_estrella_y_nuestro_agente():
    out = diag.resumen_robots(ROBOTS, "/api/offers/offers-xml")
    assert "[*] Disallow: /api/   <-- aplica a la URL" in out
    assert "[*] Allow: /api/offers   <-- aplica a la URL" in out
    assert "[*] Crawl-delay: 10" in out
    assert any(l.startswith("[JobHuntingSonda] Disallow: /privado") for l in out)
    assert not any("OtroBot" in l for l in out)
    assert not any("Disallow: /   " in l for l in out)


def test_resumen_robots_no_marca_si_no_aplica():
    out = diag.resumen_robots(ROBOTS, "/publico")
    assert not any("<--" in l for l in out)


def test_resumen_robots_vacio_o_sin_reglas():
    for t in ("", None, "User-agent: OtroBot\nDisallow: /\n"):
        assert diag.resumen_robots(t) == ["(sin reglas para * ni para nuestro agente)"]


def test_resumen_robots_max_lineas():
    t = "User-agent: *\n" + "".join(f"Disallow: /p{i}\n" for i in range(100))
    assert len(diag.resumen_robots(t)) == 40
    assert len(diag.resumen_robots(t, max_lineas=5)) == 5


def test_resumen_robots_agrupa_varios_user_agent():
    t = "User-agent: *\nUser-agent: Otro\nDisallow: /x\n"
    assert diag.resumen_robots(t) == ["[*] Disallow: /x"]


# ---------- buscar_enlace_legal ----------
BASE = "https://feinaactiva.gencat.cat/"


@pytest.mark.parametrize("html,esperado", [
    ('<a href="/ca/avis-legal">Avís legal</a>', "https://feinaactiva.gencat.cat/ca/avis-legal"),
    ('<a href="/x">Aviso legal</a>', "https://feinaactiva.gencat.cat/x"),
    ('<a href="/cond">Condicions d\'ús</a>', "https://feinaactiva.gencat.cat/cond"),
    ('<a href="/cu">Condiciones de uso</a>', "https://feinaactiva.gencat.cat/cu"),
    ('<a href="/legal/privacidad">Privacidad</a>', "https://feinaactiva.gencat.cat/legal/privacidad"),
    ('<a href="https://www.gencat.cat/legal">Legal</a>', "https://www.gencat.cat/legal"),
    ('<a href="https://gencat.cat/legal">Legal</a>', "https://gencat.cat/legal"),
    ('<a href="../rel">  Avís\n  legal </a>', "https://feinaactiva.gencat.cat/rel"),
])
def test_buscar_enlace_legal_encuentra(html, esperado):
    assert diag.buscar_enlace_legal(html, BASE) == esperado


@pytest.mark.parametrize("html", [
    "", None, "<p>Avís legal sin enlace</p>", '<a href="/contacto">Contacto</a>',
    '<a href="javascript:void(0)">Avís legal</a>', '<a href="mailto:a@b.c">legal</a>',
    '<a>Avís legal</a>',
    '<a href="https://otro.test/l">Legal</a>', '<a href="https://gencat.cat.evil.test/l">Legal</a>',
    '<a href="https://evilgencat.cat/l">Legal</a>', '<a href="http://x.test/avis-legal">Avís legal</a>',
    '<a href="//otro.test/l">Legal</a>',
])
def test_buscar_enlace_legal_sin_resultado(html):
    assert diag.buscar_enlace_legal(html, BASE) is None


def test_buscar_enlace_legal_devuelve_el_primero():
    html = '<a href="/a">Inicio</a><a href="/uno">Avís legal</a><a href="/dos">Aviso legal</a>'
    assert diag.buscar_enlace_legal(html, BASE) == BASE + "uno"


# ---------- url_final sin query ----------
def test_url_final_sin_query_en_informe(monkeypatch):
    class Resp:
        status = 200
        headers = {}
        def geturl(self): return "https://feinaactiva.gencat.cat/feed.xml?token=SECRETO123&u=1"
        def read(self, n=-1): return b"<r><o/><o/></r>"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class Opener:
        def open(self, req, timeout=None): return Resp()

    monkeypatch.setattr(diag.urllib.request, "build_opener", lambda *a, **k: Opener())
    lineas = []
    diag.descargar_y_resumir("https://feinaactiva.gencat.cat/feed.xml?token=SECRETO123", lineas.append)
    texto = "\n".join(lineas)
    assert "url_final=https://feinaactiva.gencat.cat/feed.xml" in texto
    assert "SECRETO123" not in texto and "?" not in texto.split("url_final=")[1].split()[0]


# ---------- robots: 404/410 = sin restricciones; resto 4xx = no concluyente ----------
def _robots_con_status(monkeypatch, code):
    import io as _io
    import urllib.error
    sonda = diag.sonda_portales

    class Opener:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, _io.BytesIO(b""))

    monkeypatch.setattr(sonda, "_OPENER_FACTORY", lambda *a, **k: Opener())
    sonda.vaciar_cache_robots()
    return sonda.robots_permitido("https://feinaactiva.gencat.cat/feed.xml")


@pytest.mark.parametrize("code", [404, 410])
def test_robots_404_410_sin_restricciones(monkeypatch, code):
    assert _robots_con_status(monkeypatch, code) is True


@pytest.mark.parametrize("code", [401, 403, 429, 400, 451, 500, 503])
def test_robots_otros_errores_no_concluyentes(monkeypatch, code):
    assert _robots_con_status(monkeypatch, code) is None
