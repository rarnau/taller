"""Regenera el archivo de referencia ``golden_master.json``.

Ejecutar **a propósito** solo cuando un cambio de comportamiento es esperado y
revisado (no como parte de los tests). Uso::

    python tests/_generar_golden.py

Los tests de regresión (``test_regresion.py``) NO regeneran el golden: lo leen
y comparan, fallando si el motor cambió de comportamiento sin actualizarlo.

IMPORTANTE: el golden debe regenerarse SIEMPRE con la config DEFAULT prístina,
nunca con un ``config/user_config.json`` personalizado (turnos, tasa_falla,
tiempo_enfriado_h, ...). La suite se aísla sola (fixture autouse en
``conftest.py``), y este script fuerza lo mismo abajo apuntando
``persistencia.CONFIG_PATH`` a una ruta inexistente, con lo que
``cargar_config()`` devuelve ``DEFAULTS``.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config.persistencia as persistencia

# Forzar la config default prístina: con CONFIG_PATH inexistente,
# cargar_config() (usada por _escenarios) devuelve una copia de DEFAULTS.
persistencia.CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_no_existe_user_config.json")

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
