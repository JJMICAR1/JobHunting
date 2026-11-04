"""Logica 'Elegir entorno' de salud.yml y mercado.yml ejecutando el bloque bash real (sin red)."""
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"

# (evento, evento_pipeline, rama, titulo, manual) -> entorno
CASOS_WORKFLOW_RUN = [
    ("workflow_run", "schedule", "main", "pipeline prod", "", "prod"),
    ("workflow_run", "schedule", "main", "", "", "prod"),
    ("workflow_run", "workflow_dispatch", "main", "pipeline prod", "", "prod"),
    ("workflow_run", "workflow_dispatch", "claude/otra", "pipeline prod", "", "dev"),
    ("workflow_run", "workflow_dispatch", "main", "pipeline dev", "", "dev"),
    ("workflow_run", "workflow_dispatch", "main", "pipeline dry-run", "", "dev"),
    ("workflow_run", "workflow_dispatch", "main", "", "", "dev"),
    ("workflow_run", "schedule", "claude/otra", "pipeline prod", "", "dev"),
    ("workflow_run", "push", "main", "pipeline dev", "", "dev"),
    ("workflow_run", "push", "claude/fase-6", "pipeline dev", "", "dev"),
    ("push", "", "", "", "", "dev"),
    ("workflow_dispatch", "", "", "", "dev", "dev"),
    ("workflow_dispatch", "", "", "", "prod", "prod"),
]


def bloque(wf):
    d = yaml.safe_load((WF / f"{wf}.yml").read_text(encoding="utf-8"))
    job = d["jobs"][wf]
    return next(p for p in job["steps"] if p.get("name") == "Elegir entorno")["run"]


def elegir(wf, tmp_path, evento, ev_pipe, rama, titulo, manual):
    salida = tmp_path / "salida"
    salida.write_text("")
    env = {"PATH": "/usr/bin:/bin", "EVENTO": evento, "EVENTO_PIPELINE": ev_pipe, "RAMA_PIPELINE": rama,
           "TITULO_PIPELINE": titulo, "ENTORNO_MANUAL": manual, "GITHUB_OUTPUT": str(salida)}
    r = subprocess.run(["bash", "-c", bloque(wf)], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return dict(l.split("=", 1) for l in salida.read_text().splitlines() if "=" in l)


@pytest.mark.parametrize("wf", ["mercado", "salud"])
@pytest.mark.parametrize("evento,ev_pipe,rama,titulo,manual,esperado", CASOS_WORKFLOW_RUN)
def test_entorno(wf, tmp_path, evento, ev_pipe, rama, titulo, manual, esperado):
    if wf == "mercado" and evento == "schedule":
        pytest.skip("mercado no se lanza por schedule")
    out = elegir(wf, tmp_path, evento, ev_pipe, rama, titulo, manual)
    assert out["entorno"] == esperado
    if wf == "salud":
        assert out["max_horas"] == ("28" if esperado == "prod" else "0")


def test_salud_schedule_propio_es_prod(tmp_path):
    out = elegir("salud", tmp_path, "schedule", "", "", "", "")
    assert out == {"entorno": "prod", "max_horas": "28"}


def test_mercado_y_salud_usan_la_misma_regla():
    def regla(wf):
        return next(l.strip() for l in bloque(wf).splitlines() if l.strip().startswith("workflow_run)"))
    m, s = regla("mercado"), regla("salud")
    assert m.split("; else")[0].replace("E=prod", "") == s.split("; else")[0].replace("E=prod; H=28", "")
