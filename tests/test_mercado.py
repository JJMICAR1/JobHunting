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
TIT = "📊 Mercado laboral en Catalunya\nMartes 10 de noviembre"


def test_formatear_basico_prod():
    t = mercado.formatear([fila()], "prod", HOY)
    assert t.startswith(TIT) and "[dev]" not in t
    assert "Hoy hay 100 ofertas activas (90 puestos distintos).\n" \
           "Son 4 más que ayer (+4,2 %) y 10 menos que hace una semana." in t
    assert "Han entrado 5 ofertas nuevas y han desaparecido 3." in t
    assert "Por portal:\n• Tecnoempleo: 100 ofertas (+4 vs ayer). 5 nuevas, 3 retiradas." in t


def test_formatear_dev_prefijo():
    t = mercado.formatear([fila()], "dev", HOY)
    assert t.startswith("🧪 [dev] Mercado laboral en Catalunya\nMartes 10 de noviembre")


def test_formatear_nulls_sin_raya_ni_none():
    t = mercado.formatear([fila(d_vistas_1d=None, d_vistas_7d=None, d_unicas_1d=None, d_unicas_7d=None,
                                n_desaparecidas=None)], "prod", HOY)
    assert "Es el primer día con datos, aún no hay con qué comparar." in t
    assert "None" not in t and "—" not in t and "desaparecido" not in t and "retirada" not in t
    assert "• Tecnoempleo: 100 ofertas. 5 nuevas." in t
    assert "Han entrado 5 ofertas nuevas." in t


def test_formatear_sin_datos_de_hoy():
    t = mercado.formatear([fila(dia=date(2026, 11, 8))], "prod", HOY)
    assert "Hoy no hay datos todavía." in t
    assert "• Tecnoempleo: sin datos de hoy (último: 08/11/2026)." in t
    assert "ofertas activas" not in t and "Han entrado" not in t


def test_formatear_total_solo_con_filas_de_hoy():
    t = mercado.formatear([fila("a"), fila("b", n_vistas=50, n_nuevas=1, n_unicas=10),
                           fila("c", dia=date(2026, 11, 1), n_vistas=999)], "prod", HOY)
    assert "Hoy hay 150 ofertas activas (100 puestos distintos)." in t
    assert "Son 8 más que ayer (+5,6 %) y 20 menos que hace una semana." in t
    assert "Han entrado 6 ofertas nuevas y han desaparecido 6." in t
    assert "1.149" not in t


def test_formatear_acepta_datetime_utc():
    t = mercado.formatear([fila()], "prod", datetime(2026, 11, 10, 5, 17, tzinfo=timezone.utc))
    assert t.startswith(TIT)


def test_cita_feina_solo_si_aparece():
    assert "Fuente:" not in mercado.formatear([fila()], "prod", HOY)
    t = mercado.formatear([fila(), fila("feinaactiva")], "prod", HOY)
    assert "• Feina Activa: " in t
    assert t.endswith("Fuente: Feina Activa (Generalitat de Catalunya), datos del 10/11/2026.")


def test_lista_vacia():
    t = mercado.formatear([], "prod", HOY)
    assert t == "📊 Mercado laboral en Catalunya\nMartes 10 de noviembre\n\nHoy no hay datos todavía."
    assert mercado.formatear([], "dev", HOY).startswith("🧪 [dev] Mercado laboral en Catalunya")


@pytest.mark.parametrize("dia,nombre", [
    (date(2026, 11, 9), "Lunes"), (date(2026, 11, 10), "Martes"), (date(2026, 11, 11), "Miércoles"),
    (date(2026, 11, 12), "Jueves"), (date(2026, 11, 13), "Viernes"), (date(2026, 11, 14), "Sábado"),
    (date(2026, 11, 15), "Domingo")])
def test_dias_de_la_semana(dia, nombre):
    assert mercado.formatear([], "prod", dia).splitlines()[1] == f"{nombre} {dia.day} de noviembre"


@pytest.mark.parametrize("mes,nombre", list(enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
     "noviembre", "diciembre"], 1)))
def test_meses(mes, nombre):
    d = date(2026, mes, 1)
    linea = mercado.formatear([], "prod", d).splitlines()[1]
    assert linea.endswith(f" 1 de {nombre}") and linea.split()[0] in mercado.DIAS


def test_fecha_conocida_jueves_5_noviembre():
    assert mercado.formatear([], "prod", date(2026, 11, 5)).splitlines()[1] == "Jueves 5 de noviembre"


@pytest.mark.parametrize("n,txt", [(999, "999"), (1000, "1.000"), (12345, "12.345")])
def test_miles_con_punto(n, txt):
    t = mercado.formatear([fila(n_vistas=n, n_unicas=n, d_vistas_1d=None, d_vistas_7d=None)], "prod", HOY)
    assert f"Hoy hay {txt} ofertas activas ({txt} puestos distintos)." in t
    assert f"• Tecnoempleo: {txt} ofertas." in t
    assert "," not in t.split("Por portal:")[0].split("\n\n")[1]


