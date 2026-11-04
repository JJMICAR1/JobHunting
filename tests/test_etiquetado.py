"""Fase 7: bot de etiquetado con BD de pruebas y Telegram falso (sin red)."""
import json
import random
from datetime import date

import pytest

from conftest import utc
from jobhunting import db, etiquetado as E, reglas as R, telegram as tg
from jobhunting.modelo import Oferta

TOKEN = "123456:SECRETOKENabcXYZ"
CHAT = "987654321"
OTRO_CHAT = "555000111"
AHORA = utc(2026, 11, 4, 9, 0)
DIA = date(2026, 11, 4)


class FakeTG:
    """http falso: graba (metodo, datos) y responde segun `resp`/`fallos`."""

    def __init__(self, updates=None):
        self.calls = []
        self.updates = updates or []
        self.fallos = {}      # metodo -> status http (aplica siempre) o excepcion
        self.fallo_en = {}    # (metodo, n-esima llamada empezando en 1) -> status/excepcion
        self.n = {}
        self.msg_id = 100

    def __call__(self, url, datos):
        assert url.startswith(f"https://api.telegram.org/bot{TOKEN}/")
        metodo = url.rsplit("/", 1)[1]
        self.calls.append((metodo, json.loads(json.dumps(datos))))
        self.n[metodo] = self.n.get(metodo, 0) + 1
        f = self.fallo_en.get((metodo, self.n[metodo]), self.fallos.get(metodo))
        if isinstance(f, Exception):
            raise f
        if f:
            return f, None
        if metodo == "getUpdates":
            return 200, {"ok": True, "result": self.updates}
        if metodo == "sendMessage":
            self.msg_id += 1
            return 200, {"ok": True, "result": {"message_id": self.msg_id}}
        return 200, {"ok": True, "result": True}

    def ofertas(self):
        """sendMessage de ofertas (llevan botones); excluye intro y respuestas a comandos."""
        return [d for d in self.de("sendMessage") if "reply_markup" in d]

    def intros(self):
        return [d for d in self.de("sendMessage")
                if "reply_markup" not in d and d["text"].startswith(("Lote de hoy", "Aún aprendo"))]

    def de(self, metodo):
        return [d for m, d in self.calls if m == metodo]


def of(i, titulo=None, **kw):
    base = dict(portal="tecnoempleo", id_portal=f"rf-{i}", titulo=titulo or f"Oferta {i}",
                url=f"https://www.tecnoempleo.com/x/rf-{i}", empresa="ACME", ubicacion="Barcelona",
                fecha_publicacion=utc(2026, 11, 3), ciudad="Barcelona", modalidad="remoto")
    base.update(kw)
    return Oferta(**base)


@pytest.fixture
def bd(conn):
    db.migrar(conn)
    return conn


def poner_ofertas(conn, ofs, ahora=AHORA):
    db.guardar_ofertas(conn, ofs, ahora)


def n(conn, tabla):
    return conn.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]


def cfg(conn, clave):
    return E.leer_config(conn, clave, "AUSENTE")


def upd(uid, **kw):
    return {"update_id": uid, **kw}


def msg(uid, texto, chat=CHAT):
    return upd(uid, message={"message_id": uid, "chat": {"id": int(chat)}, "text": texto})


def clic(uid, data, chat=CHAT, cid=None):
    return upd(uid, callback_query={"id": cid or f"cq{uid}", "data": data,
                                    "message": {"message_id": 7, "chat": {"id": int(chat)}, "text": "Oferta"}})


def enviar(conn, http, entorno="prod", ahora=AHORA, dry=False):
    return E.enviar_lote(conn, entorno, TOKEN, CHAT, ahora, dry, http)


# --- migracion 006 ---

def test_migracion_006_up_down_up(conn):
    assert "006_etiquetado" in db.migrar(conn)
    poner_ofertas(conn, [of(1)])
    e1 = conn.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                      "WHERE table_schema = current_schema() ORDER BY 1,2").fetchall()
    assert {"config", "envios_etiquetado", "etiquetas"} <= {r[0] for r in e1}
    assert db.migrar(conn) == []
    conn.execute((db.DIR_MIGRACIONES / "006_etiquetado.down.sql").read_text(encoding="utf-8"))
    tablas = {r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables "
                                         "WHERE table_schema = current_schema()").fetchall()}
    assert not tablas & {"config", "envios_etiquetado", "etiquetas"} and "ofertas" in tablas
    assert n(conn, "ofertas") == 1
    assert db.migrar(conn) == ["006_etiquetado"]
    e2 = conn.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                      "WHERE table_schema = current_schema() ORDER BY 1,2").fetchall()
    assert e1 == e2


def test_migracion_006_restricciones(bd):
    import psycopg
    poner_ofertas(bd, [of(1)])
    with pytest.raises(psycopg.errors.CheckViolation):
        bd.execute("INSERT INTO envios_etiquetado (portal,id_portal,enviado,muestra) "
                   "VALUES ('tecnoempleo','rf-1',now(),'otra')")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        bd.execute("INSERT INTO envios_etiquetado (portal,id_portal,enviado,muestra) "
                   "VALUES ('tecnoempleo','nada',now(),'azar')")
    bd.execute("INSERT INTO envios_etiquetado (portal,id_portal,enviado,muestra) VALUES ('tecnoempleo','rf-1',now(),'azar')")
    with pytest.raises(psycopg.errors.UniqueViolation):
        bd.execute("INSERT INTO envios_etiquetado (portal,id_portal,enviado,muestra) "
                   "VALUES ('tecnoempleo','rf-1',now(),'reglas')")


def test_borrar_oferta_borra_envio_y_etiqueta(bd):
    poner_ofertas(bd, [of(1)])
    enviar(bd, FakeTG())
    eid = bd.execute("SELECT id FROM envios_etiquetado").fetchone()[0]
    E.guardar_etiqueta(bd, eid, True, AHORA)
    bd.execute("DELETE FROM ofertas")
    assert n(bd, "envios_etiquetado") == 0 and n(bd, "etiquetas") == 0


# --- seleccion 70/30 ---

