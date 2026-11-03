"""Pipeline multi-portal sin BD: ejecutar_portal, ejecutar(portal=...) y CLI --portal."""
from pathlib import Path

import pytest

from jobhunting import pipeline
from jobhunting.descarga import Bloqueado
from jobhunting.modelo import ParserRoto
from jobhunting.portales.feinaactiva import scraper as sc_fa
from jobhunting.portales.feinaactiva.scraper import ResultadoRecorrido

XML = (Path(__file__).parent / "fixtures" / "feinaactiva" / "ofertas_muestra.xml").read_bytes()


def fetch_xml(url, *a, **k):
    assert url == sc_fa.URL_XML
    return XML


def test_feinaactiva_dry_run_con_fetch_falso(capsys):
    assert pipeline.ejecutar_portal("feinaactiva", dry_run=True, fetch=fetch_xml) == 0
    out = capsys.readouterr().out
    assert "## Feina Activa: ok" in out
    assert "n_ofertas: 5" in out and "n_descartadas: 2" in out and "n_duplicadas: 1" in out
    assert "total_anunciado: 8" in out
    assert "por_grupo: feinaactiva=6, sicas=2" in out
    assert "paginas: 1" in out
    assert "ejemplo.test" not in out


def test_feinaactiva_dry_run_no_toca_bd(monkeypatch):
    monkeypatch.setattr(pipeline.db, "conectar", lambda *a, **k: pytest.fail("no debe conectar"))
    assert pipeline.ejecutar_portal("feinaactiva", dry_run=True, fetch=fetch_xml,
                                    database_url="postgresql://x") == 0


def test_feinaactiva_scraper_una_sola_peticion():
    llamadas = []
    rec = sc_fa.recorrer(fetch=lambda u: llamadas.append(u) or XML)
    assert llamadas == [sc_fa.URL_XML] and rec.paginas == 1 and rec.motivo_parada == "fin"
    assert len(rec.ofertas) == 5 and rec.n_duplicadas == 1 and rec.n_descartadas == 2


def test_feinaactiva_bloqueado_codigo_2(capsys):
    def f(url):
        raise Bloqueado("http_429")
    assert pipeline.ejecutar_portal("feinaactiva", dry_run=True, fetch=f) == 2
    assert "bloqueado" in capsys.readouterr().out


def test_feinaactiva_parser_roto_codigo_1(capsys):
    assert pipeline.ejecutar_portal("feinaactiva", dry_run=True, fetch=lambda u: b"<html/>") == 1
    assert "parser roto" in capsys.readouterr().out


def test_feinaactiva_doctype_codigo_1():
    malo = b'<!DOCTYPE ofertes [<!ENTITY e "x">]><ofertes><g><ad/></g></ofertes>'
    assert pipeline.ejecutar_portal("feinaactiva", dry_run=True, fetch=lambda u: malo) == 1


def test_feinaactiva_error_inesperado_codigo_1():
    def f(url):
        raise RuntimeError("boom")
    assert pipeline.ejecutar_portal("feinaactiva", dry_run=True, fetch=f) == 1


def test_portal_desconocido(capsys):
    assert pipeline.ejecutar_portal("glassdoor", dry_run=True) == 1
    assert "desconocido" in capsys.readouterr().err


def test_sin_database_url_feinaactiva(capsys):
    assert pipeline.ejecutar_portal("feinaactiva", fetch=fetch_xml) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_ejecutar_por_defecto_sigue_siendo_tecnoempleo(monkeypatch):
    vistos = []
    monkeypatch.setattr(pipeline, "ejecutar_portal", lambda p, **kw: vistos.append(p) or 0)
    assert pipeline.ejecutar() == 0 and vistos == ["tecnoempleo"]


# ---- ejecutar(portal="todos")
def _vacio(**kw):
    kw.setdefault("motivo_parada", "fin")
    return ResultadoRecorrido(**kw)


def falso_recorrer(monkeypatch, tecno, fa, orden=None):
    """tecno / fa: 'ok' | 'bloqueado' | 'roto' | 'error'."""
    def hacer(nombre, modo):
        def rec(*a, **k):
            if orden is not None:
                orden.append(nombre)
            if modo == "ok":
                return _vacio()
            if modo == "bloqueado":
                return _vacio(bloqueado=True, motivo_parada="bloqueado", detalle="http_429")
            if modo == "roto":
                raise ParserRoto("x")
            raise RuntimeError("boom")
        return rec
    monkeypatch.setattr(pipeline, "recorrer", hacer("tecnoempleo", tecno))
    monkeypatch.setattr(sc_fa, "recorrer", hacer("feinaactiva", fa))


