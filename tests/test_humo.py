"""Test de humo de la Fase 1: comprueba que los subagentes existen con permisos mínimos."""
from pathlib import Path

AGENTES = Path(__file__).resolve().parent.parent / ".claude" / "agents"
ESPERADOS = {"scraper-dev", "tester", "db-engineer", "ml-engineer", "devops", "reviewer"}


def leer_cabecera(ruta: Path) -> dict:
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert lineas[0] == "---", f"{ruta.name}: falta la cabecera"
    fin = lineas.index("---", 1)
    campos = {}
    for linea in lineas[1:fin]:
        clave, _, valor = linea.partition(":")
        campos[clave.strip()] = valor.strip()
    return campos


def test_estan_todos_los_agentes():
    assert {p.stem for p in AGENTES.glob("*.md")} == ESPERADOS


def test_cabeceras_validas():
    for ruta in AGENTES.glob("*.md"):
        c = leer_cabecera(ruta)
        assert c["name"] == ruta.stem
        assert c["description"]
        assert c["model"] == "sonnet"
        assert "Agent" not in c["tools"], "los subagentes no crean subagentes"


def test_reviewer_solo_lectura():
    tools = {t.strip() for t in leer_cabecera(AGENTES / "reviewer.md")["tools"].split(",")}
    assert tools == {"Read", "Grep", "Glob", "Bash"}