def cands_con_notas(n_si=14, n_otras=10):
    from datetime import timedelta
    cs = []
    for i in range(n_si + n_otras):
        t = f"Python SQL dev {i}" if i < n_si // 2 else (f"Python dev {i}" if i < n_si else f"Cocinero {i}")
        cs.append(dict(portal="tecnoempleo", id_portal=f"rf-{i:02d}", titulo=t, empresa="X", ciudad=None,
                       modalidad=None, url="https://x/y", ultima_vez=AHORA + timedelta(minutes=i)))
    return cs


def test_seleccion_70_30_determinista():
    r = R.Reglas(si=("python", "sql"))
    cs = cands_con_notas()
    a = E.seleccionar(cs, r, 10, DIA)
    b = E.seleccionar(list(cs), r, 10, DIA)   # candidatas() ya llega ordenada: mismo orden -> mismo lote
    assert [c["id_portal"] for c in a] == [c["id_portal"] for c in b]
    assert len(a) == 10 and len({c["id_portal"] for c in a}) == 10
    reglas = [c for c in a if c["muestra"] == "reglas"]
    azar = [c for c in a if c["muestra"] == "azar"]
    assert (len(reglas), len(azar)) == (7, 3)
    # las 7 de reglas son las 7 de mayor nota (todas con nota 2: hay 7 con python+sql)
    assert all(c["nota"] == 2.0 for c in reglas)
    assert [c["muestra"] for c in a] == ["reglas"] * 7 + ["azar"] * 3


def test_seleccion_empate_gana_la_mas_reciente():
    r = R.Reglas(si=("python",))
    cs = cands_con_notas()
    sel = [c for c in E.seleccionar(cs, r, 10, DIA) if c["muestra"] == "reglas"]
    # 14 con nota 1 o 2; 7 con nota 2 (i=0..6) entran todas; el resto de empates no se mira
    assert {c["id_portal"] for c in sel} == {f"rf-{i:02d}" for i in range(14)} & {c["id_portal"] for c in sel}
    r2 = R.Reglas(si=("dev",))   # todas las "dev" empatan a 1: entran las 7 mas recientes de las 14
    sel2 = [c for c in E.seleccionar(cs, r2, 10, DIA) if c["muestra"] == "reglas"]
    assert {c["id_portal"] for c in sel2} == {f"rf-{i:02d}" for i in range(7, 14)}


def test_seleccion_azar_depende_del_dia_pero_no_de_la_ejecucion():
    r = R.Reglas(si=("python",))
    cs = cands_con_notas(n_otras=40)
    azar = lambda d: [c["id_portal"] for c in E.seleccionar(cs, r, 10, d) if c["muestra"] == "azar"]
    assert azar(DIA) == azar(DIA)
    assert azar(DIA) == [c["id_portal"] for c in random.Random(DIA.toordinal()).sample(
        [c for c in cs if c["id_portal"] not in {x["id_portal"] for x in E.seleccionar(cs, r, 10, DIA) if x["muestra"] == "reglas"}], 3)]
    assert any(azar(date(2026, 11, d)) != azar(DIA) for d in range(5, 15))


def test_seleccion_sin_reglas_todo_al_azar_y_pocas_candidatas():
    cs = cands_con_notas()
    sel = E.seleccionar(cs, R.Reglas(), 10, DIA)
    assert len(sel) == 10 and {c["muestra"] for c in sel} == {"azar"}
    assert len(E.seleccionar(cs[:3], R.Reglas(si=("python",)), 10, DIA)) == 3
    assert E.seleccionar([], R.Reglas(), 10, DIA) == []


def test_formato_y_teclado():
    c = dict(titulo="Dev", empresa="ACME", ciudad="Girona", modalidad="remoto", url="https://u/1",
             nota=1.5, motivos=["python", "Girona"], muestra="azar")
    t = E.formatear(c, "dev", True)
    assert t.splitlines() == ["[dev] Dev", "ACME", "Girona · remoto", "Nota 1,5: python, Girona [azar]", "https://u/1"]
    assert "Nota" not in E.formatear(c, "prod", False) and not E.formatear(c, "prod", False).startswith("[dev]")
    assert E.teclado("prod", 5)["inline_keyboard"][0][0]["callback_data"] == "p:s:5"
    assert E.teclado("dev", 5)["inline_keyboard"][0][1]["callback_data"] == "d:n:5"


@pytest.mark.parametrize("data,ent,esperado", [
    ("p:s:5", "prod", (True, 5)), ("p:n:5", "prod", (False, 5)), ("d:s:5", "dev", (True, 5)),
    ("d:s:5", "prod", None), ("p:s:5", "dev", None), ("p:x:5", "prod", None), ("p:s:", "prod", None),
    ("p:s:-1", "prod", None), ("p:s:5:6", "prod", None), ("", "prod", None), (None, "prod", None)])
def test_parsear_callback(data, ent, esperado):
    assert E.parsear_callback(data, ent) == esperado


# --- envio del lote ---

