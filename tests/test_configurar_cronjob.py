"""scripts/configurar_cronjob.py: idempotencia, cuerpo de las tareas y secretos (sin red, `llamar` falso)."""
import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("configurar_cronjob", RAIZ / "scripts" / "configurar_cronjob.py")
cj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cj)

CLAVE = "CRONKEY-abc123SECRETA"
GH = "github_pat_TOKENSECRETO789"
ET, PI = "jobhunting etiquetado prod", "jobhunting pipeline prod"


class Falso:
    """llamar falso: graba (metodo, ruta, datos); `jobs` es lo que devuelve el GET."""

    def __init__(self, jobs=(), get=200, fallos=None, excepciones=None):
        self.jobs, self.get, self.calls = list(jobs), get, []
        self.fallos = fallos or {}            # (metodo, ruta) -> status
        self.excepciones = excepciones or {}  # (metodo, ruta) -> Exception

    def __call__(self, metodo, ruta, clave, datos=None):
        assert clave == CLAVE
        self.calls.append((metodo, ruta, datos))
        if (metodo, ruta) in self.excepciones:
            raise self.excepciones[(metodo, ruta)]
        if metodo == "GET":
            return self.get, ({"jobs": self.jobs} if self.get == 200 else None)
        st = self.fallos.get((metodo, ruta), 200)
        return st, {"jobId": 999} if metodo == "PUT" else None

    def escrituras(self):
        return [(m, r) for m, r, _ in self.calls if m != "GET"]


# --- idempotencia ---

def test_sin_tareas_dos_put():
    f = Falso()
    assert cj.configurar(CLAVE, GH, f) == 0
    assert f.escrituras() == [("PUT", "/jobs"), ("PUT", "/jobs")]
    assert {d["job"]["title"] for m, _, d in f.calls if m == "PUT"} == {ET, PI}


def test_con_las_dos_existentes_dos_patch():
    f = Falso(jobs=[{"title": ET, "jobId": 11}, {"title": PI, "jobId": 22}, {"title": "otra ajena", "jobId": 33}])
    assert cj.configurar(CLAVE, GH, f) == 0
    assert sorted(f.escrituras()) == [("PATCH", "/jobs/11"), ("PATCH", "/jobs/22")]


def test_mezcla_una_existe_otra_no():
    f = Falso(jobs=[{"title": PI, "jobId": 22}])
    assert cj.configurar(CLAVE, GH, f) == 0
    assert sorted(f.escrituras()) == [("PATCH", "/jobs/22"), ("PUT", "/jobs")]
    f = Falso(jobs=[{"title": ET, "jobId": 11}])
    cj.configurar(CLAVE, GH, f)
    assert sorted(f.escrituras()) == [("PATCH", "/jobs/11"), ("PUT", "/jobs")]


def test_segunda_ejecucion_mismo_estado():
    """Simula cron-job.org: tras crear, el GET devuelve las tareas y se pasa a PATCH con el mismo cuerpo."""
    f1 = Falso()
    cj.configurar(CLAVE, GH, f1)
    cuerpos1 = {d["job"]["title"]: d for m, _, d in f1.calls if m == "PUT"}
    f2 = Falso(jobs=[{"title": t, "jobId": i} for i, t in enumerate(cuerpos1, 1)])
    cj.configurar(CLAVE, GH, f2)
    assert not [1 for m, _, _ in f2.calls if m == "PUT"]
    assert {d["job"]["title"]: d for m, _, d in f2.calls if m == "PATCH"} == cuerpos1


def test_get_sin_jobs_o_none():
    class F(Falso):
        def __call__(self, metodo, ruta, clave, datos=None):
            self.calls.append((metodo, ruta, datos))
            return (200, {"jobs": None}) if metodo == "GET" else (200, {"jobId": 1})
    f = F()
    assert cj.configurar(CLAVE, GH, f) == 0 and f.escrituras() == [("PUT", "/jobs")] * 2


# --- cuerpo de los jobs ---

def cuerpo(titulo):
    f = Falso()
    cj.configurar(CLAVE, GH, f)
    return next(d["job"] for m, _, d in f.calls if m == "PUT" and d["job"]["title"] == titulo)


