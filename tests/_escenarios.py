"""Definición de escenarios de regresión y cálculo de su *fingerprint*.

Este módulo es la fuente de verdad compartida entre:
  - ``_generar_golden.py`` (regenera el JSON de referencia a propósito), y
  - ``test_regresion.py`` (compara la corrida actual contra ese JSON).

Un *fingerprint* es un dict 100% serializable y determinista que resume el
resultado de una simulación (KPIs, nº de snapshots, alertas y estado final de
cada cilindro). Si una refactorización del motor preserva el comportamiento,
todos los fingerprints deben quedar idénticos.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.persistencia import cargar_config
from modelos.kpis import calcular_kpis
from modelos.taller import TallerCilindros

_DIR_DATOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datos")
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden_master.json")

# Cada escenario: nombre -> {excel, estrategia, tiempo_enfriado}
ESCENARIOS = {
    "parada_mayor_diametro": {
        "excel": "simulacion_caso_parada.xlsx", "estrategia": "mayor_diametro", "tiempo_enfriado": 0.0,
    },
    "parada_fifo": {
        "excel": "simulacion_caso_parada.xlsx", "estrategia": "fifo", "tiempo_enfriado": 0.0,
    },
    "parada_enfriado_8h": {
        "excel": "simulacion_caso_parada.xlsx", "estrategia": "mayor_diametro", "tiempo_enfriado": 8.0,
    },
    "cils140_mayor_diametro": {
        "excel": "simulacion_140cils_1semana.xlsx", "estrategia": "mayor_diametro", "tiempo_enfriado": 0.0,
    },
    "cils140_menor_mm_desb": {
        "excel": "simulacion_140cils_1semana.xlsx", "estrategia": "menor_mm_desb_fifo_prod", "tiempo_enfriado": 0.0,
    },
}


def ejecutar_escenario(esc: dict) -> TallerCilindros:
    """Construye y simula un taller para un escenario dado (sin GUI ni I/O extra)."""
    cfg = cargar_config()
    cfg["tiempo_enfriado_h"] = esc["tiempo_enfriado"]
    taller = TallerCilindros()
    taller.configurar(cfg)
    taller.cargar_datos(os.path.join(_DIR_DATOS, esc["excel"]))
    taller.simular(estrategia=esc["estrategia"], callback_log=None)
    return taller


def fingerprint(taller: TallerCilindros) -> dict:
    """Resumen determinista y serializable del resultado de una simulación."""
    k = calcular_kpis(taller)
    return {
        "kpis": {
            "cilindros_totales": k["cilindros_totales"],
            "activos": k["activos"],
            "bajas": k["bajas"],
            "alertas_criticas": k["alertas_criticas"],
            "cambios_programados": k["cambios_programados"],
            "rectificados_realizados": k["rectificados_realizados"],
            "horizonte_simulacion_h": round(k["horizonte_simulacion_h"], 4),
            "diametro_promedio_mm": round(k["diametro_promedio_mm"], 4),
            "desgaste_medio_mm": round(k["desgaste_medio_mm"], 4),
            "utilizacion_maquinas_pct": {
                m: round(v, 4) for m, v in k["utilizacion_maquinas_pct"].items()
            },
        },
        "n_snapshots": len(taller.snapshots),
        "n_alertas": len(taller.alertas),
        "alertas": [
            {"tiempo": a.tiempo.isoformat(), "tipo": a.tipo, "mensaje": a.mensaje, "jaula": a.jaula}
            for a in taller.alertas
        ],
        "cilindros": sorted(
            [c.id, c.estado.value, round(c.diametro, 2)] for c in taller.cilindros.values()
        ),
    }


def fingerprint_de_todos() -> dict:
    """Ejecuta todos los escenarios y devuelve {nombre: fingerprint}."""
    return {nombre: fingerprint(ejecutar_escenario(esc)) for nombre, esc in ESCENARIOS.items()}
