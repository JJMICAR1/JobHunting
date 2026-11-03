"""Fase 5: sincronización de issues con una API de GitHub falsa en memoria."""
import pytest

from jobhunting import alertas
from jobhunting.salud import Alerta

A1 = Alerta("tecnoempleo", "cero", "msg uno")
A2 = Alerta("feinaactiva", "error", "msg dos")


class FakeGH:
    def __init__(self, label_status=201, fallo=None):
        self.issues, self.etiquetas, self.log, self.sig = [], [], [], 1
        self.label_status, self.fallo = label_status, fallo

    def poner(self, titulo, labels=("alerta",), pr=False, state="open"):
        i = {"number": self.sig, "title": titulo, "state": state,
             "labels": [{"name": n} for n in labels]}
        if pr:
            i["pull_request"] = {}
        self.sig += 1
        self.issues.append(i)
        return i

    def __call__(self, metodo, ruta, datos=None):
        self.log.append((metodo, ruta, datos))
        if self.fallo and self.fallo(metodo, ruta):
            return 500, None
        if metodo == "GET":
            assert ruta.startswith("/issues?")
            q = dict(p.split("=") for p in ruta.split("?")[1].split("&"))
            pg, n = int(q["page"]), int(q["per_page"])
            sel = [i for i in self.issues if i["state"] == "open"
                   and q["labels"] in [l["name"] for l in i["labels"]]]
            return 200, sel[(pg - 1) * n: pg * n]
        if (metodo, ruta) == ("POST", "/labels"):
            self.etiquetas.append(datos["name"])
            return self.label_status, {}
        if (metodo, ruta) == ("POST", "/issues"):
            i = self.poner(datos["title"], datos["labels"])
            i["body"] = datos["body"]
            return 201, i
        if metodo == "POST" and ruta.endswith("/comments"):
            return 201, {}
        if metodo == "PATCH":
            num = int(ruta.rsplit("/", 1)[1])
            for i in self.issues:
                if i["number"] == num:
                    i["state"] = datos["state"]
            return 200, {}
        raise AssertionError((metodo, ruta))

    def abiertos(self):
        return [i for i in self.issues if i["state"] == "open"]

    def escrituras(self):
        return [x for x in self.log if x[0] != "GET"]


def test_crea_issues_con_etiquetas():
    gh = FakeGH()
    c = alertas.sincronizar([A1, A2], "prod", http=gh)
    assert c == {"abiertos": 2, "cerrados": 0, "sin_cambios": 0}
    assert {i["title"] for i in gh.issues} == {"[alerta][prod] tecnoempleo: cero",
                                               "[alerta][prod] feinaactiva: error"}
    assert all(["alerta", "entorno:prod"] == [l["name"] for l in i["labels"]] for i in gh.issues)
    assert set(gh.etiquetas) == {"alerta", "entorno:prod"}
    assert "tecnoempleo" in gh.issues[0]["body"] and "msg uno" in gh.issues[0]["body"]


def test_idempotente():
    gh = FakeGH()
    alertas.sincronizar([A1, A2], "prod", http=gh)
    n = len(gh.escrituras())
    c = alertas.sincronizar([A1, A2], "prod", http=gh)
    assert c == {"abiertos": 0, "cerrados": 0, "sin_cambios": 2}
    assert len(gh.escrituras()) == n and len(gh.abiertos()) == 2


def test_sin_alertas_ni_issues_no_escribe():
    gh = FakeGH()
    assert alertas.sincronizar([], "prod", http=gh) == {"abiertos": 0, "cerrados": 0, "sin_cambios": 0}
    assert gh.escrituras() == []


def test_cierra_las_resueltas_con_comentario():
    gh = FakeGH()
    alertas.sincronizar([A1, A2], "prod", http=gh)
    c = alertas.sincronizar([A1], "prod", http=gh)
    assert c == {"abiertos": 0, "cerrados": 1, "sin_cambios": 1}
    assert [i["title"] for i in gh.abiertos()] == ["[alerta][prod] tecnoempleo: cero"]
    cierre = [x for x in gh.log if x[0] == "PATCH"]
    assert cierre[0][2]["state"] == "closed"
    assert any(m == "POST" and r.endswith("/comments") for m, r, _ in gh.log)
    # una tercera vez no vuelve a tocar nada
    n = len(gh.escrituras())
    alertas.sincronizar([A1], "prod", http=gh)
    assert len(gh.escrituras()) == n


