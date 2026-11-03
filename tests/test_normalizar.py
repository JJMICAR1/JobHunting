import re

import pytest

from jobhunting.normalizar import huella, separar_ubicacion


@pytest.mark.parametrize("texto,esperado", [
    ("Barcelona", ("Barcelona", None)),
    ("Barcelona (Híbrido)", ("Barcelona", "hibrido")),
    ("BARCELONA (Presencial)", ("Barcelona", "presencial")),
    ("Madrid (Híbrido)", ("Madrid", "hibrido")),
    ("Girona (Teletrabajo)", ("Girona", "remoto")),
    ("100% remoto", (None, "remoto")),
    ("España", (None, None)),
    ("EspaÑa y otras", (None, None)),
    (None, (None, None)),
    ("", (None, None)),
    ("l'hospitalet de llobregat (Presencial)", ("L'Hospitalet de Llobregat", "presencial")),
    ("Santa Cruz de Tenerife", ("Santa Cruz de Tenerife", None)),
])
def test_separar_ubicacion(texto, esperado):
    assert separar_ubicacion(texto) == esperado


@pytest.mark.parametrize("ciudad", ["Barcelona", "madrid", "L'Hospitalet de Llobregat"])
def test_misma_ciudad_con_cualquier_modalidad(ciudad):
    base = separar_ubicacion(ciudad)[0]
    for mod, esp in [("Presencial", "presencial"), ("Híbrido", "hibrido"), ("Teletrabajo", "remoto")]:
        c, m = separar_ubicacion(f"{ciudad.upper()} ({mod})")
        assert (c, m) == (base, esp)


def test_huella_formato():
    assert re.fullmatch(r"[0-9a-f]{16}", huella("ACME", "Dev", "Barcelona"))


def test_huella_invariante_a_tildes_mayusculas_espacios_genero():
    a = huella("Mytic Innova", "Programador/a Java", "Barcelona")
    assert a == huella("  MYTIC   innova ", "Programador Java", "BARCELONA")
    assert a == huella("Mýtic Innova", "Prógramador/a  JAVA", "Bárcelona")


def test_huella_distinta_si_cambia_empresa_o_ciudad():
    b = huella("ACME", "Dev", "Barcelona")
    assert b != huella("OTRA", "Dev", "Barcelona")
    assert b != huella("ACME", "Dev", "Madrid")
    assert b != huella("ACME", "Dev Senior", "Barcelona")


def test_huella_tolera_none():
    h = huella(None, None, None)
    assert re.fullmatch(r"[0-9a-f]{16}", h)
    assert huella("ACME", "Dev", None) != huella("ACME", "Dev", "Barcelona")
    assert huella(None, "Dev", "Barcelona") == huella("", "Dev", "Barcelona")