@pytest.mark.parametrize("tecno,fa,esperado", [
    ("ok", "ok", 0),
    ("error", "ok", 1),
    ("ok", "error", 1),
    ("roto", "ok", 1),
    ("bloqueado", "ok", 2),
    ("ok", "bloqueado", 2),
    ("bloqueado", "error", 1),      # 1 > 2
    ("error", "bloqueado", 1),
    ("bloqueado", "bloqueado", 2),
])
def test_todos_ejecuta_los_dos_y_gana_el_peor(monkeypatch, tecno, fa, esperado):
    orden = []
    falso_recorrer(monkeypatch, tecno, fa, orden)
    assert pipeline.ejecutar(portal="todos", dry_run=True, sleep=lambda s: None) == esperado
    assert orden == ["tecnoempleo", "feinaactiva"]   # los dos se ejecutan siempre


def test_todos_un_fallo_inesperado_no_corta(monkeypatch, capsys):
    llamados = []

    def ep(p, **kw):
        llamados.append(p)
        if p == "tecnoempleo":
            raise RuntimeError("fuera del control de ejecutar_portal")
        return 0
    monkeypatch.setattr(pipeline, "ejecutar_portal", ep)
    assert pipeline.ejecutar(portal="todos", dry_run=True) == 1
    assert llamados == ["tecnoempleo", "feinaactiva"]
    assert "fallo inesperado" in capsys.readouterr().err


def test_todos_ignora_fetch(monkeypatch):
    kws = []
    monkeypatch.setattr(pipeline, "ejecutar_portal", lambda p, **kw: kws.append(kw) or 0)
    pipeline.ejecutar(portal="todos", fetch=lambda u: 1, dry_run=True)
    assert all("fetch" not in kw for kw in kws) and len(kws) == 2


@pytest.mark.parametrize("lista,esperado", [([], 0), ([0, 0], 0), ([2, 0], 2), ([0, 1], 1), ([2, 1, 2], 1)])
def test_peor(lista, esperado):
    assert pipeline._peor(lista) == esperado


# ---- CLI
def llamadas_cli(monkeypatch, argv, env=None):
    vistos = []

    def ep(portal, **kw):
        vistos.append((portal, kw))
        return 0
    monkeypatch.setattr(pipeline, "ejecutar_portal", ep)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return pipeline.main(argv), vistos


def test_cli_por_defecto_todos(monkeypatch):
    rc, v = llamadas_cli(monkeypatch, ["--dry-run"])
    assert rc == 0 and [p for p, _ in v] == ["tecnoempleo", "feinaactiva"]
    assert all(kw["dry_run"] is True for _, kw in v)


@pytest.mark.parametrize("p", ["tecnoempleo", "feinaactiva"])
def test_cli_portal_unico(monkeypatch, p):
    rc, v = llamadas_cli(monkeypatch, ["--portal", p, "--dry-run"])
    assert rc == 0 and [x for x, _ in v] == [p]


def test_cli_portal_invalido(monkeypatch):
    with pytest.raises(SystemExit) as e:
        llamadas_cli(monkeypatch, ["--portal", "glassdoor"])
    assert e.value.code == 2


def test_cli_database_url_del_entorno(monkeypatch):
    _, v = llamadas_cli(monkeypatch, ["--portal", "feinaactiva"], env={"DATABASE_URL": "postgresql://u@h/d"})
    assert v[0][1]["database_url"] == "postgresql://u@h/d" and v[0][1]["dry_run"] is False


def test_cli_feinaactiva_dry_run_de_extremo_a_extremo(monkeypatch, capsys):
    monkeypatch.setattr(pipeline, "descargar_bytes", fetch_xml)
    assert pipeline.main(["--portal", "feinaactiva", "--dry-run"]) == 0
    assert "Feina Activa: ok" in capsys.readouterr().out


def test_cli_codigo_de_salida_propagado(monkeypatch):
    falso_recorrer(monkeypatch, "ok", "bloqueado")
    assert pipeline.main(["--portal", "feinaactiva", "--dry-run"]) == 2
