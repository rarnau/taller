"""Definición de escenarios de regresión y cálculo de su *fingerprint*.

Este módulo es la fuente de verdad compartida entre:
  - ``_generar_golden.py`` (regenera el JSON de referencia a propósito), y
  - ``test_regresion.py`` (compara la corrida actual contra ese JSON).

Un *fingerprint* es un dict 100% serializable y determinista que resume el
resultado de una simulación (KPIs, nº de snapshots, alertas, estado final de
cada cilindro y un hash del contenido completo de todos los snapshots). Si una
refactorización del motor preserva el comportamiento, todos los fingerprints
deben quedar idénticos.
"""
import hashlib
import json
import os
import sys
from datetime import datetime

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


def serializar_snapshots(taller: TallerCilindros) -> list:
    """Serialización canónica y completa de TODOS los snapshots de la corrida.

    Vuelca *todos* los campos de cada ``Snapshot`` —exactamente los datos que la
    GUI consume para el playback: conteos por estado y por SubStock, detalle de
    jaulas, CRC, máquinas, cola de rectificado y enfriando—. Usa ``__dict__``
    para que cualquier campo nuevo del Snapshot quede cubierto automáticamente.
    """
    out = []
    for sn in taller.snapshots:
        out.append({k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in sn.__dict__.items()})
    return out


def digest_snapshots(taller: TallerCilindros) -> str:
    """Hash sha256 de la serialización canónica de los snapshots.

    Es la red de seguridad de los datos que ve la GUI: cualquier cambio en
    cualquier campo de cualquier snapshot (orden incluido en las listas de
    detalle) mueve el hash. ``sort_keys`` normaliza el orden de claves de los
    dicts (la GUI accede por clave); el orden de las listas sí se preserva.
    """
    data = json.dumps(serializar_snapshots(taller), sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


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
        # Hash del contenido completo de todos los snapshots (datos de la GUI).
        "snapshots_sha256": digest_snapshots(taller),
    }


def fingerprint_de_todos() -> dict:
    """Ejecuta todos los escenarios y devuelve {nombre: fingerprint}."""
    return {nombre: fingerprint(ejecutar_escenario(esc)) for nombre, esc in ESCENARIOS.items()}