@pytest.mark.parametrize("titulo,wf", [(ET, "etiquetado.yml"), (PI, "pipeline.yml")])
def test_url_metodo_zona_y_body(titulo, wf):
    j = cuerpo(titulo)
    assert j["url"] == f"https://api.github.com/repos/JJMICAR1/JobHunting/actions/workflows/{wf}/dispatches"
    assert j["requestMethod"] == 1 and j["enabled"] is True and j["saveResponses"] is False
    assert j["schedule"]["timezone"] == "Europe/Madrid" and j["schedule"]["expiresAt"] == 0
    assert json.loads(j["extendedData"]["body"]) == {"ref": "main", "inputs": {"entorno": "prod"}}
    h = j["extendedData"]["headers"]
    assert h["Authorization"] == f"Bearer {GH}" and h["Accept"] == "application/vnd.github+json"
    assert h["X-GitHub-Api-Version"] == "2022-11-28" and h["Content-Type"] == "application/json"
    for k in ("mdays", "months", "wdays"):
        assert j["schedule"][k] == [-1]


def test_horarios():
    s = cuerpo(ET)["schedule"]
    assert s["minutes"] == [37] and s["hours"] == [-1]
    s = cuerpo(PI)["schedule"]
    assert s["minutes"] == [17] and s["hours"] == [6]


def test_solo_dos_tareas_con_titulos_estables():
    assert set(cj.TAREAS) == {ET, PI}


# --- fallos ---

def test_get_401_sale_1_y_no_escribe(capsys):
    f = Falso(get=401)
    assert cj.configurar(CLAVE, GH, f) == 1
    assert f.escrituras() == [] and "401" in capsys.readouterr().out


def test_get_con_cuerpo_raro_sale_1():
    class F(Falso):
        def __call__(self, *a, **k):
            return 200, ["no es dict"]
    assert cj.configurar(CLAVE, GH, F()) == 1


def test_un_put_falla_sale_1_pero_intenta_el_otro(capsys):
    f = Falso()
    # fallar solo el primero: PUT /jobs es el mismo para ambos, asi que falla el 1o
    n = {"i": 0}
    orig = f.__call__

    def llamar(metodo, ruta, clave, datos=None):
        if metodo == "PUT":
            n["i"] += 1
            f.calls.append((metodo, ruta, datos))
            return (500, None) if n["i"] == 1 else (200, {"jobId": 5})
        return orig(metodo, ruta, clave, datos)
    assert cj.configurar(CLAVE, GH, llamar) == 1
    assert n["i"] == 2
    out = capsys.readouterr().out
    assert "500" in out and "creada (id 5)" in out


def test_un_patch_falla_sale_1_pero_intenta_el_otro():
    f = Falso(jobs=[{"title": ET, "jobId": 11}, {"title": PI, "jobId": 22}], fallos={("PATCH", "/jobs/11"): 404})
    assert cj.configurar(CLAVE, GH, f) == 1
    assert sorted(f.escrituras()) == [("PATCH", "/jobs/11"), ("PATCH", "/jobs/22")]


@pytest.mark.xfail(strict=True, reason="configurar_cronjob.py:configurar: un RuntimeError de red en el 1er PUT "
                   "propaga y no se intenta la 2a tarea (solo los status HTTP de error siguen adelante)")
def test_error_de_red_en_una_tarea_no_impide_la_otra():
    f = Falso(excepciones={("PUT", "/jobs"): RuntimeError("fallo de red")})
    try:
        cj.configurar(CLAVE, GH, f)
    except RuntimeError:
        pass
    assert len(f.escrituras()) == 2


def test_error_de_red_real_no_incluye_la_clave(monkeypatch):
    def urlopen(req, timeout=None):
        raise urllib.error.URLError(f"fallo con {req.full_url} Authorization: Bearer {CLAVE}")
    monkeypatch.setattr(cj.urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError) as e:
        cj.http("GET", "/jobs", CLAVE)
    assert CLAVE not in str(e.value) and "URLError" in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_http_error_devuelve_codigo(monkeypatch):
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, "x", {}, None)
    monkeypatch.setattr(cj.urllib.request, "urlopen", urlopen)
    assert cj.http("GET", "/jobs", CLAVE) == (403, None)


