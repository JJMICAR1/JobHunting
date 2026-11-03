"""Fase 5: evaluación pura de salud (sin red ni BD) y main()."""
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from conftest import utc
from jobhunting import salud
from jobhunting.salud import Alerta, Ejecucion, evaluar, evaluar_portal, resumen

AHORA = utc(2026, 11, 3, 8)
P = "tecnoempleo"


def ej(horas=1, n=100, estado="ok", portal=P, **kw):
    return Ejecucion(portal, AHORA - timedelta(hours=horas), estado, n, **kw)


def hist(*ns, desde=24):
    return [ej(desde + 24 * i, n) for i, n in enumerate(ns)]


def tipos(r):
    return [a.tipo for a in r]


def test_sin_ejecuciones():
    r = evaluar_portal(P, [], AHORA)
    assert tipos(r) == ["sin_ejecucion"] and r[0].portal == P


def test_sin_ejecuciones_ignora_otros_portales():
    assert tipos(evaluar_portal(P, [ej(portal="feinaactiva")], AHORA)) == ["sin_ejecucion"]


def test_sin_ejecuciones_latido_desactivado():
    assert evaluar_portal(P, [], AHORA, max_horas=None) == []


def test_todo_bien():
    assert evaluar_portal(P, [ej(1, 100)] + hist(100, 100, 100), AHORA) == []


def test_sin_ejecucion_antigua():
    assert tipos(evaluar_portal(P, [ej(30)], AHORA)) == ["sin_ejecucion"]


def test_latido_limite_exacto():
    assert evaluar_portal(P, [ej(28)], AHORA) == []
    r = Ejecucion(P, AHORA - timedelta(hours=28, seconds=1), "ok", 10)
    assert tipos(evaluar_portal(P, [r], AHORA)) == ["sin_ejecucion"]


def test_max_horas_none_desactiva_latido():
    assert evaluar_portal(P, [ej(1000)], AHORA, max_horas=None) == []


def test_sin_ejecucion_tiene_prioridad():
    mal = ej(40, 0, estado="error", detalle="x", n_descartadas=99, total_anunciado=1000)
    assert tipos(evaluar_portal(P, [mal], AHORA)) == ["sin_ejecucion"]


def test_error_y_detalle():
    r = evaluar_portal(P, [ej(1, 0, "error", detalle="parser roto: x")], AHORA)
    assert tipos(r) == ["error"] and "parser roto: x" in r[0].mensaje


def test_error_sin_detalle():
    assert "sin detalle" in evaluar_portal(P, [ej(1, 0, "error")], AHORA)[0].mensaje


def test_bloqueado():
    r = evaluar_portal(P, [ej(1, 30, "bloqueado", detalle="http_429")], AHORA)
    assert tipos(r) == ["bloqueado"] and "http_429" in r[0].mensaje


def test_cero():
    assert tipos(evaluar_portal(P, [ej(1, 0)] + hist(100, 100, 100), AHORA)) == ["cero"]


def test_cero_no_dispara_caida():
    assert "caida" not in tipos(evaluar_portal(P, [ej(1, 0)] + hist(100, 100, 100), AHORA))


def test_caida_con_historial():
    r = evaluar_portal(P, [ej(1, 40)] + hist(100, 100, 100), AHORA)
    assert tipos(r) == ["caida"]


def test_caida_limite_exacto_50_pct_no_alerta():
    assert evaluar_portal(P, [ej(1, 50)] + hist(100, 100, 100), AHORA) == []
    assert tipos(evaluar_portal(P, [ej(1, 49)] + hist(100, 100, 100), AHORA)) == ["caida"]


def test_caida_historial_insuficiente():
    assert evaluar_portal(P, [ej(1, 10)] + hist(100, 100), AHORA) == []


def test_historial_ignora_no_ok_y_ceros():
    previas = hist(100, 100) + [ej(100, 0), ej(110, 100, "error"), ej(120, 100, "bloqueado")]
    assert evaluar_portal(P, [ej(1, 10)] + previas, AHORA) == []  # solo 2 válidas


def test_caida_usa_ventana_de_7():
    previas = hist(*([100] * 7 + [1] * 20))
    assert tipos(evaluar_portal(P, [ej(1, 40)] + previas, AHORA)) == ["caida"]


def test_caida_usa_mediana():
    previas = hist(1000, 100, 100)  # mediana 100; la media sería 400
    assert tipos(evaluar_portal(P, [ej(1, 40)] + previas, AHORA)) == ["caida"]


def test_descartes():
    r = evaluar_portal(P, [ej(1, 80, n_descartadas=20)], AHORA)
    assert tipos(r) == ["descartes"]


