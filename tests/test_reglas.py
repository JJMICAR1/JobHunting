"""Fase 7: reglas de puntuacion y comandos (puro, sin BD ni red)."""
import pytest

from jobhunting import reglas as R
from jobhunting.reglas import Reglas, aplicar_comando, normalizar, puntuar


def cmd(r, texto, prog=None):
    return aplicar_comando(r, texto, prog)


# --- normalizacion ---

def test_normalizar_tildes_y_mayusculas():
    assert normalizar("  Ingeniero/a de Datos – BARCELONA ") == "ingeniero a de datos barcelona"
    assert normalizar("Gestión Pública") == "gestion publica"
    assert normalizar(None) == "" and normalizar("") == ""


def test_normalizar_conserva_mas_y_almohadilla():
    assert normalizar("C++") == "c++" and normalizar("C#") == "c#"


def test_palabra_completa_no_subcadena():
    r = Reglas(si=("java",))
    assert puntuar("Java Developer", None, None, None, r)[0] == 1.0
    assert puntuar("JavaScript Developer", None, None, None, r)[0] == 0.0
    assert puntuar("Desarrollador Javascript", None, None, None, r)[0] == 0.0


def test_c_mas_mas_no_casa_con_c():
    assert puntuar("Dev C++ senior", None, None, None, Reglas(si=("c++",)))[0] == 1.0
    assert puntuar("Dev C senior", None, None, None, Reglas(si=("c++",)))[0] == 0.0
    assert puntuar("Dev C++ senior", None, None, None, Reglas(si=("c",)))[0] == 0.0


def test_frase_y_tildes():
    r = Reglas(si=("machine learning",))
    assert puntuar("Ingeniero de Machine-Learning", None, None, None, r)[0] == 1.0
    assert puntuar("Machine y Learning", None, None, None, r)[0] == 0.0
    assert puntuar("Analista de Gestión", None, None, None, Reglas(si=("gestion",)))[0] == 1.0


# --- puntuacion ---

def test_puntuacion_basica_y_motivos():
    r = Reglas(si=("python", "sql"), no=("becario",), ciudades=("barcelona",), modalidades=("remoto",))
    nota, motivos = puntuar("Python y SQL dev", "ACME", "Barcelona", "remoto", r)
    assert nota == 3.0 and motivos == ["python", "sql", "Barcelona", "remoto"]


def test_no_resta_3_en_titulo_o_empresa_una_sola_vez():
    r = Reglas(no=("becario",))
    assert puntuar("Becario python", "X", None, None, r)[0] == -3.0
    assert puntuar("Dev", "Becario SL", None, None, r)[0] == -3.0
    assert puntuar("Becario", "Becario SL", None, None, r)[0] == -3.0


def test_si_solo_mira_el_titulo():
    assert puntuar("Dev", "Python SL", None, None, Reglas(si=("python",)))[0] == 0.0


def test_listas_vacias_no_suman():
    r = Reglas()
    assert puntuar("Python", "X", "Barcelona", "remoto", r) == (0.0, [])
    assert r.vacia()
    # ciudades/modalidades vacias: no suman aunque la oferta tenga datos
    assert puntuar("x", "y", "Barcelona", "remoto", Reglas(si=("zzz",)))[0] == 0.0


def test_ciudad_y_modalidad_media_cada_una_y_no_casan_otras():
    r = Reglas(ciudades=("barcelona",), modalidades=("hibrido",))
    assert puntuar("x", "y", "Barcelona", "hibrido", r)[0] == 1.0
    assert puntuar("x", "y", "Madrid", "remoto", r)[0] == 0.0
    assert puntuar("x", "y", "Barcelona", None, r)[0] == 0.5
    assert puntuar("x", "y", None, "hibrido", r)[0] == 0.5
    assert puntuar("x", "y", "BARCELONA", "Híbrido", r)[0] == 1.0


# --- comandos ---

def test_si_no_ciudad_modalidad():
    r = Reglas()
    r, m = cmd(r, "/si Python")
    assert r.si == ("python",) and "python" in m
    r, _ = cmd(r, "/no Becario")
    r, _ = cmd(r, "/ciudad Sabadell")
    r, _ = cmd(r, "/modalidad Híbrido")
    assert (r.no, r.ciudades, r.modalidades) == (("becario",), ("sabadell",), ("hibrido",))


