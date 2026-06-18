"""Cálculo de KPIs de una simulación ya ejecutada (sin dependencias de GUI)."""
from typing import Any, Dict

import numpy as np

from modelos.enums import EstadoCilindro


def calcular_kpis(taller) -> Dict[str, Any]:
    """Devuelve los KPIs de una simulación ya ejecutada.

    Única fuente de verdad para las métricas: la GUI (tab KPIs) y el CLI la
    consumen por igual para no divergir.
    """
    total = len(taller.cilindros)
    activos = len([c for c in taller.cilindros.values() if c.estado != EstadoCilindro.BAJA])
    bajas = total - activos
    alertas_criticas = sum(1 for a in taller.alertas if a.tipo == "CRITICO")
    rectificados = sum(len(mq.historial_trabajo) for mq in taller.maquinas.values())

    horizonte_h = 0.0
    if taller.snapshots:
        horizonte_h = (taller.snapshots[-1].tiempo - taller.snapshots[0].tiempo).total_seconds() / 3600

    diam_prom = (
        float(np.mean([c.diametro for c in taller.cilindros.values() if c.estado != EstadoCilindro.BAJA]))
        if activos else 0.0
    )
    desgastes = [
        c.diametro_original - c.diametro
        for c in taller.cilindros.values()
        if c.diametro_original != c.diametro
    ]
    desgaste_medio = float(np.mean(desgastes)) if desgastes else 0.0

    # Dos utilizaciones por máquina (coinciden en 24/7, donde operativo == calendario):
    #   - disponible: tiempo ocupada / tiempo operativo (horas en turno, "disponibles")
    #   - neta:       tiempo ocupada / tiempo calendario total
    # Como tiempo operativo <= calendario, siempre neta <= disponible (su tope).
    t0 = taller.snapshots[0].tiempo if taller.snapshots else None
    t1 = taller.snapshots[-1].tiempo if taller.snapshots else None
    utilizacion_maquinas: Dict[str, float] = {}
    utilizacion_neta: Dict[str, float] = {}
    for nombre, mq in taller.maquinas.items():
        op_min = mq.minutos_operativos_entre(t0, t1) if t0 is not None else 0.0
        disp = (mq.tiempo_total_ocupada_min / op_min * 100) if op_min > 0 else 0.0
        neta = (mq.tiempo_total_ocupada_min / 60) / horizonte_h * 100 if horizonte_h else 0.0
        utilizacion_maquinas[nombre] = disp
        utilizacion_neta[nombre] = neta

    return {
        "cilindros_totales": total,
        "activos": activos,
        "bajas": bajas,
        "alertas_criticas": alertas_criticas,
        "cambios_programados": len(taller.eventos_programados),
        "rectificados_realizados": rectificados,
        "horizonte_simulacion_h": horizonte_h,
        "diametro_promedio_mm": diam_prom,
        "desgaste_medio_mm": desgaste_medio,
        "utilizacion_maquinas_pct": utilizacion_maquinas,
        "utilizacion_neta_pct": utilizacion_neta,
    }