def test_descartes_limite_exacto():
    assert evaluar_portal(P, [ej(1, 90, n_descartadas=10)], AHORA) == []  # 10 % justo
    assert tipos(evaluar_portal(P, [ej(1, 89, n_descartadas=11)], AHORA)) == ["descartes"]


def test_descartes_sin_tarjetas_no_divide_por_cero():
    assert tipos(evaluar_portal(P, [ej(1, 0, n_descartadas=0)], AHORA)) == ["cero"]


def test_incompleto():
    r = evaluar_portal(P, [ej(1, 70, total_anunciado=100)], AHORA)
    assert tipos(r) == ["incompleto"]


def test_incompleto_limite_exacto():
    assert evaluar_portal(P, [ej(1, 80, total_anunciado=100)], AHORA) == []
    assert tipos(evaluar_portal(P, [ej(1, 79, total_anunciado=100)], AHORA)) == ["incompleto"]


def test_incompleto_sin_total_no_alerta():
    assert evaluar_portal(P, [ej(1, 5, total_anunciado=None)], AHORA) == []
    assert evaluar_portal(P, [ej(1, 5, total_anunciado=0)], AHORA) == []


def test_varias_alertas_a_la_vez():
    r = evaluar_portal(P, [ej(1, 40, n_descartadas=40, total_anunciado=200)] + hist(100, 100, 100), AHORA)
    assert tipos(r) == ["caida", "descartes", "incompleto"]


def test_orden_de_entrada_indiferente():
    base = [ej(1, 40)] + hist(100, 100, 100)
    esperado = evaluar_portal(P, base, AHORA)
    assert esperado and evaluar_portal(P, list(reversed(base)), AHORA) == esperado
    assert evaluar_portal(P, base[2:] + base[:2], AHORA) == esperado


def test_fecha_naive_ahora():
    with pytest.raises(ValueError):
        evaluar_portal(P, [ej()], datetime(2026, 11, 3, 8))


def test_fecha_naive_ejecucion():
    with pytest.raises(ValueError):
        evaluar_portal(P, [Ejecucion(P, datetime(2026, 11, 3), "ok", 5)], AHORA)


def test_fecha_no_utc():
    cet = timezone(timedelta(hours=1))
    with pytest.raises(ValueError):
        evaluar_portal(P, [ej()], AHORA.astimezone(cet))


def test_un_portal_no_afecta_al_otro():
    ejs = [ej(1, 0, "error", detalle="x"), ej(1, 100, portal="feinaactiva")]
    r = evaluar(ejs, AHORA, portales=(P, "feinaactiva"))
    assert [(a.portal, a.tipo) for a in r] == [(P, "error")]


def test_evaluar_portales_por_defecto_sin_datos():
    r = evaluar([], AHORA)
    assert [a.portal for a in r] == list(salud.PORTALES) and set(tipos(r)) == {"sin_ejecucion"}


def test_evaluar_max_horas_none():
    assert evaluar([], AHORA, max_horas=None) == []


def test_ejecucion_es_inmutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        ej().n_ofertas = 3


def test_alerta_clave():
    assert Alerta(P, "cero", "m").clave == f"{P}: cero"


def test_resumen():
    assert "todo bien" in resumen([], "prod") and "(prod)" in resumen([], "prod")
    t = resumen([Alerta(P, "cero", "msg")], "dev")
    assert "1 alerta(s)" in t and f"**{P}: cero**" in t and "msg" in t


# ---- main ----

