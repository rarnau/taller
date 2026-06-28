"""KPI computation for an already-run simulation (no GUI dependencies)."""
from typing import Any, Dict

import numpy as np

from models.enums import CylinderState


def compute_kpis(workshop) -> Dict[str, Any]:
    """Return the KPIs of an already-run simulation.

    Single source of truth for the metrics: the GUI (KPIs tab) and the CLI both
    consume it so they cannot diverge.

    Note: the returned dict keys stay in Spanish on purpose (consumed by key
    across GUI/CLI/tests and embedded in the regression golden master).
    """
    total = len(workshop.cylinders)
    active = len([c for c in workshop.cylinders.values() if c.state != CylinderState.SCRAPPED])
    scrapped = total - active
    critical_alerts = sum(1 for a in workshop.alerts if a.type == "CRITICO")
    grinds = sum(len(mq.work_history) for mq in workshop.machines.values())

    horizon_h = 0.0
    if workshop.snapshots:
        horizon_h = (workshop.snapshots[-1].tiempo - workshop.snapshots[0].tiempo).total_seconds() / 3600

    avg_diam = (
        float(np.mean([c.diameter for c in workshop.cylinders.values() if c.state != CylinderState.SCRAPPED]))
        if active else 0.0
    )
    wear_values = [
        c.original_diameter - c.diameter
        for c in workshop.cylinders.values()
        if c.original_diameter != c.diameter
    ]
    mean_wear = float(np.mean(wear_values)) if wear_values else 0.0

    # Per-machine utilization decomposition (OEE-style; available × net = overall
    # utilization = busy / calendar):
    #   - available: availability factor = operative time / calendar, where
    #     operative = calendar − scheduled stoppages (closed shifts). 100% under 24/7.
    #   - net: utilization of available time = busy / operative, where
    #     busy = operative − machine idle − failures (failures not modeled yet ⇒ 0).
    calendar_min = horizon_h * 60
    t0 = workshop.snapshots[0].tiempo if workshop.snapshots else None
    t1 = workshop.snapshots[-1].tiempo if workshop.snapshots else None
    machine_availability: Dict[str, float] = {}
    machine_net: Dict[str, float] = {}
    for name, mq in workshop.machines.items():
        op_min = mq.operative_minutes_between(t0, t1) if t0 is not None else 0.0
        avail = (op_min / calendar_min * 100) if calendar_min > 0 else 0.0
        net = (mq.total_busy_min / op_min * 100) if op_min > 0 else 0.0
        machine_availability[name] = avail
        machine_net[name] = net

    return {
        "cilindros_totales": total,
        "activos": active,
        "bajas": scrapped,
        "alertas_criticas": critical_alerts,
        "cambios_programados": len(workshop.scheduled_events),
        "rectificados_realizados": grinds,
        "horizonte_simulacion_h": horizon_h,
        "diametro_promedio_mm": avg_diam,
        "desgaste_medio_mm": mean_wear,
        "utilizacion_maquinas_pct": machine_availability,
        "utilizacion_neta_pct": machine_net,
    }
