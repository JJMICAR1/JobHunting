"""El workflow de etiquetado: cron, prod solo desde main, permisos minimos, secretos y latido."""
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
RUTA = RAIZ / ".github" / "workflows" / "etiquetado.yml"
yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))


def job(wf):
    return wf["jobs"]["etiquetado"]


def paso(wf, nombre):
    return next(p for p in job(wf)["steps"] if nombre in p.get("name", ""))


def test_disparadores(wf):
    on = wf.get("on", wf.get(True))
    assert on["schedule"] == [{"cron": "37 * * * *"}]
    assert "workflow_dispatch" in on
    assert on["workflow_dispatch"]["inputs"]["entorno"]["options"] == ["dev", "prod"]
    assert on["workflow_dispatch"]["inputs"]["entorno"]["default"] == "dev"
    assert on["push"]["paths"] == [".github/workflows/etiquetado.yml"]
    assert "pull_request_target" not in on


def test_permisos_y_timeout(wf):
    assert wf["permissions"] == {"contents": "read"}
    assert job(wf)["permissions"] == {"contents": "read"}
    assert job(wf)["timeout-minutes"] == 5


def test_concurrency_por_entorno_sin_cancelar(wf):
    c = wf["concurrency"]
    assert c["cancel-in-progress"] is False
    g = c["group"]
    assert g.startswith("etiquetado-") and "schedule" in g and "'prod'" in g and "inputs.entorno" in g


def test_prod_solo_con_ref_main_y_dev_sin_ref(wf):
    assert "github.ref == 'refs/heads/main'" in paso(wf, "(prod)")["if"]
    assert "== 'prod'" in paso(wf, "(prod)")["if"]
    assert "github.ref" not in paso(wf, "(dev)")["if"] and "== 'dev'" in paso(wf, "(dev)")["if"]


def test_cron_es_prod_y_lo_demas_dev(wf):
    run = paso(wf, "Elegir entorno")["run"]
    assert "schedule) E=prod" in run and "workflow_dispatch) E=\"$ENTORNO_MANUAL\"" in run and "*) E=dev" in run
    assert paso(wf, "Elegir entorno")["env"]["EVENTO"] == "${{ github.event_name }}"


def test_secretos_por_entorno(wf):
    prod, dev = paso(wf, "(prod)"), paso(wf, "(dev)")
    assert prod["env"]["DATABASE_URL"] == "${{ secrets.NEO_URL_PROD }}"
    assert dev["env"]["DATABASE_URL"] == "${{ secrets.NEO_URL_DEV }}"
    for p in (prod, dev):
        assert p["env"]["TELEGRAM_BOT_TOKEN"] == "${{ secrets.TELEGRAM_BOT_TOKEN }}"
        assert p["env"]["TELEGRAM_CHAT_ID"] == "${{ secrets.TELEGRAM_CHAT_ID }}"
    assert "NEO_URL_DEV" not in str(prod) and "NEO_URL_PROD" not in str(dev)
    assert "--entorno prod" in prod["run"] and "--entorno dev" in dev["run"]


def test_secretos_solo_en_los_pasos_del_bot(wf):
    for p in job(wf)["steps"]:
        if "(prod)" not in p.get("name", "") and "(dev)" not in p.get("name", ""):
            assert "secrets." not in str(p)


def test_no_imprime_secretos(wf):
    for p in job(wf)["steps"]:
        for linea in p.get("run", "").splitlines():
            if linea.strip().startswith("echo"):
                assert "$DATABASE_URL" not in linea and "TOKEN" not in linea and "CHAT_ID" not in linea


def test_esta_en_el_latido():
    salud = yaml.safe_load((RAIZ / ".github" / "workflows" / "salud.yml").read_text(encoding="utf-8"))
    runs = " ".join(p.get("run", "") for p in salud["jobs"]["latido"]["steps"])
    assert "etiquetado.yml" in runs and "pipeline.yml" in runs and "salud.yml" in runs