def test_comandos_idempotentes():
    r, _ = cmd(Reglas(), "/si python")
    r2, m = cmd(r, "/si  PYTHON ")
    assert r2 == r and m.startswith("Ya estaba")
    r3, _ = cmd(r, "/modalidad remoto")
    assert cmd(r3, "/modalidad remoto")[0] == r3
    q, _ = cmd(r, "/quitar python")
    assert cmd(q, "/quitar python") == (q, "No estaba: python")


def test_si_y_no_son_excluyentes_gana_el_ultimo():
    r, _ = cmd(Reglas(), "/si python")
    r, _ = cmd(r, "/no python")
    assert r.si == () and r.no == ("python",)
    r, _ = cmd(r, "/si python")
    assert r.si == ("python",) and r.no == ()


def test_quitar_de_todas_las_listas():
    r = Reglas(si=("a",), no=("b",), ciudades=("c",), modalidades=("remoto",))
    for t in ("a", "b", "c", "remoto"):
        r, m = cmd(r, f"/quitar {t}")
        assert m == f"Quitado: {t}"
    assert r.vacia()


def test_ver_con_progreso_y_ayuda():
    r = Reglas(si=("python",))
    _, m = cmd(r, "/ver", {"total": 12, "si": 5, "no": 7, "meta": 100, "lote": 10})
    assert "Sí: python" in m and "12/100" in m and "Sí 5" in m and "No 7" in m and "Lote: 10" in m
    assert "No: (vacío)" in m
    assert cmd(r, "/ver")[1].count("0/100") == 1
    for c in ("/ayuda", "/start", "/help"):
        assert cmd(r, c) == (r, R.AYUDA)


def test_lote():
    assert R.parsear_lote("/lote 15") == 15
    assert R.parsear_lote("/lote 1") == 1 and R.parsear_lote("/lote 30") == 30
    for malo in ("/lote 0", "/lote 31", "/lote -3", "/lote x", "/lote", "/lote 2.5"):
        assert isinstance(R.parsear_lote(malo), str)
    assert R.parsear_lote("/si x") is None
    r = Reglas(si=("a",))
    assert cmd(r, "/lote 5") == (r, "Lote: 5 al día")
    assert cmd(r, "/lote 99")[0] == r


def test_comando_con_bot_y_mayusculas():
    assert cmd(Reglas(), "/SI@MiBot python")[0].si == ("python",)


@pytest.mark.parametrize("texto", ["/si", "/si   ", "/si !!!", "/no", "/ciudad", "/quitar", "/quitar ..."])
def test_comandos_sin_argumento_usan_uso(texto):
    r = Reglas(si=("a",))
    nuevas, m = cmd(r, texto)
    assert nuevas == r and m.startswith("Uso")


@pytest.mark.parametrize("texto", ["/modalidad", "/modalidad lunar", "/modalidad remoto hibrido"])
def test_modalidad_invalida(texto):
    nuevas, m = cmd(Reglas(), texto)
    assert nuevas.vacia() and m.startswith("Uso: /modalidad")


@pytest.mark.parametrize("texto", ["/foo", "/", "hola", "", "   "])
def test_comando_desconocido(texto):
    r = Reglas(si=("a",))
    nuevas, m = cmd(r, texto)
    assert nuevas == r and "no reconocido" in m


# --- limites ---

def test_limite_60_caracteres():
    ok = "a" * 60
    r, _ = cmd(Reglas(), f"/si {ok}")
    assert r.si == (ok,)
    r2, m = cmd(Reglas(), f"/si {'a' * 61}")
    assert r2.vacia() and "demasiado largo" in m


def test_limite_200_terminos():
    r = Reglas()
    for i in range(200):
        r, _ = cmd(r, f"/si t{i}")
    assert len(r.si) == 200
    r2, m = cmd(r, "/si otro")
    assert r2 == r and "llena" in m
    assert cmd(r, "/si t3")[1].startswith("Ya estaba")
    # /no no esta afectada por /si llena
    assert len(cmd(r, "/no otro")[0].no) == 1


def test_desde_dict_valida():
    assert Reglas.desde_dict(None) == Reglas()
    assert Reglas.desde_dict({"si": ["Python", "python", "SQL"]}).si == ("python", "sql")
    assert Reglas.desde_dict(Reglas(si=("a",)).a_dict()) == Reglas(si=("a",))
    for malo in ([], {"x": []}, {"si": "a"}, {"si": [1]}, {"si": ["!!!"]}, {"si": ["a" * 61]},
                 {"modalidades": ["lunar"]}, {"si": [f"t{i}" for i in range(201)]}):
        with pytest.raises(ValueError):
            Reglas.desde_dict(malo)