def test_http_envia_clave_en_cabecera_y_json(monkeypatch):
    vistos = {}

    class R:
        status = 200
        def read(self): return b'{"jobs": []}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def urlopen(req, timeout=None):
        vistos["req"], vistos["t"] = req, timeout
        return R()
    monkeypatch.setattr(cj.urllib.request, "urlopen", urlopen)
    assert cj.http("PUT", "/jobs", CLAVE, {"a": 1}) == (200, {"jobs": []})
    r = vistos["req"]
    assert r.get_method() == "PUT" and r.full_url == "https://api.cron-job.org/jobs"
    assert r.get_header("Authorization") == f"Bearer {CLAVE}" and json.loads(r.data) == {"a": 1}
    assert vistos["t"] == cj.TIMEOUT


# --- main / secretos ---

def test_main_sin_secretos(monkeypatch, capsys):
    for faltan in ({"CRONJOB_API_KEY": CLAVE}, {"GH_DISPATCH_TOKEN": GH}, {}, {"CRONJOB_API_KEY": "  ", "GH_DISPATCH_TOKEN": GH}):
        monkeypatch.delenv("CRONJOB_API_KEY", raising=False)
        monkeypatch.delenv("GH_DISPATCH_TOKEN", raising=False)
        for k, v in faltan.items():
            monkeypatch.setenv(k, v)
        assert cj.main() == 1
        out = capsys.readouterr().out
        assert "Faltan" in out and CLAVE not in out and GH not in out


def test_main_hace_strip(monkeypatch):
    monkeypatch.setenv("CRONJOB_API_KEY", CLAVE + "\n")
    monkeypatch.setenv("GH_DISPATCH_TOKEN", "  " + GH + "\n")
    f = Falso()
    monkeypatch.setattr(cj, "http", f)
    # configurar() usa `llamar=http` fijado al definirse: se llama explicitamente con el falso
    visto = {}
    orig = cj.configurar
    monkeypatch.setattr(cj, "configurar", lambda c, g, llamar=f: visto.update(c=c, g=g) or orig(c, g, llamar))
    assert cj.main() == 0
    assert visto == {"c": CLAVE, "g": GH}
    j = next(d["job"] for m, _, d in f.calls if m == "PUT")
    assert j["extendedData"]["headers"]["Authorization"] == f"Bearer {GH}"


def test_main_error_de_red_sale_1_sin_secretos(monkeypatch, capsys):
    monkeypatch.setenv("CRONJOB_API_KEY", CLAVE)
    monkeypatch.setenv("GH_DISPATCH_TOKEN", GH)

    def urlopen(req, timeout=None):
        raise urllib.error.URLError(f"{req.full_url} Bearer {CLAVE} {GH}")
    monkeypatch.setattr(cj.urllib.request, "urlopen", urlopen)
    assert cj.main() == 1
    o = capsys.readouterr()
    assert CLAVE not in o.out + o.err and GH not in o.out + o.err and "URLError" in o.out


@pytest.mark.parametrize("caso", ["ok", "crear", "patch", "get401", "put500", "patch500"])
def test_stdout_nunca_contiene_secretos(caso, capsys):
    jobs = [{"title": ET, "jobId": 11}, {"title": PI, "jobId": 22}]
    f = {"ok": Falso(), "crear": Falso(), "patch": Falso(jobs=jobs), "get401": Falso(get=401),
         "put500": Falso(fallos={("PUT", "/jobs"): 500}),
         "patch500": Falso(jobs=jobs, fallos={("PATCH", "/jobs/11"): 500, ("PATCH", "/jobs/22"): 401})}[caso]
    cj.configurar(CLAVE, GH, f)
    o = capsys.readouterr()
    assert CLAVE not in o.out + o.err and GH not in o.out + o.err and "Bearer" not in o.out + o.err


def test_stdout_con_respuesta_que_trae_los_secretos(capsys):
    """Aunque cron-job.org devolviera el cuerpo (con el token) en una respuesta, no se imprime."""
    class F(Falso):
        def __call__(self, metodo, ruta, clave, datos=None):
            if metodo == "GET":
                return 200, {"jobs": [{"title": ET, "jobId": 1, "extendedData": {"headers": {"Authorization": GH}}}]}
            return 200, {"jobId": 2, "eco": GH}
    cj.configurar(CLAVE, GH, F())
    assert GH not in capsys.readouterr().out
