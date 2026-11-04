"""El workflow de mercado: permisos minimos, prod solo en main y tras cron, secretos sin imprimir."""
import re
from pathlib import Path

import pytest

RUTA = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "mercado.yml"
yaml = pytest.importorskip("yaml")
SECRETOS = ("NEO_URL_DEV", "NEO_URL_PROD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))


def job(wf):
    return wf["jobs"]["mercado"]


def paso(wf, nombre):
    return next(p for p in job(wf)["steps"] if nombre in p.get("name", ""))


def test_permisos(wf):
    assert wf["permissions"] == {"contents": "read"}
    assert job(wf)["permissions"] == {"contents": "read"}


def test_disparadores(wf):
    on = wf.get("on", wf.get(True))
    assert on["workflow_run"]["workflows"] == ["pipeline"] and on["workflow_run"]["types"] == ["completed"]
    assert "workflow_dispatch" in on
    assert on["push"]["paths"] == [".github/workflows/mercado.yml"]


def test_prod_solo_con_ref_main(wf):
    assert "github.ref == 'refs/heads/main'" in paso(wf, "(prod)")["if"]
    assert "github.ref" not in paso(wf, "(dev)")["if"]


def test_prod_solo_si_el_pipeline_vino_de_schedule(wf):
    elegir = paso(wf, "Elegir entorno")
    assert elegir["env"]["EVENTO_PIPELINE"] == "${{ github.event.workflow_run.event }}"
    run = elegir["run"]
    assert elegir["env"]["RAMA_PIPELINE"] == "${{ github.event.workflow_run.head_branch }}"
    assert elegir["env"]["TITULO_PIPELINE"] == "${{ github.event.workflow_run.display_title }}"
    # prod solo si el pipeline vino de main Y (schedule o dispatch 'pipeline prod'); si no, dev
    assert re.search(r'workflow_run\)\s*if \[ "\$RAMA_PIPELINE" = main \]', run)
    assert 'EVENTO_PIPELINE" = schedule' in run and 'TITULO_PIPELINE" = "pipeline prod"' in run
    assert re.search(r"then E=prod; else E=dev; fi", run)
    # la logica real se ejecuta en test_workflow_entorno.py
    # el resto de eventos nunca da prod por defecto
    assert re.search(r"\*\)\s*E=dev", run)
    assert "prod" in paso(wf, "(prod)")["if"] and "'prod'" not in paso(wf, "(dev)")["if"]
    assert "== 'dev'" in paso(wf, "(dev)")["if"]


def test_se_salta_si_el_pipeline_se_cancelo(wf):
    cond = job(wf)["if"]
    assert "workflow_run.conclusion != 'cancelled'" in cond
    assert "github.event_name != 'workflow_run'" in cond


def test_secretos_por_entorno(wf):
    prod, dev = paso(wf, "(prod)"), paso(wf, "(dev)")
    assert prod["env"]["DATABASE_URL"] == "${{ secrets.NEO_URL_PROD }}"
    assert dev["env"]["DATABASE_URL"] == "${{ secrets.NEO_URL_DEV }}"
    for p in (prod, dev):
        assert p["env"]["TELEGRAM_BOT_TOKEN"] == "${{ secrets.TELEGRAM_BOT_TOKEN }}"
        assert p["env"]["TELEGRAM_CHAT_ID"] == "${{ secrets.TELEGRAM_CHAT_ID }}"
    assert "NEO_URL_DEV" not in str(prod) and "NEO_URL_PROD" not in str(dev)
    assert "--entorno prod" in prod["run"] and "--entorno dev" in dev["run"]


def test_secretos_solo_en_los_pasos_de_mercado(wf):
    for p in job(wf)["steps"]:
        if "(prod)" not in p.get("name", "") and "(dev)" not in p.get("name", ""):
            assert "secrets." not in str(p)


def test_ningun_run_imprime_secretos(wf):
    for p in job(wf)["steps"]:
        run = p.get("run", "")
        assert "secrets." not in run
        for linea in run.splitlines():
            if re.search(r"\b(echo|printf|cat|env|set -x)\b", linea):
                # citar el NOMBRE del secreto en un mensaje es valido; expandir su valor no.
                sin_test = re.sub(r'\[ -z "\$\w+" \]', "", linea)
                assert "${{" not in linea, linea
                assert not re.search(r"\$\{?(DATABASE_URL|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)\b", sin_test), linea
    assert "set -x" not in RUTA.read_text(encoding="utf-8")


def test_timeout_y_sin_continue_on_error(wf):
    assert 0 < job(wf)["timeout-minutes"] <= 10
    assert not any(p.get("continue-on-error") for p in job(wf)["steps"])


def test_concurrencia_sin_cancelar(wf):
    assert wf["concurrency"]["cancel-in-progress"] is False
