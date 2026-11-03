"""Recuento de mercado por Telegram: formato, envio y main (sin red; leer contra la vista si hay BD)."""
import os
from datetime import date, datetime, timezone

import pytest

from jobhunting import mercado
from jobhunting.mercado import Fila

HOY = date(2026, 11, 10)
TOKEN = "123456:TOKEN-FALSO-abcdef"
CHAT = "987654321"


def fila(portal="tecnoempleo", dia=HOY, **kw):
    base = dict(dia=dia, portal=portal, n_vistas=100, n_nuevas=5, n_desaparecidas=3, n_unicas=90,
                d_vistas_1d=4, d_vistas_7d=-10, d_unicas_1d=0, d_unicas_7d=7)
    base.update(kw)
    return Fila(**base)


# --- formatear ---
def test_formatear_basico_prod():
    t = mercado.formatear([fila()], "prod", HOY)
    assert t.startswith("Mercado 2026-11-10") and "[dev]" not in t
    assert "activas: 100 (Δ1d +4, Δ7d -10)" in t
    assert "nuevas: 5 · desaparecidas: 3" in t
    assert "únicos: 90 (Δ1d +0, Δ7d +7)" in t


def test_formatear_dev_prefijo():
    assert mercado.formatear([fila()], "dev", HOY).startswith("[dev] Mercado 2026-11-10")


def test_formatear_nulls_con_raya():
    t = mercado.formatear([fila(d_vistas_1d=None, d_vistas_7d=None, d_unicas_1d=None, d_unicas_7d=None,
                                n_desaparecidas=None)], "prod", HOY)
    assert "Δ1d —, Δ7d —" in t and "desaparecidas: —" in t and "None" not in t


def test_formatear_sin_datos_de_hoy():
    t = mercado.formatear([fila(dia=date(2026, 11, 8))], "prod", HOY)
    assert "sin datos de hoy, último: 2026-11-08" in t
    assert "Total hoy (0 portales): activas 0" in t


def test_formatear_total_solo_con_filas_de_hoy():
    t = mercado.formatear([fila("a"), fila("b", n_vistas=50, n_nuevas=1, n_unicas=10),
                           fila("c", dia=date(2026, 11, 1), n_vistas=999)], "prod", HOY)
    assert "Total hoy (2 portales): activas 150, nuevas 6, únicos 100" in t


def test_formatear_acepta_datetime_utc():
    t = mercado.formatear([fila()], "prod", datetime(2026, 11, 10, 5, 17, tzinfo=timezone.utc))
    assert t.startswith("Mercado 2026-11-10")


def test_cita_feina_solo_si_aparece():
    assert "Feina Activa" not in mercado.formatear([fila()], "prod", HOY)
    t = mercado.formatear([fila(), fila("feinaactiva")], "prod", HOY)
    assert "Fuente Feina Activa: Generalitat de Catalunya" in t


def test_lista_vacia():
    t = mercado.formatear([], "prod", HOY)
    assert t == "Mercado 2026-11-10\nsin datos"
    assert mercado.formatear([], "dev", HOY).startswith("[dev] ")


def test_longitud_bajo_limite_telegram():
    filas = [fila(f"portal-{i}" + "x" * 50) for i in range(200)]
    assert len(mercado.formatear(filas, "prod", HOY)) < 4096


# --- enviar ---
def http_ok(guardar=None):
    def http(url, datos):
        if guardar is not None:
            guardar.append((url, datos))
        return 200, {"ok": True}
    return http


def test_enviar_ok():
    llamadas = []
    mercado.enviar("hola", TOKEN, CHAT, http=http_ok(llamadas))
    (url, datos), = llamadas
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert datos["chat_id"] == CHAT and datos["text"] == "hola"
    assert "parse_mode" not in datos


@pytest.mark.parametrize("respuesta", [(500, {"ok": True}), (403, None), (200, {"ok": False}),
                                       (200, None), (200, [])])
def test_enviar_error_de_respuesta(respuesta):
    with pytest.raises(RuntimeError) as e:
        mercado.enviar("x", TOKEN, CHAT, http=lambda u, d: respuesta)
    assert TOKEN not in str(e.value)