def test_main_sin_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert salud.main(["--entorno", "dev", "--sin-issues"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_main_bd_inaccesible_no_filtra(monkeypatch, capsys):
    url = "postgresql://u:s3cr3t@localhost:1/x"
    monkeypatch.setenv("DATABASE_URL", url)
    assert salud.main(["--entorno", "dev", "--sin-issues"]) == 1
    o = capsys.readouterr()
    assert "s3cr3t" not in o.out + o.err


def test_main_entorno_obligatorio():
    with pytest.raises(SystemExit):
        salud.main([])


class GH:
    """API de issues falsa mínima."""
    def __init__(self, error=None):
        self.llamadas, self.error = [], error

    def __call__(self, metodo, ruta, datos=None):
        self.llamadas.append((metodo, ruta, datos))
        if self.error:
            return 500, None
        if metodo == "GET":
            return 200, []
        if ruta == "/labels":
            return 201, {}
        return 201, {"number": 1}


def sembrar(conn, portal, horas, n, estado="ok", **kw):
    from jobhunting import db
    db.migrar(conn)
    fin = AHORA - timedelta(hours=horas)
    db.registrar_ejecucion(conn, portal, fin - timedelta(minutes=2), fin, estado, n, **kw)


def test_main_sin_issues_con_bd(conn, db_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    sembrar(conn, "tecnoempleo", 1, 100)
    sembrar(conn, "feinaactiva", 1, 0, "error", detalle="boom")
    gh = GH()
    assert salud.main(["--entorno", "dev", "--sin-issues"], ahora=AHORA, github=gh) == 0
    out = capsys.readouterr().out
    assert "feinaactiva: error" in out and "tecnoempleo" not in out.split("alerta(s)")[1]
    assert gh.llamadas == []


def test_main_con_github_falso(conn, db_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", db_url)
    sembrar(conn, "tecnoempleo", 1, 100)
    sembrar(conn, "feinaactiva", 1, 0, "error", detalle="boom")
    gh = GH()
    assert salud.main(["--entorno", "dev"], ahora=AHORA, github=gh) == 0
    crea = [d for m, r, d in gh.llamadas if (m, r) == ("POST", "/issues")]
    assert [d["title"] for d in crea] == ["[alerta][dev] feinaactiva: error"]
    assert "1 abiertos" in capsys.readouterr().out


def test_main_error_http(conn, db_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", db_url)
    sembrar(conn, "tecnoempleo", 1, 100)
    assert salud.main(["--entorno", "dev"], ahora=AHORA, github=GH(error=True)) == 1
    assert "Error al sincronizar" in capsys.readouterr().err


def test_main_max_horas_cero_desactiva_latido(conn, db_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", db_url)
    sembrar(conn, "tecnoempleo", 500, 100)
    sembrar(conn, "feinaactiva", 500, 100)
    assert salud.main(["--entorno", "dev", "--max-horas", "0", "--sin-issues"], ahora=AHORA) == 0
    assert "todo bien" in capsys.readouterr().out
    assert salud.main(["--entorno", "prod", "--sin-issues"], ahora=AHORA) == 0
    assert "sin_ejecucion" in capsys.readouterr().out


def test_main_escribe_step_summary(conn, db_url, monkeypatch, tmp_path):
    f = tmp_path / "s.md"
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(f))
    sembrar(conn, "tecnoempleo", 1, 100)
    sembrar(conn, "feinaactiva", 1, 100)
    assert salud.main(["--entorno", "dev", "--sin-issues"], ahora=AHORA) == 0
    assert "todo bien" in f.read_text()


# ---- _limpiar y main de solo lectura ----

def test_limpiar_vacio():
    assert salud._limpiar(None) == "sin detalle" and salud._limpiar("") == "sin detalle"


def test_limpiar_quita_urls_html_y_backticks():
    t = salud._limpiar("fallo en https://x.com/a?token=abc y <script>`rm`</script>")
    assert "https://" not in t and "token" not in t
    assert not any(c in t for c in "<>`")


def test_limpiar_una_linea_y_limite():
    assert salud._limpiar("a\nb\r\n  c") == "a b c"
    t = salud._limpiar("x" * 500)
    assert t == "x" * 200 + "…"
    assert salud._limpiar("x" * 200) == "x" * 200


def test_alertas_error_y_bloqueado_usan_limpiar():
    for est, tipo in (("error", "error"), ("bloqueado", "bloqueado")):
        r = evaluar_portal(P, [ej(1, 0, est, detalle="ver http://a.b/c?k=1 <b>")], AHORA)
        assert tipos(r) == [tipo] and "http" not in r[0].mensaje and "<" not in r[0].mensaje


def test_main_no_migra(conn, db_url, monkeypatch):
    from jobhunting import db
    sembrar(conn, "tecnoempleo", 1, 100)
    monkeypatch.setenv("DATABASE_URL", db_url)

    def no(*a, **k):
        raise AssertionError("main no debe migrar")
    monkeypatch.setattr(db, "migrar", no)
    assert salud.main(["--entorno", "dev", "--sin-issues"], ahora=AHORA) == 0


def test_main_bd_sin_migrar_no_crea_tablas(conn, db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    assert salud.main(["--entorno", "dev", "--sin-issues"], ahora=AHORA) == 1  # no hay tabla
    n = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() "
                     "AND table_name IN ('ejecuciones','ofertas','schema_migraciones')").fetchone()[0]
    assert n == 0


def test_main_sin_columnas_003(conn, db_url, monkeypatch, capsys):
    sembrar(conn, "tecnoempleo", 1, 100)
    sembrar(conn, "feinaactiva", 1, 100)
    conn.execute("ALTER TABLE ejecuciones DROP COLUMN n_descartadas, DROP COLUMN total_anunciado")
    monkeypatch.setenv("DATABASE_URL", db_url)
    assert salud.main(["--entorno", "dev", "--sin-issues"], ahora=AHORA) == 0
    assert "todo bien" in capsys.readouterr().out