def test_porcentaje_positivo_con_coma_y_signo():
    t = mercado.formatear([fila(n_vistas=1007, d_vistas_1d=7, d_vistas_7d=None)], "prod", HOY)
    assert "Son 7 más que ayer (+0,7 %)." in t


def test_porcentaje_negativo():
    t = mercado.formatear([fila(n_vistas=988, d_vistas_1d=-12, d_vistas_7d=None)], "prod", HOY)
    assert "Son 12 menos que ayer (-1,2 %)." in t


def test_total_de_ayer_cero_sin_porcentaje():
    t = mercado.formatear([fila(n_vistas=5, d_vistas_1d=5, d_vistas_7d=None)], "prod", HOY)
    assert "Son 5 más que ayer." in t and "%" not in t


def test_delta_cero_igual_que_ayer():
    t = mercado.formatear([fila(d_vistas_1d=0, d_vistas_7d=None)], "prod", HOY)
    assert "Es igual que ayer." in t and "%" not in t
    t = mercado.formatear([fila(d_vistas_1d=0, d_vistas_7d=3)], "prod", HOY)
    assert "Es igual que ayer y 3 más que hace una semana." in t
    t = mercado.formatear([fila(d_vistas_1d=None, d_vistas_7d=0)], "prod", HOY)
    assert "Es igual que hace una semana." in t


def test_solo_1d_sin_7d():
    t = mercado.formatear([fila(d_vistas_1d=4, d_vistas_7d=None)], "prod", HOY)
    assert "Son 4 más que ayer (+4,2 %)." in t and "hace una semana" not in t


def test_solo_7d_sin_1d():
    t = mercado.formatear([fila(d_vistas_1d=None, d_vistas_7d=-5)], "prod", HOY)
    assert "Son 5 menos que hace una semana." in t and "ayer" not in t


def test_un_dia_sin_comparar_si_un_portal_no_tiene_delta():
    t = mercado.formatear([fila("a"), fila("b", d_vistas_1d=None)], "prod", HOY)
    assert "Son 4 más que ayer" not in t and "Son 4" not in t
    assert "hace una semana" in t


def test_singular():
    t = mercado.formatear([fila(n_vistas=1, n_unicas=1, n_nuevas=1, n_desaparecidas=1,
                                d_vistas_1d=1, d_vistas_7d=None)], "prod", HOY)
    assert "Hoy hay 1 oferta activa (1 puesto distinto)." in t
    assert "Ha entrado 1 oferta nueva y ha desaparecido 1." in t
    assert "• Tecnoempleo: 1 oferta (+1 vs ayer). 1 nueva, 1 retirada." in t


def test_n_desaparecidas_null_omite_desaparecido():
    t = mercado.formatear([fila("a", n_desaparecidas=None), fila("b", n_desaparecidas=2)], "prod", HOY)
    assert "desaparecido" not in t
    assert "Han entrado 10 ofertas nuevas." in t
    assert "• a: 100 ofertas (+4 vs ayer). 5 nuevas." in t
    assert "• b: 100 ofertas (+4 vs ayer). 5 nuevas, 2 retiradas." in t


def test_orden_por_ofertas_descendente():
    t = mercado.formatear([fila("a", n_vistas=50), fila("b", n_vistas=200), fila("c", n_vistas=100)],
                          "prod", HOY)
    assert t.index("• b:") < t.index("• c:") < t.index("• a:")


def test_portal_sin_datos_de_hoy_al_final_y_fuera_de_totales():
    t = mercado.formatear([fila("viejo", dia=date(2026, 11, 1), n_vistas=5000),
                           fila("a", n_vistas=10), fila("b", n_vistas=20)], "prod", HOY)
    assert t.index("• b:") < t.index("• a:") < t.index("• viejo:")
    assert "• viejo: sin datos de hoy (último: 01/11/2026)." in t
    assert "Hoy hay 30 ofertas activas" in t and "5.030" not in t


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
    assert "Mercado laboral en Catalunya\nMartes 10 de noviembre" in out and "::warning::" in out


def test_main_envia_con_token(entorno, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    llamadas = []
    assert mercado.main(["--entorno", "dev"], ahora=AHORA, http=http_ok(llamadas)) == 0
    assert len(llamadas) == 1 and llamadas[0][1]["text"].startswith("🧪 [dev] Mercado laboral")
    assert TOKEN not in capsys.readouterr().out


def test_main_dry_run_no_llama_http(entorno, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    assert mercado.main(["--entorno", "prod", "--dry-run"], ahora=AHORA, http=http_prohibido) == 0
    assert "Mercado laboral en Catalunya\nMartes 10 de noviembre" in capsys.readouterr().out


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
    assert "Fuente: Feina Activa" in mercado.formatear(filas, "prod", date(2026, 11, 10))


def test_leer_sin_vista_error_claro(conn):
    with pytest.raises(RuntimeError, match="004"):
        mercado.leer(conn)
