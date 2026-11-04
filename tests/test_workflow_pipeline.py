"""El workflow del pipeline: crons de respaldo, prod solo desde main, --solo-si-falta solo en schedule."""
import re
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "pipeline.yml"
yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))


def on(wf):
    return wf.get("on", wf.get(True))


def paso(wf, nombre):
    return next(p for p in wf["jobs"]["pipeline"]["steps"] if nombre in p.get("name", ""))


def test_cuatro_crons(wf):
    crons = [c["cron"] for c in on(wf)["schedule"]]
    assert crons == ["17 5 * * *", "47 6 * * *", "23 9 * * *", "53 12 * * *"]


def test_dispatch_admite_prod(wf):
    ent = on(wf)["workflow_dispatch"]["inputs"]["entorno"]
    assert ent["options"] == ["dev", "dry-run", "prod"]
    assert ent["default"] == "dev"


def test_paso_prod_condicion(wf):
    cond = paso(wf, "(prod)")["if"]
    assert "github.event_name == 'schedule'" in cond
    assert "github.event_name == 'workflow_dispatch'" in cond and "inputs.entorno == 'prod'" in cond
    # dev y dry-run nunca corren en prod
    assert "prod" not in paso(wf, "(dev)")["if"]
    assert "prod" not in paso(wf, "(dry-run)")["if"]
    assert "schedule" not in paso(wf, "(dev)")["if"] and "schedule" not in paso(wf, "(dry-run)")["if"]


def test_prod_exige_main_y_falla_con_error(wf):
    p = paso(wf, "(prod)")
    run = p["run"]
    assert p["env"]["REF"] == "${{ github.ref }}"
    lineas = run.splitlines()
    i_ref = next(i for i, l in enumerate(lineas) if "refs/heads/main" in l)
    i_py = next(i for i, l in enumerate(lineas) if "python -m jobhunting.pipeline" in l)
    assert i_ref < i_py
    assert '"$REF" != "refs/heads/main"' in lineas[i_ref]
    assert "::error::" in lineas[i_ref] and "exit 1" in lineas[i_ref]


def test_prod_usa_secreto_prod_y_todos(wf):
    p = paso(wf, "(prod)")
    assert p["env"]["DATABASE_URL"] == "${{ secrets.NEO_URL_PROD }}"
    assert p["env"]["PORTAL"] == "todos"
    assert "NEO_URL_DEV" not in str(p)
    assert "NEO_URL_PROD" not in str(paso(wf, "(dev)")) and "NEO_URL_PROD" not in str(paso(wf, "(dry-run)"))


def test_solo_si_falta_solo_en_schedule(wf):
    p = paso(wf, "(prod)")
    assert p["env"]["EVENTO"] == "${{ github.event_name }}"
    assert re.search(r'if \[ "\$EVENTO" = schedule \]; then EXTRA="--solo-si-falta"; fi', p["run"])
    assert "--solo-si-falta" not in p["run"].replace('EXTRA="--solo-si-falta"', "")
    assert "solo-si-falta" not in paso(wf, "(dev)")["run"] and "solo-si-falta" not in paso(wf, "(dry-run)")["run"]


def test_run_name(wf):
    rn = wf["run-name"]
    assert rn.startswith("pipeline ${{") and "github.event_name == 'schedule' && 'prod'" in rn
    assert "inputs.entorno" in rn and rn.rstrip("}} ").endswith("'dev'")
    # el dispatch dev/dry-run/prod da 'pipeline <entorno>': el titulo que usan salud y mercado
    assert "pipeline prod" in " ".join(
        p["run"] for w in ("salud", "mercado")
        for p in yaml.safe_load((RUTA.parent / f"{w}.yml").read_text())["jobs"][w]["steps"] if "run" in p)


def test_concurrencia_separa_entornos(wf):
    g = wf["concurrency"]
    assert g["cancel-in-progress"] is False
    assert g["group"] == "pipeline-${{ github.event_name == 'schedule' && 'prod' || inputs.entorno || 'dev' }}"


def test_permisos_minimos(wf):
    assert wf["permissions"] == {"contents": "read"}
