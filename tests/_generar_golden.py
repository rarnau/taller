"""Regenera el archivo de referencia ``golden_master.json``.

Ejecutar **a propósito** solo cuando un cambio de comportamiento es esperado y
revisado (no como parte de los tests). Uso::

    python tests/_generar_golden.py

Los tests de regresión (``test_regresion.py``) NO regeneran el golden: lo leen
y comparan, fallando si el motor cambió de comportamiento sin actualizarlo.
"""
import json

from _escenarios import GOLDEN_PATH, fingerprint_de_todos

if __name__ == "__main__":
    datos = fingerprint_de_todos()
    with open(GOLDEN_PATH, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    print(f"Golden regenerado en {GOLDEN_PATH} ({len(datos)} escenarios).")
    for nombre, fp in datos.items():
        print(f"  - {nombre}: {fp['kpis']['cilindros_totales']} cils, "
              f"{fp['n_snapshots']} snapshots, {fp['n_alertas']} alertas, "
              f"{fp['kpis']['rectificados_realizados']} rectificados")
