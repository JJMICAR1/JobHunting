"""Contrato de .github/workflows/cronjob.yml: solo manual o al cambiar sus ficheros, sin schedule."""
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "cronjob.yml"
yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))


def test_disparadores(wf):
    on = wf.get("on", wf.get(True))
    assert set(on) == {"workflow_dispatch", "push"} and "schedule" not in on
    assert on["push"]["branches"] == ["claude/**"]
    assert on["push"]["paths"] == [".github/workflows/cronjob.yml", "scripts/configurar_cronjob.py"]


def test_permisos_y_concurrency(wf):
    assert wf["permissions"] == {"contents": "read"}
    assert wf["jobs"]["configurar"]["permissions"] == {"contents": "read"}
    assert wf["concurrency"] == {"group": "cronjob", "cancel-in-progress": False}


def test_secretos_solo_en_el_paso_del_script(wf):
    pasos = wf["jobs"]["configurar"]["steps"]
    p = next(x for x in pasos if "scripts/configurar_cronjob.py" in x.get("run", ""))
    assert p["env"] == {"CRONJOB_API_KEY": "${{ secrets.CRONJOB_API_KEY }}",
                        "GH_DISPATCH_TOKEN": "${{ secrets.GH_DISPATCH_TOKEN }}"}
    assert p["run"].strip() == "python scripts/configurar_cronjob.py"
    for otro in pasos:
        if otro is not p:
            assert "secrets." not in str(otro)
    assert "secrets." not in str({k: v for k, v in wf.items() if k != "jobs"})


def test_no_hay_pull_request_target(wf):
    assert "pull_request_target" not in wf.get("on", wf.get(True))