def test_enviar_excepcion_de_red_no_filtra_token():
    def http(url, datos):
        raise OSError(f"<urlopen error timed out> {url}")
    with pytest.raises(RuntimeError) as e:
        mercado.enviar("x", TOKEN, CHAT, http=http)
    assert TOKEN not in str(e.value) and "api.telegram.org" not in str(e.value)
    assert TOKEN not in repr(e.value) and e.value.__cause__ is None and e.value.__suppress_context__


# --- main ---
@pytest.fixture
def entorno(monkeypatch):
    for k in ("DATABASE_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("jobhunting.mercado.leer", lambda conn: [fila()])
    monkeypatch.setattr("jobhunting.db.conectar", lambda url: FakeConn())
    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario:SECRETO-BD@host/db")


class FakeConn:
    def close(self):
        pass


AHORA = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)


def http_prohibido(url, datos):
    raise AssertionError("no debe llamar a http")


def test_main_sin_token_imprime_y_sale_0(entorno, capsys):
    assert mercado.main(["--entorno", "prod"], ahora=AHORA, http=http_prohibido) == 0
    out = capsys.readouterr().out
    assert "Mercado 2026-11-10" in out and "::warning::" in out


def test_main_envia_con_token(entorno, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    llamadas = []
    assert mercado.main(["--entorno", "dev"], ahora=AHORA, http=http_ok(llamadas)) == 0
    assert len(llamadas) == 1 and llamadas[0][1]["text"].startswith("[dev] ")
    assert TOKEN not in capsys.readouterr().out


def test_main_dry_run_no_llama_http(entorno, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    assert mercado.main(["--entorno", "prod", "--dry-run"], ahora=AHORA, http=http_prohibido) == 0
    assert "Mercado 2026-11-10" in capsys.readouterr().out


def test_main_error_de_telegram_sale_1_sin_token(entorno, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)

    def http(url, datos):
        raise OSError(url)
    assert mercado.main(["--entorno", "prod"], ahora=AHORA, http=http) == 1
    c = capsys.readouterr()
    assert TOKEN not in c.out + c.err


def test_main_error_bd_sale_1_sin_filtrar_url(entorno, monkeypatch, capsys):
    def malo(url):
        raise ValueError(f"fallo con {url}")
    monkeypatch.setattr("jobhunting.db.conectar", malo)
    assert mercado.main(["--entorno", "prod"], ahora=AHORA, http=http_prohibido) == 1
    c = capsys.readouterr()
    assert "SECRETO-BD" not in c.out + c.err and "postgresql://" not in c.out + c.err


def test_main_error_al_leer_sale_1_sin_filtrar_url(entorno, monkeypatch, capsys):
    def malo(conn):
        raise Exception("conexion postgresql://usuario:SECRETO-BD@host/db caida")
    monkeypatch.setattr("jobhunting.mercado.leer", malo)
    assert mercado.main(["--entorno", "prod"], ahora=AHORA, http=http_prohibido) == 1
    c = capsys.readouterr()
    assert "SECRETO-BD" not in c.out + c.err


def test_main_sin_database_url_sale_1(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert mercado.main(["--entorno", "prod"], http=http_prohibido) == 1


# --- leer contra la vista real (solo con BD) ---
def test_leer_contra_la_vista(conn):
    from jobhunting import db
    db.migrar(conn)
    conn.execute("INSERT INTO recuento_diario (dia,portal,n_vistas,n_nuevas,n_unicas) "
                 "VALUES ('2026-11-09','tecnoempleo',10,1,9),('2026-11-10','tecnoempleo',12,2,10),"
                 "('2026-11-10','feinaactiva',4,0,4)")
    filas = mercado.leer(conn)
    assert [f.portal for f in filas] == ["feinaactiva", "tecnoempleo"]
    t = next(f for f in filas if f.portal == "tecnoempleo")
    assert isinstance(t, Fila) and t.dia == date(2026, 11, 10) and t.d_vistas_1d == 2 and t.d_vistas_7d is None
    assert "Fuente Feina Activa" in mercado.formatear(filas, "prod", date(2026, 11, 10))


def test_leer_sin_vista_error_claro(conn):
    with pytest.raises(RuntimeError, match="004"):
        mercado.leer(conn)