def test_envio_basico_y_una_vez_al_dia(bd):
    poner_ofertas(bd, [of(i) for i in range(15)])
    http = FakeTG()
    assert enviar(bd, http) == 10
    assert len(http.ofertas()) == 10 and len(http.intros()) == 1 and n(bd, "envios_etiquetado") == 10
    assert n(bd, "avisos") == 1
    assert bd.execute("SELECT tipo FROM avisos").fetchone()[0] == "etiquetado"
    assert bd.execute("SELECT count(*) FROM envios_etiquetado WHERE message_id IS NULL").fetchone()[0] == 0
    for d in http.ofertas():
        assert d["chat_id"] == CHAT and d["disable_web_page_preview"] is True
        assert d["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("p:s:")
    # segunda ejecucion el mismo dia: nada
    http2 = FakeTG()
    assert enviar(bd, http2) == 0 and http2.calls == []
    assert n(bd, "envios_etiquetado") == 10 and n(bd, "avisos") == 1
    # a otra hora del mismo dia, tambien
    assert enviar(bd, http2, ahora=utc(2026, 11, 4, 22, 0)) == 0 and http2.calls == []


def test_una_oferta_nunca_se_envia_dos_veces(bd):
    poner_ofertas(bd, [of(i) for i in range(12)])
    enviar(bd, FakeTG())
    # al dia siguiente se vuelven a ver las 12 y se anaden 3: solo salen las no enviadas
    dia2 = utc(2026, 11, 5, 9, 0)
    poner_ofertas(bd, [of(i) for i in range(15)], dia2)
    http = FakeTG()
    assert enviar(bd, http, ahora=dia2) == 5
    assert n(bd, "envios_etiquetado") == 15
    assert bd.execute("SELECT count(*) FROM (SELECT 1 FROM envios_etiquetado GROUP BY portal,id_portal "
                      "HAVING count(*) > 1) x").fetchone()[0] == 0
    # el dia 3 no queda nada nuevo: no envia ni un mensaje
    dia3 = utc(2026, 11, 6, 9, 0)
    poner_ofertas(bd, [of(i) for i in range(15)], dia3)
    http3 = FakeTG()
    assert enviar(bd, http3, ahora=dia3) == 0 and http3.de("sendMessage") == []


def test_registrar_envio_duplicado_devuelve_none(bd):
    poner_ofertas(bd, [of(1)])
    assert isinstance(E.registrar_envio(bd, "tecnoempleo", "rf-1", AHORA, "azar", None), int)
    assert E.registrar_envio(bd, "tecnoempleo", "rf-1", AHORA, "azar", None) is None
    assert n(bd, "envios_etiquetado") == 1


def test_sin_ofertas_de_hoy_no_envia(bd, capsys):
    poner_ofertas(bd, [of(i) for i in range(5)], utc(2026, 11, 3, 9, 0))   # ayer
    http = FakeTG()
    assert enviar(bd, http) == 0 and http.calls == [] and n(bd, "avisos") == 0
    assert "sin ofertas" in capsys.readouterr().out


def test_solo_ofertas_vistas_hoy_utc(bd):
    poner_ofertas(bd, [of(1)], utc(2026, 11, 3, 23, 59))
    poner_ofertas(bd, [of(2)], utc(2026, 11, 4, 0, 0))
    poner_ofertas(bd, [of(3)], utc(2026, 11, 5, 0, 0))
    assert [c["id_portal"] for c in E.candidatas(bd, DIA)] == ["rf-2"]


def test_respeta_lote_configurado_y_reglas_en_mensaje(bd):
    poner_ofertas(bd, [of(i, titulo=f"Python dev {i}" if i < 3 else f"Otro {i}") for i in range(20)])
    E.guardar_config(bd, "lote", 4, AHORA)
    E.guardar_config(bd, "reglas", {"si": ["python"], "no": [], "ciudades": [], "modalidades": []}, AHORA)
    http = FakeTG()
    assert enviar(bd, http) == 4
    textos = [d["text"] for d in http.ofertas()]
    assert sum("[azar]" not in t for t in textos) == round(4 * 0.7) == 3
    assert all("Nota" in t for t in textos)
    assert bd.execute("SELECT count(*) FROM envios_etiquetado WHERE muestra='reglas'").fetchone()[0] == 3


def test_lote_invalido_en_config_usa_defecto(bd):
    for v in (0, 31, "x", True, 2.5, None):
        E.guardar_config(bd, "lote", v, AHORA)
        assert E.leer_lote(bd) == E.LOTE_DEFECTO


def test_lote_cortado_a_medias_se_reanuda_sin_duplicar(bd):
    poner_ofertas(bd, [of(i) for i in range(15)])
    http = FakeTG()
    http.fallo_en[("sendMessage", 5)] = 500   # 1 = intro, 2-4 = ofertas, 5 = 4a oferta
    with pytest.raises(RuntimeError):
        enviar(bd, http)
    assert n(bd, "envios_etiquetado") == 3 and n(bd, "avisos") == 0     # la reserva fallida se deshace
    ya = {r[0] for r in bd.execute("SELECT id_portal FROM envios_etiquetado").fetchall()}
    http2 = FakeTG()
    assert enviar(bd, http2) == 7
    assert len(http2.ofertas()) == 7 and http2.intros() == []   # la intro no se repite al reanudar
    assert n(bd, "envios_etiquetado") == 10 and n(bd, "avisos") == 1
    nuevos = {r[0] for r in bd.execute("SELECT id_portal FROM envios_etiquetado").fetchall()} - ya
    assert len(nuevos) == 7
    assert enviar(bd, FakeTG()) == 0


def test_429_al_enviar_para_sin_reintentos(bd):
    poner_ofertas(bd, [of(i) for i in range(15)])
    http = FakeTG()
    http.fallo_en[("sendMessage", 4)] = 429   # 1 = intro, 2-3 = ofertas, 4 = 3a oferta
    with pytest.raises(tg.LimiteTelegram):
        enviar(bd, http)
    assert len(http.de("sendMessage")) == 4          # intro + 3 intentos: ni un reintento ni mas envios
    assert n(bd, "envios_etiquetado") == 2 and n(bd, "avisos") == 0


def test_dry_run_en_enviar_lote_no_escribe_ni_llama(bd, capsys):
    poner_ofertas(bd, [of(i) for i in range(15)])
    http = FakeTG()
    assert enviar(bd, http, dry=True) == 10
    assert http.calls == [] and n(bd, "envios_etiquetado") == 0 and n(bd, "avisos") == 0
    out = capsys.readouterr().out
    assert "(sin enviar)" in out and TOKEN not in out and CHAT not in out


# --- recoger: clics ---

def preparar_envios(bd, k=3):
    poner_ofertas(bd, [of(i) for i in range(k)])
    enviar(bd, FakeTG())
    return [r[0] for r in bd.execute("SELECT id FROM envios_etiquetado ORDER BY id_portal").fetchall()]


def etiquetas(bd):
    return bd.execute("SELECT id_portal, etiqueta FROM etiquetas ORDER BY id_portal").fetchall()


def recoger(bd, http, entorno="prod", ahora=AHORA):
    return E.recoger(bd, entorno, TOKEN, CHAT, ahora, http)


def test_callback_guarda_etiqueta_y_responde(bd):
    ids = preparar_envios(bd)
    http = FakeTG([clic(10, f"p:s:{ids[0]}"), clic(11, f"p:n:{ids[1]}")])
    assert recoger(bd, http) == 2
    assert dict(etiquetas(bd)) == {"rf-0": True, "rf-1": False}
    resp = http.de("answerCallbackQuery")
    assert [r["callback_query_id"] for r in resp] == ["cq10", "cq11"] and resp[0]["text"] == "Sí ✅"
    ed = http.de("editMessageText")
    assert ed[0]["text"].endswith("Sí ✅") and ed[1]["text"].endswith("No ❌")
    assert ed[0]["reply_markup"] == {"inline_keyboard": []} and ed[0]["chat_id"] == CHAT


def test_reclic_cambia_la_etiqueta_ultimo_gana(bd):
    ids = preparar_envios(bd)
    recoger(bd, FakeTG([clic(10, f"p:s:{ids[0]}")]))
    assert etiquetas(bd) == [("rf-0", True)]
    recoger(bd, FakeTG([clic(11, f"p:n:{ids[0]}")]), ahora=utc(2026, 11, 4, 10, 0))
    assert etiquetas(bd) == [("rf-0", False)]
    assert bd.execute("SELECT etiquetada FROM etiquetas").fetchone()[0] == utc(2026, 11, 4, 10, 0)
    assert n(bd, "etiquetas") == 1


def test_mismo_update_dos_veces_mismo_estado(bd):
    ids = preparar_envios(bd)
    u = [clic(10, f"p:s:{ids[0]}")]
    recoger(bd, FakeTG(u))
    e1 = bd.execute("SELECT * FROM etiquetas").fetchall()
    recoger(bd, FakeTG(u))
    assert bd.execute("SELECT * FROM etiquetas").fetchall() == e1 and n(bd, "etiquetas") == 1


def test_callback_otro_chat_o_otro_entorno_se_ignora(bd):
    ids = preparar_envios(bd)
    http = FakeTG([clic(10, f"p:s:{ids[0]}", chat=OTRO_CHAT), clic(11, f"d:s:{ids[1]}"),
                   clic(12, "basura"), clic(13, f"p:s:{ids[2]}x"), upd(14, callback_query={"id": "z", "data": f"p:s:{ids[0]}"})])
    assert recoger(bd, http) == 5
    assert n(bd, "etiquetas") == 0
    assert http.de("answerCallbackQuery") == [] and http.de("editMessageText") == []
    # aun asi se confirman (offset) para no reprocesarlos
    assert cfg(bd, "telegram_offset") == 15


def test_callback_de_envio_desconocido_no_rompe(bd):
    preparar_envios(bd)
    http = FakeTG([clic(10, "p:s:999999")])
    recoger(bd, http)
    assert n(bd, "etiquetas") == 0
    assert http.de("answerCallbackQuery")[0]["text"] == "Oferta desconocida" and http.de("editMessageText") == []
    assert cfg(bd, "telegram_offset") == 11


@pytest.mark.parametrize("data", ["p:s:" + "9" * 19, "p:s:99999999999999999999", "p:s:²", "p:n:١٢٣"])
def test_callback_con_id_no_valido_se_ignora_y_el_offset_avanza(bd, data):
    ids = preparar_envios(bd)
    http = FakeTG([clic(10, data), clic(11, f"p:s:{ids[0]}")])
    recoger(bd, http)
    assert len(http.de("answerCallbackQuery")) == 1       # solo el valido
    assert etiquetas(bd) == [("rf-0", True)] and cfg(bd, "telegram_offset") == 12


def test_parsear_callback_limite_18_cifras():
    assert E.parsear_callback("p:s:" + "9" * 18, "prod") == (True, int("9" * 18))
    assert E.parsear_callback("p:s:" + "9" * 19, "prod") is None
    assert E.parsear_callback("p:s:²", "prod") is None


def test_fallo_cosmetico_no_impide_guardar(bd, capsys):
    ids = preparar_envios(bd)
    http = FakeTG([clic(10, f"p:s:{ids[0]}")])
    http.fallos["answerCallbackQuery"] = 400
    http.fallos["editMessageText"] = RuntimeError("boom")
    recoger(bd, http)
    assert etiquetas(bd) == [("rf-0", True)] and cfg(bd, "telegram_offset") == 11


# --- recoger: offset ---

def test_prod_envia_offset_y_lo_guarda(bd):
    E.guardar_config(bd, "telegram_offset", 40, AHORA)
    http = FakeTG([msg(40, "/ayuda"), msg(41, "hola"), msg(45, "/ver")])
    recoger(bd, http)
    g = http.de("getUpdates")[0]
    assert g["offset"] == 40 and g["timeout"] == 0 and g["allowed_updates"] == ["message", "callback_query"]
    assert cfg(bd, "telegram_offset") == 46


def test_prod_sin_offset_previo_no_lo_envia_y_sin_updates_no_guarda(bd):
    http = FakeTG([])
    recoger(bd, http)
    assert "offset" not in http.de("getUpdates")[0]
    assert cfg(bd, "telegram_offset") == "AUSENTE"


def test_dev_no_envia_offset_ni_lo_guarda_ni_aplica_comandos(bd):
    E.guardar_config(bd, "telegram_offset", 40, AHORA)
    ids = preparar_envios(bd)
    http = FakeTG([msg(50, "/si python"), msg(51, "/lote 3"), clic(52, f"d:s:{ids[0]}"), clic(53, f"p:s:{ids[1]}")])
    recoger(bd, http, entorno="dev")
    assert "offset" not in http.de("getUpdates")[0]
    assert cfg(bd, "telegram_offset") == 40
    assert cfg(bd, "reglas") == "AUSENTE" and cfg(bd, "lote") == "AUSENTE"
    assert http.de("sendMessage") == []
    assert etiquetas(bd) == [("rf-0", True)]     # solo el callback con prefijo dev


def test_offset_en_fallo_a_mitad_no_pierde_updates_sin_procesar(bd):
    """Si un update falla (429 al responder), el offset apunta a ese update, no mas alla."""
    ids = preparar_envios(bd)
    http = FakeTG([clic(10, f"p:s:{ids[0]}"), clic(11, f"p:s:{ids[1]}"), clic(12, f"p:s:{ids[2]}")])
    http.fallo_en[("answerCallbackQuery", 2)] = 429
    with pytest.raises(tg.LimiteTelegram):
        recoger(bd, http)
    assert cfg(bd, "telegram_offset") == 11            # el 11 y el 12 se volveran a pedir
    # la siguiente hora Telegram los devuelve de nuevo con offset=11
    http2 = FakeTG([clic(11, f"p:s:{ids[1]}"), clic(12, f"p:s:{ids[2]}")])
    recoger(bd, http2)
    assert http2.de("getUpdates")[0]["offset"] == 11
    assert dict(etiquetas(bd)) == {"rf-0": True, "rf-1": True, "rf-2": True}
    assert cfg(bd, "telegram_offset") == 13


def test_offset_si_falla_el_primer_update_no_se_guarda(bd):
    ids = preparar_envios(bd)
    E.guardar_config(bd, "telegram_offset", 10, AHORA)
    http = FakeTG([clic(10, f"p:s:{ids[0]}"), clic(11, f"p:s:{ids[1]}")])
    http.fallo_en[("answerCallbackQuery", 1)] = 429
    with pytest.raises(tg.LimiteTelegram):
        recoger(bd, http)
    assert cfg(bd, "telegram_offset") == 10


def test_reglas_invalidas_no_bloquean_el_offset(bd):
    """Un comando con config.reglas invalida se responde y se da por consumido: no lanza y el offset avanza."""
    ids = preparar_envios(bd)
    http = FakeTG([clic(20, f"p:s:{ids[0]}"), msg(21, "/si python"), clic(22, f"p:s:{ids[1]}")])
    E.guardar_config(bd, "reglas", {"raro": 1}, AHORA)
    recoger(bd, http)
    assert cfg(bd, "telegram_offset") == 23
    assert dict(etiquetas(bd)) == {"rf-0": True, "rf-1": True}
    assert cfg(bd, "reglas") == {"raro": 1}
    resp = http.de("sendMessage")
    assert len(resp) == 1 and resp[0]["text"].startswith("Las reglas guardadas tienen un formato no válido")


def test_getupdates_falla_no_toca_offset(bd):
    E.guardar_config(bd, "telegram_offset", 7, AHORA)
    http = FakeTG()
    http.fallos["getUpdates"] = 500
    with pytest.raises(RuntimeError):
        recoger(bd, http)
    assert cfg(bd, "telegram_offset") == 7


def test_429_en_getupdates_para(bd):
    http = FakeTG()
    http.fallos["getUpdates"] = 429
    with pytest.raises(tg.LimiteTelegram):
        recoger(bd, http)
    assert len(http.calls) == 1


# --- recoger: comandos ---

def test_comandos_en_prod_guardan_reglas_y_responden(bd):
    http = FakeTG([msg(1, "/si Python"), msg(2, "/si python"), msg(3, "/no becario"), msg(4, "/ciudad Girona"),
                   msg(5, "/modalidad remoto"), msg(6, "/lote 12"), msg(7, "/ver"), msg(8, "/quitar becario")])
    recoger(bd, http)
    assert cfg(bd, "reglas") == {"si": ["python"], "no": [], "ciudades": ["girona"], "modalidades": ["remoto"]}
    assert cfg(bd, "lote") == 12
    resp = [d["text"] for d in http.de("sendMessage")]
    assert len(resp) == 8 and all(d["chat_id"] == CHAT for d in http.de("sendMessage"))
    assert resp[1].startswith("Ya estaba") and resp[5] == "Lote: 12 al día"
    assert "Sí: python" in resp[6] and "No: becario" in resp[6] and "0/100" in resp[6] and "Lote: 12" in resp[6]


def test_comando_repetido_deja_mismo_estado(bd):
    cs = [msg(1, "/si python"), msg(2, "/no java")]
    recoger(bd, FakeTG(cs))
    e1 = cfg(bd, "reglas")
    recoger(bd, FakeTG(cs))
    assert cfg(bd, "reglas") == e1


def test_comando_de_otro_chat_o_texto_normal_se_ignora(bd):
    http = FakeTG([msg(1, "/si hack", chat=OTRO_CHAT), msg(2, "hola"), upd(3), upd(4, message={"text": "/si x"})])
    recoger(bd, http)
    assert cfg(bd, "reglas") == "AUSENTE" and http.de("sendMessage") == []


def test_lote_invalido_no_cambia_config(bd):
    http = FakeTG([msg(1, "/lote 99"), msg(2, "/lote x")])
    recoger(bd, http)
    assert cfg(bd, "lote") == "AUSENTE"
    assert all(t.startswith("Uso: /lote") for t in (d["text"] for d in http.de("sendMessage")))


def test_ver_cuenta_progreso(bd):
    ids = preparar_envios(bd)
    recoger(bd, FakeTG([clic(1, f"p:s:{ids[0]}"), clic(2, f"p:n:{ids[1]}"), clic(3, f"p:n:{ids[2]}")]))
    http = FakeTG([msg(4, "/ver")])
    recoger(bd, http)
    assert "Progreso: 3/100 (Sí 1, No 2)" in http.de("sendMessage")[0]["text"]


# --- main: dev/prod, dry-run, secretos ---

@pytest.fixture
def entorno(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)


def test_main_prod_recoge_y_envia(conn, entorno):
    db.migrar(conn)
    poner_ofertas(conn, [of(i) for i in range(12)])
    http = FakeTG([msg(5, "/lote 3")])
    assert E.main(["--entorno", "prod"], ahora=AHORA, http=http) == 0
    assert len(http.de("sendMessage")) == 1 + 1 + 3     # respuesta al comando + intro + lote
    assert cfg(conn, "telegram_offset") == 6 and n(conn, "envios_etiquetado") == 3
    # segunda ejecucion: mismo estado
    estado = (n(conn, "envios_etiquetado"), n(conn, "avisos"), cfg(conn, "lote"))
    assert E.main(["--entorno", "prod"], ahora=AHORA, http=FakeTG()) == 0
    assert (n(conn, "envios_etiquetado"), n(conn, "avisos"), cfg(conn, "lote")) == estado


def test_main_dev_no_toca_offset_ni_comandos(conn, entorno):
    db.migrar(conn)
    poner_ofertas(conn, [of(i) for i in range(12)])
    http = FakeTG([msg(5, "/lote 3")])
    assert E.main(["--entorno", "dev"], ahora=AHORA, http=http) == 0
    assert "offset" not in http.de("getUpdates")[0] and cfg(conn, "telegram_offset") == "AUSENTE"
    assert cfg(conn, "lote") == "AUSENTE" and n(conn, "envios_etiquetado") == 10
    assert all(d["reply_markup"]["inline_keyboard"][0][0]["callback_data"].startswith("d:")
               for d in http.ofertas())
    assert len(http.ofertas()) == 10 and all(d["text"].startswith("[dev] ") for d in http.ofertas())


def test_main_dry_run_no_escribe_ni_llama(conn, entorno, capsys):
    db.migrar(conn)
    poner_ofertas(conn, [of(i) for i in range(12)])
    antes = [n(conn, t) for t in ("config", "envios_etiquetado", "etiquetas", "avisos", "ofertas")]
    http = FakeTG([msg(5, "/lote 3")])
    assert E.main(["--entorno", "prod", "--dry-run"], ahora=AHORA, http=http) == 0
    assert http.calls == []
    assert antes == [n(conn, t) for t in ("config", "envios_etiquetado", "etiquetas", "avisos", "ofertas")]
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and CHAT not in out.out + out.err


def test_main_dry_run_no_migra(conn, entorno):
    db.migrar(conn)
    conn.execute((db.DIR_MIGRACIONES / "006_etiquetado.down.sql").read_text(encoding="utf-8"))
    E.main(["--entorno", "prod", "--dry-run"], ahora=AHORA, http=FakeTG())
    assert conn.execute("SELECT to_regclass('config')").fetchone()[0] is None


def test_main_sin_token_solo_muestra(conn, db_url, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    db.migrar(conn)
    poner_ofertas(conn, [of(i) for i in range(3)])
    http = FakeTG()
    assert E.main(["--entorno", "dev"], ahora=AHORA, http=http) == 0
    assert http.calls == [] and n(conn, "envios_etiquetado") == 0 and n(conn, "avisos") == 0
    assert "Faltan TELEGRAM_BOT_TOKEN" in capsys.readouterr().out


def test_main_sin_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert E.main(["--entorno", "dev"]) == 1
    assert "DATABASE_URL" in capsys.readouterr().err   # nombre de la variable, no su valor


def test_main_429_para_con_cero_sin_reintentos(conn, entorno, capsys):
    db.migrar(conn)
    http = FakeTG()
    http.fallos["getUpdates"] = 429
    assert E.main(["--entorno", "prod"], ahora=AHORA, http=http) == 0
    assert len(http.calls) == 1
    assert "429" in capsys.readouterr().out


def test_main_error_telegram_devuelve_1(conn, entorno):
    db.migrar(conn)
    http = FakeTG()
    http.fallos["getUpdates"] = 500
    assert E.main(["--entorno", "prod"], ahora=AHORA, http=http) == 1


def test_ninguna_salida_contiene_secretos(conn, entorno, capsys, db_url):
    db.migrar(conn)
    poner_ofertas(conn, [of(i) for i in range(12)])
    ids_http = []
    casos = [
        FakeTG([msg(5, "/ver")]),                                                       # normal
        _con_fallo("getUpdates", RuntimeError(f"https://api.telegram.org/bot{TOKEN}/getUpdates chat {CHAT}")),
        _con_fallo("getUpdates", OSError(f"fallo https://api.telegram.org/bot{TOKEN}/x")),
        _con_fallo("sendMessage", ConnectionError(f"{TOKEN} {CHAT}")),
        _con_fallo("sendMessage", 500), _con_fallo("getUpdates", 429), _con_fallo("getUpdates", 403),
    ]
    for http in casos:
        E.main(["--entorno", "prod"], ahora=AHORA, http=http)
        E.main(["--entorno", "dev", "--dry-run"], ahora=AHORA, http=http)
    o = capsys.readouterr()
    todo = o.out + o.err
    for secreto in (TOKEN, "SECRETOKEN", CHAT, db_url, "postgres:postgres"):
        assert secreto not in todo, secreto


def _con_fallo(metodo, f):
    h = FakeTG()
    h.fallos[metodo] = f
    return h


def test_errores_de_bd_no_muestran_la_url(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://usuario:CLAVESECRETA@localhost:1/bd")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT)
    assert E.main(["--entorno", "prod"], ahora=AHORA, http=FakeTG()) == 1
    o = capsys.readouterr()
    todo = o.out + o.err
    assert "CLAVESECRETA" not in todo and "usuario" not in todo and "localhost:1" not in todo


# --- telegram.py ---

def test_telegram_errores_sin_token():
    def malo(url, datos):
        raise OSError(f"no se pudo abrir {url}")
    with pytest.raises(RuntimeError) as e:
        tg.llamar(TOKEN, "getUpdates", {}, malo)
    assert TOKEN not in str(e.value) and "OSError" in str(e.value)
    with pytest.raises(RuntimeError) as e:
        tg.llamar(TOKEN, "getUpdates", {}, lambda u, d: (200, {"ok": False}))
    assert TOKEN not in str(e.value)
    with pytest.raises(tg.LimiteTelegram):
        tg.llamar(TOKEN, "getUpdates", {}, lambda u, d: (429, None))
    assert tg.llamar(TOKEN, "x", {}, lambda u, d: (200, {"ok": True, "result": [1]})) == [1]


def test_mercado_sigue_reexportando_http_telegram():
    from jobhunting import mercado
    assert mercado.http_telegram is tg.http_telegram


def test_main_hace_strip_de_token_y_chat(conn, db_url, monkeypatch):
    db.migrar(conn)
    poner_ofertas(conn, [of(i) for i in range(3)])
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN + "\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", CHAT + "\n")
    http = FakeTG([msg(5, "/ver")])
    assert E.main(["--entorno", "prod"], ahora=AHORA, http=http) == 0
    env = http.de("sendMessage")
    assert len(env) == 1 + 1 + 3 and all(d["chat_id"] == CHAT for d in env)   # el comando del chat se obedece
    assert cfg(conn, "telegram_offset") == 6


def test_respuesta_a_comandos_se_recorta_a_4000(bd):
    r = {"si": [f"termino{i:03d}" + "x" * 40 for i in range(200)], "no": [f"n{i}" + "y" * 40 for i in range(200)],
         "ciudades": [], "modalidades": []}
    E.guardar_config(bd, "reglas", r, AHORA)
    assert len(R.aplicar_comando(R.Reglas.desde_dict(r), "/ver")[1]) > 4000
    http = FakeTG([msg(1, "/ver")])
    recoger(bd, http)
    t = http.de("sendMessage")[0]["text"]
    assert len(t) == E.MAX_TEXTO == 4000


# --- reglas aprendidas: bot ---

def etiquetar(bd, spec, ahora=AHORA):
    """spec: [(titulo, ciudad, modalidad, bool)]: crea ofertas, envios y etiquetas directamente."""
    for i, (t, c, m, et) in enumerate(spec):
        o = of(f"e{i}", titulo=t, ciudad=c, modalidad=m)
        poner_ofertas(bd, [o], utc(2026, 11, 3, 8, 0))
        eid = E.registrar_envio(bd, "tecnoempleo", f"rf-e{i}", utc(2026, 11, 3, 9, 0), "azar", None)
        E.guardar_etiqueta(bd, eid, et, ahora)


PATRON = [("Python dev", "Girona", "remoto", True)] * 5 + [("Cocinero jefe", "Lleida", "presencial", False)] * 5


def test_calcular_auto_guarda_solo_si_se_pide(bd):
    etiquetar(bd, PATRON)
    a = E.calcular_auto(bd, R.Reglas(), AHORA, guardar=False)
    assert "python" in a.si and "cocinero" in a.no and cfg(bd, "reglas_auto") == "AUSENTE"
    E.calcular_auto(bd, R.Reglas(), AHORA, guardar=True)
    assert cfg(bd, "reglas_auto")["si"] == list(a.si)


def test_calcular_auto_respeta_ignorar(bd):
    etiquetar(bd, PATRON)
    a = E.calcular_auto(bd, R.Reglas(ignorar=("python",)), AHORA, guardar=False)
    assert "python" not in a.si and "python dev" in a.si


def test_reglas_auto_solo_se_guarda_en_prod_sin_dry_run(bd):
    etiquetar(bd, PATRON)
    poner_ofertas(bd, [of(i) for i in range(5)])
    enviar(bd, FakeTG(), entorno="dev")
    assert cfg(bd, "reglas_auto") == "AUSENTE"
    bd.execute("DELETE FROM avisos")
    enviar(bd, FakeTG(), entorno="prod", dry=True)
    assert cfg(bd, "reglas_auto") == "AUSENTE"
    enviar(bd, FakeTG(), entorno="prod")
    assert "python" in cfg(bd, "reglas_auto")["si"]


def test_dev_nunca_escribe_config(bd):
    etiquetar(bd, PATRON)
    poner_ofertas(bd, [of(i) for i in range(5)])
    antes = bd.execute("SELECT clave, valor FROM config ORDER BY 1").fetchall()
    http = FakeTG([msg(1, "/si x"), msg(2, "/ver")])
    recoger(bd, http, entorno="dev")
    enviar(bd, http, entorno="dev")
    assert bd.execute("SELECT clave, valor FROM config ORDER BY 1").fetchall() == antes


def test_ver_en_prod_calcula_y_guarda_auto_y_progreso_primero(bd):
    etiquetar(bd, PATRON)
    http = FakeTG([msg(1, "/ver")])
    recoger(bd, http)
    t = http.de("sendMessage")[0]["text"]
    assert t.startswith("Progreso: 10/100 (Sí 5, No 5)")
    assert "Aprendido de tus Sí/No" in t and "python" in t
    assert "python" in cfg(bd, "reglas_auto")["si"]


@pytest.mark.xfail(strict=True, reason="reglas.py _ver: `a = p.get('auto')` es un dict con 4 listas vacias (truthy), "
                   "asi que /ver con <10 etiquetas imprime 'Aprendido de tus Sí/No: ' vacio en vez de 'nada todavía'")
def test_ver_sin_etiquetas_suficientes_dice_nada_todavia(bd):
    http = FakeTG([msg(1, "/ver")])
    recoger(bd, http)
    assert "nada todavía" in http.de("sendMessage")[0]["text"]


def test_olvidar_y_quitar_sobre_ignorar_por_bot(bd):
    etiquetar(bd, PATRON)
    recoger(bd, FakeTG([msg(1, "/olvidar Python")]))
    assert cfg(bd, "reglas")["ignorar"] == ["python"]
    assert "python" not in E.calcular_auto(bd, E.leer_reglas(bd), AHORA, False).si
    http = FakeTG([msg(2, "/quitar python")])
    recoger(bd, http)
    assert "ignorar" not in cfg(bd, "reglas") and http.de("sendMessage")[0]["text"] == "Quitado: python"
    assert "python" in E.calcular_auto(bd, E.leer_reglas(bd), AHORA, False).si


def test_intro_variantes():
    el = [{"muestra": "reglas"}] * 7 + [{"muestra": "azar"}] * 3
    assert E.mensaje_intro(el, R.Reglas(), 4) == "Aún aprendo: llevas 4/10 etiquetas para empezar a puntuar"
    sin = E.mensaje_intro(el, R.Reglas(), 40)
    assert sin.startswith("Lote de hoy: 10 al azar") and "patrones" in sin
    auto = R.Reglas(si=tuple(f"s{i}" for i in range(8)), no=("malo",))
    m = E.mensaje_intro(el, auto, 40).splitlines()
    assert m == ["Lote de hoy: 7 por lo que he aprendido de ti, 3 al azar", "Te gusta: s0, s1, s2, s3, s4",
                 "No te gusta: malo"]
    solo_no = E.mensaje_intro(el, R.Reglas(no=("malo",)), 40)
    assert "Te gusta" not in solo_no and "No te gusta: malo" in solo_no


def test_intro_se_envia_una_vez_con_menos_de_10_etiquetas(bd):
    poner_ofertas(bd, [of(i) for i in range(12)])
    http = FakeTG()
    enviar(bd, http)
    assert [d["text"] for d in http.intros()] == ["Aún aprendo: llevas 0/10 etiquetas para empezar a puntuar"]
    assert http.de("sendMessage")[0] == http.intros()[0]      # va la primera


def test_intro_con_patrones_y_nota_usa_manual_mas_auto(bd):
    etiquetar(bd, PATRON)
    poner_ofertas(bd, [of(i, titulo="Python dev" if i < 3 else f"Otro {i}", ciudad="Girona", modalidad="remoto")
                       for i in range(20)])
    E.guardar_config(bd, "reglas", {"si": ["otro"], "no": [], "ciudades": [], "modalidades": []}, AHORA)
    http = FakeTG()
    enviar(bd, http)
    intro = http.intros()[0]["text"]
    assert intro.startswith("Lote de hoy: 7 por lo que he aprendido de ti, 3 al azar") and "Te gusta: " in intro
    por_reglas = [d["text"] for d in http.ofertas() if "[azar]" not in d["text"]]
    assert len(por_reglas) == 7
    # "Python dev": auto si dev, python, "python dev" (+3) + ciudad (+0,5) + modalidad (+0,5) = 4,0
    assert any("Nota 4,0" in t for t in por_reglas if t.startswith("Python dev"))
    # "Otro n": manual "otro" (+1) + ciudad + modalidad = 2,0 -> la nota usa manual + aprendido
    assert any("Nota 2,0" in t for t in por_reglas if t.startswith("Otro"))


def test_manual_manda_sobre_auto_en_la_nota(bd):
    etiquetar(bd, PATRON)
    poner_ofertas(bd, [of(i, titulo="Python dev") for i in range(12)])
    E.guardar_config(bd, "reglas", {"no": ["python"], "si": [], "ciudades": [], "modalidades": []}, AHORA)
    http = FakeTG()
    enviar(bd, http)
    notas = [d["text"] for d in http.ofertas() if "Nota" in d["text"]]
    assert notas and all("-python" in t for t in notas)      # manual "no" python; el auto "si" no entra


@pytest.mark.xfail(strict=True, reason="enviar_lote: pendientes == lote se cumple tambien si la 1a oferta falla "
                   "(se borra la reserva) y la intro ya salio: al reanudar se envia otra intro")
def test_intro_no_se_repite_si_falla_la_primera_oferta(bd):
    poner_ofertas(bd, [of(i) for i in range(12)])
    http = FakeTG()
    http.fallo_en[("sendMessage", 2)] = 500          # 1 = intro, 2 = primera oferta
    with pytest.raises(RuntimeError):
        enviar(bd, http)
    http2 = FakeTG()
    enviar(bd, http2)
    assert http2.intros() == []


def test_dry_run_y_sin_token_no_imprimen_datos_personales(bd, capsys):
    etiquetar(bd, PATRON)
    poner_ofertas(bd, [of(i, titulo=f"Python secretisimo {i}") for i in range(12)])
    for dry, tok in ((True, TOKEN), (False, None)):
        http = FakeTG()
        assert E.enviar_lote(bd, "prod", tok, CHAT if tok else None, AHORA, dry, http) == 10
        out = capsys.readouterr().out
        assert out.startswith("(sin enviar) 10 ofertas:") and "términos aprendidos" in out
        for dato in ("secretisimo", "Oferta", "ACME", "python", "cocinero", "tecnoempleo", "http"):
            assert dato not in out.lower().replace("(sin enviar)", ""), dato
        assert http.calls == []
    assert cfg(bd, "reglas_auto") == "AUSENTE"


# --- varios comandos en un mensaje ---

def test_multilinea_en_orden_una_sola_respuesta(bd):
    http = FakeTG([msg(1, "/si a1x\n/no b1x\n/ver")])
    recoger(bd, http)
    assert cfg(bd, "reglas")["si"] == ["a1x"] and cfg(bd, "reglas")["no"] == ["b1x"]
    env = http.de("sendMessage")
    assert len(env) == 1
    lineas = env[0]["text"].splitlines()
    assert lineas[0] == "Añadido a si: a1x" and lineas[1] == "Añadido a no: b1x"
    assert "Sí: a1x" in env[0]["text"] and "No: b1x" in env[0]["text"]     # /ver ve el estado acumulado


def test_multilinea_ignora_lineas_sin_barra(bd):
    http = FakeTG([msg(1, "/si uno\nhola\ntexto suelto\n   /si dos  \n\n")])
    recoger(bd, http)
    assert cfg(bd, "reglas")["si"] == ["uno", "dos"]
    assert http.de("sendMessage")[0]["text"].splitlines() == ["Añadido a si: uno", "Añadido a si: dos"]


def test_multilinea_corta_a_60_comandos(bd):
    texto = "\n".join(f"/si t{i}" for i in range(75))
    http = FakeTG([msg(1, texto)])
    recoger(bd, http)
    assert len(cfg(bd, "reglas")["si"]) == E.MAX_LINEAS == 60
    assert cfg(bd, "reglas")["si"][-1] == "t59" and len(http.de("sendMessage")) == 1


def test_multilinea_idempotente_al_reprocesar(bd):
    u = [msg(1, "/si a1x\n/no b1x\n/olvidar c1x\n/lote 7")]
    recoger(bd, FakeTG(u))
    e1 = (cfg(bd, "reglas"), cfg(bd, "lote"))
    http = FakeTG(u)
    recoger(bd, http)
    assert (cfg(bd, "reglas"), cfg(bd, "lote")) == e1 == ({"si": ["a1x"], "no": ["b1x"], "ciudades": [],
                                                           "modalidades": [], "ignorar": ["c1x"]}, 7)
    assert "Ya estaba: a1x" in http.de("sendMessage")[0]["text"]


def test_multilinea_lote_y_ver_guarda_antes(bd):
    http = FakeTG([msg(1, "/si a1x\n/lote 5\n/ver")])
    recoger(bd, http)
    assert cfg(bd, "lote") == 5 and cfg(bd, "reglas")["si"] == ["a1x"]
    assert http.de("sendMessage")[0]["text"].splitlines()[1] == "Lote: 5 al día"
    assert cfg(bd, "reglas_auto") is not None


def test_multilinea_respuesta_recortada_y_solo_texto_sin_barras_no_responde(bd):
    http = FakeTG([msg(1, "solo texto\nmas texto")])
    recoger(bd, http)
    assert http.de("sendMessage") == [] and cfg(bd, "reglas") == "AUSENTE"
    http = FakeTG([msg(2, "/ver\n" * 60)])
    recoger(bd, http)
    assert len(http.de("sendMessage")[0]["text"]) <= E.MAX_TEXTO
