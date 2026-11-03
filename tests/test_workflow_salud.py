"""El workflow de salud: permisos mínimos, secretos por entorno y latido solo en cron."""
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "salud.yml"
yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))


def paso(wf, nombre):
    return next(p for p in wf["jobs"]["salud"]["steps"] if nombre in p.get("name", ""))


def test_permisos(wf):
    assert wf["permissions"] == {"contents": "read"}
    assert wf["jobs"]["salud"]["permissions"] == {"contents": "read", "issues": "write"}
    assert wf["jobs"]["latido"]["permissions"] == {"actions": "write"}


def test_prod_solo_desde_main(wf):
    assert "github.ref == 'refs/heads/main'" in paso(wf, "(prod)")["if"]
    assert "github.ref" not in paso(wf, "(dev)")["if"]


def test_secretos_por_entorno(wf):
    prod, dev = paso(wf, "(prod)"), paso(wf, "(dev)")
    assert prod["env"]["DATABASE_URL"] == "${{ secrets.NEO_URL_PROD }}"
    assert dev["env"]["DATABASE_URL"] == "${{ secrets.NEO_URL_DEV }}"
    assert "NEO_URL_DEV" not in prod["run"] and "NEO_URL_PROD" not in dev["run"]
    assert "--entorno prod" in prod["run"] and "--entorno dev" in dev["run"]
    assert "prod" in prod["if"] and "dev" in dev["if"]


def test_latido_job_aparte_solo_en_schedule(wf):
    assert wf["jobs"]["latido"]["if"] == "github.event_name == 'schedule'"
    assert not any("Latido" in p.get("name", "") or "enable" in p.get("run", "")
                   for p in wf["jobs"]["salud"]["steps"])
    assert any("enable" in p.get("run", "") for p in wf["jobs"]["latido"]["steps"])
    assert "needs" not in wf["jobs"]["latido"]


def test_ningun_otro_paso_usa_secretos_de_bd(wf):
    for p in wf["jobs"]["salud"]["steps"]:
        if "(prod)" not in p.get("name", "") and "(dev)" not in p.get("name", ""):
            assert "NEO_URL" not in str(p)


def test_no_hay_pull_request_target(wf):
    on = wf.get("on", wf.get(True))
    assert "pull_request_target" not in on and "schedule" in on
