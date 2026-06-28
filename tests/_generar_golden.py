"""Regenerates the reference file ``golden_master.json``.

Run **on purpose** only when a behavior change is expected and reviewed (not as
part of the tests). Usage::

    python tests/_generar_golden.py

The regression tests (``test_regresion.py``) do NOT regenerate the golden: they
read it and compare, failing if the engine changed behavior without updating it.
"""
import json

from _escenarios import GOLDEN_PATH, fingerprint_all

if __name__ == "__main__":
    data = fingerprint_all()
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Golden regenerado en {GOLDEN_PATH} ({len(data)} escenarios).")
    for name, fp in data.items():
        print(f"  - {name}: {fp['kpis']['cilindros_totales']} cils, "
              f"{fp['n_snapshots']} snapshots, {fp['n_alertas']} alertas, "
              f"{fp['kpis']['rectificados_realizados']} rectificados")