def test_no_toca_otro_entorno_pr_ni_sin_prefijo():
    gh = FakeGH()
    dev = gh.poner("[alerta][dev] tecnoempleo: cero", ("alerta", "entorno:dev"))
    pr = gh.poner("[alerta][prod] feinaactiva: error", pr=True)
    ajeno = gh.poner("Bug manual del CEO")
    otro = gh.poner("[alerta][prod]sin espacio: x")
    alertas.sincronizar([], "prod", http=gh)
    assert all(i["state"] == "open" for i in (dev, pr, ajeno, otro))
    assert gh.escrituras() == []


def test_issue_de_otro_entorno_no_cuenta_como_existente():
    gh = FakeGH()
    gh.poner("[alerta][dev] tecnoempleo: cero", ("alerta", "entorno:dev"))
    c = alertas.sincronizar([A1], "prod", http=gh)
    assert c["abiertos"] == 1 and len(gh.issues) == 2


def test_issue_sin_etiqueta_alerta_no_se_lista():
    gh = FakeGH()
    gh.poner("[alerta][prod] tecnoempleo: cero", ("otra",))
    assert alertas.abiertos(gh, "prod") == {}


def test_etiqueta_422_tolerada():
    gh = FakeGH(label_status=422)
    assert alertas.sincronizar([A1], "prod", http=gh)["abiertos"] == 1


def test_etiqueta_otro_error():
    gh = FakeGH(label_status=500)
    with pytest.raises(RuntimeError):
        alertas.sincronizar([A1], "prod", http=gh)
    assert gh.issues == []


def test_error_al_listar():
    with pytest.raises(RuntimeError):
        alertas.sincronizar([A1], "prod", http=FakeGH(fallo=lambda m, r: m == "GET"))


def test_error_al_crear_issue():
    with pytest.raises(RuntimeError):
        alertas.sincronizar([A1], "prod", http=FakeGH(fallo=lambda m, r: (m, r) == ("POST", "/issues")))


def test_error_al_comentar_y_al_cerrar():
    for f in (lambda m, r: m == "POST" and r.endswith("/comments"), lambda m, r: m == "PATCH"):
        gh = FakeGH()
        gh.poner("[alerta][prod] tecnoempleo: cero", ("alerta", "entorno:prod"))
        with pytest.raises(RuntimeError):
            alertas.sincronizar([], "prod", http=_con_fallo(gh, f))


def _con_fallo(gh, f):
    gh.fallo = f
    return gh


def test_paginacion_mas_de_100():
    gh = FakeGH()
    for i in range(250):
        gh.poner(f"[alerta][prod] p{i}: cero", ("alerta", "entorno:prod"))
    assert len(alertas.abiertos(gh, "prod")) == 250
    assert sum(1 for m, r, _ in gh.log if m == "GET") == 3
    c = alertas.sincronizar([], "prod", http=gh)
    assert c["cerrados"] == 250 and gh.abiertos() == []


def test_paginacion_exactamente_100():
    gh = FakeGH()
    for i in range(100):
        gh.poner(f"[alerta][prod] p{i}: cero", ("alerta", "entorno:prod"))
    assert len(alertas.abiertos(gh, "prod")) == 100


def test_http_github_sin_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "a/b")
    with pytest.raises(RuntimeError):
        alertas.http_github("GET", "/issues")


def test_http_github_sin_repo(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with pytest.raises(RuntimeError):
        alertas.http_github("GET", "/issues")


def test_cuerpo_no_contiene_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_SECRETO123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    gh = FakeGH()
    alertas.sincronizar([A1], "prod", http=gh)
    texto = repr(gh.log)
    assert "ghs_SECRETO123" not in texto
    assert "https://github.com/o/r/actions/runs/42" in gh.issues[0]["body"]


def test_cuerpo_sin_contexto_de_actions(monkeypatch):
    for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"):
        monkeypatch.delenv(k, raising=False)
    assert "Detectado por el workflow `salud`: -" in alertas.cuerpo(A1, "dev")
