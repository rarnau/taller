"""Tests de regresión *golden-master* del motor de simulación.

Cada escenario se ejecuta y su fingerprint se compara contra el de referencia
en ``golden_master.json``. Si una refactorización del motor cambia cualquier
resultado observable (KPIs, snapshots, alertas, estado final de cilindros), el
test falla — esa es la red de seguridad para refactorizar ``models/workshop.py``
sin alterar el comportamiento.

Si un cambio de comportamiento es *esperado*, regenerar el golden a propósito::

    python tests/_generar_golden.py
"""
import json

import pytest

from _escenarios import SCENARIOS, GOLDEN_PATH, run_scenario, fingerprint

with open(GOLDEN_PATH, "r", encoding="utf-8") as _f:
    _GOLDEN = json.load(_f)


@pytest.fixture(scope="module")
def golden():
    return _GOLDEN


@pytest.mark.parametrize("nombre", list(SCENARIOS.keys()))
def test_fingerprint_coincide_con_golden(nombre, golden):
    """El resultado completo del escenario es idéntico al de referencia."""
    assert nombre in golden, f"Escenario '{nombre}' no está en el golden; regenéralo."
    actual = fingerprint(run_scenario(SCENARIOS[nombre]))
    esperado = golden[nombre]

    # Comparaciones por sección para que el fallo sea legible (no un diff gigante).
    assert actual["kpis"] == esperado["kpis"], f"{nombre}: KPIs divergen"
    assert actual["n_snapshots"] == esperado["n_snapshots"], f"{nombre}: nº de snapshots divergen"
    assert actual["n_alertas"] == esperado["n_alertas"], f"{nombre}: nº de alertas divergen"
    assert actual["alertas"] == esperado["alertas"], f"{nombre}: alertas divergen"
    assert actual["cilindros"] == esperado["cilindros"], f"{nombre}: estado final de cilindros diverge"
    # Contenido completo de los snapshots = datos que consume la GUI para el
    # playback. Si este hash diverge pero todo lo demás coincide, cambió algún
    # campo interno de los snapshots (detalle_*, conteo_por_substock, ...); si
    # es intencional, regenerar el golden con tests/_generar_golden.py.
    assert actual["snapshots_sha256"] == esperado["snapshots_sha256"], (
        f"{nombre}: el contenido de los snapshots (datos que consume la GUI) diverge")


def test_golden_cubre_todos_los_escenarios(golden):
    """El golden no quedó desincronizado de la lista de escenarios."""
    assert set(golden.keys()) == set(SCENARIOS.keys())
