"""Cálculo de KPIs de una simulación ya ejecutada (sin dependencias de GUI)."""
from typing import Any, Dict

import numpy as np

from config import tema
from modelos.enums import EstadoCilindro
from modelos.taller import TallerCilindros


def calcular_kpis(taller: TallerCilindros) -> Dict[str, Any]:
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

    # Reposición de cilindros: entregados dentro de la ventana vs pedidos que
    # cayeron fuera de [A, B] (ver "Cylinder replenishment" en CLAUDE.md). Con
    # estrategia "ninguna" ambos son 0. getattr cubre un taller sin simular aún.
    reposicion_entregados = int(getattr(taller, "_repo_contador_id", 0))
    reposicion_pendientes = int(getattr(taller, "_repo_pendientes_fuera", 0))

    # Descomposición de la utilización por máquina (tipo OEE; disponible × neta =
    # utilización global = ocupada / calendario):
    #   - disponible: factor de disponibilidad = tiempo operativo / calendario, donde
    #     operativo = calendario − paradas programadas (turnos cerrados). En 24/7 = 100%.
    #     NO se descuentan las fallas (la disponible es solo turnos/calendario).
    #   - neta: utilización del tiempo disponible = ocupada / operativo, donde
    #     ocupada = operativo − máquina libre − fallas. Las fallas (tasa_falla por
    #     máquina) ya se modelan: pausan el rectificado, así que la máquina logra
    #     menos rectificado por minuto operativo y la neta baja sola.
    #   - falla: % del tiempo operativo perdido por fallas (KPI explícito, además de
    #     que la neta ya las refleja). Con tasa_falla=0 es 0.
    calendario_min = horizonte_h * 60
    t0 = taller.snapshots[0].tiempo if taller.snapshots else None
    t1 = taller.snapshots[-1].tiempo if taller.snapshots else None
    utilizacion_maquinas: Dict[str, float] = {}
    utilizacion_neta: Dict[str, float] = {}
    tiempo_falla: Dict[str, float] = {}
    for nombre, mq in taller.maquinas.items():
        op_min = mq.minutos_operativos_entre(t0, t1) if (t0 is not None and t1 is not None) else 0.0
        disp = (op_min / calendario_min * 100) if calendario_min > 0 else 0.0
        neta = (mq.tiempo_total_ocupada_min / op_min * 100) if op_min > 0 else 0.0
        falla_min = mq.minutos_falla_entre(t0, t1) if (t0 is not None and t1 is not None) else 0.0
        falla = (falla_min / op_min * 100) if op_min > 0 else 0.0
        utilizacion_maquinas[nombre] = disp
        utilizacion_neta[nombre] = neta
        tiempo_falla[nombre] = falla

    kpis = {
        "cilindros_totales": total,
        "activos": activos,
        "bajas": bajas,
        "alertas_criticas": alertas_criticas,
        "cambios_programados": len(taller.eventos_programados),
        "rectificados_realizados": rectificados,
        "horizonte_simulacion_h": horizonte_h,
        "diametro_promedio_mm": diam_prom,
        "desgaste_medio_mm": desgaste_medio,
        "reposicion_entregados": reposicion_entregados,
        "reposicion_pendientes": reposicion_pendientes,
        "utilizacion_maquinas_pct": utilizacion_maquinas,
        "utilizacion_neta_pct": utilizacion_neta,
        "tiempo_falla_pct": tiempo_falla,
    }

    # Metadatos para vistas (GUI/CLI): sólo nombre/label (sin color).
    metric_order = [
        key for key, val in kpis.items()
        if not isinstance(val, dict)
    ]
    metric_meta: Dict[str, Dict[str, str]] = {}
    for key in metric_order:
        base = tema.KPI_META_BASE.get(key, {})
        label = str(base.get("label", key.replace("_", " ").title()))

        metric_meta[key] = {
            "label": label,
        }

    kpis["metric_order"] = metric_order
    kpis["metric_meta"] = metric_meta
    return kpis


def _metricas_paradas(taller: TallerCilindros) -> Dict[str, float]:
    """Métricas de servicio derivadas de los snapshots (para Monte Carlo).

    - ``paradas``: episodios de PARADA (flancos de subida por jaula: una jaula
      que pasa de operativa a detenida cuenta una vez por episodio).
    - ``stock_min``: mínimo de cilindros Disponibles a lo largo de la corrida.
    - ``nivel_servicio_pct``: % del tiempo simulado sin ninguna jaula parada
      (ponderado por la duración entre snapshots).
    """
    snaps = taller.snapshots
    if not snaps:
        return {"paradas": 0.0, "stock_min": 0.0, "nivel_servicio_pct": 100.0}

    episodios = 0
    previas: set = set()
    stock_min = min(s.cantidad_disponibles for s in snaps)

    total_s = 0.0
    servida_s = 0.0
    for i, s in enumerate(snaps):
        actuales = set(s.jaulas_paradas)
        episodios += len(actuales - previas)  # flancos de subida
        previas = actuales
        if i + 1 < len(snaps):
            dt = (snaps[i + 1].tiempo - s.tiempo).total_seconds()
            if dt > 0:
                total_s += dt
                if not actuales:
                    servida_s += dt
    nivel = (servida_s / total_s * 100.0) if total_s > 0 else 100.0
    return {"paradas": float(episodios), "stock_min": float(stock_min),
            "nivel_servicio_pct": nivel}


def metricas_montecarlo(taller: TallerCilindros) -> Dict[str, float]:
    """KPIs **planos** (solo escalares) para una corrida de Monte Carlo.

    Construido sobre ``calcular_kpis`` (única fuente de verdad), que **no se
    toca** para no alterar el golden master: aplana los dicts por-máquina a
    columnas ``util_disp_<maq>`` / ``util_neta_<maq>`` / ``falla_<maq>`` y suma
    las métricas de servicio (``paradas``/``stock_min``/``nivel_servicio_pct``).
    El resultado es un dict ``{str: float}`` listo para fila de CSV y agregación.
    """
    k = calcular_kpis(taller)
    fila: Dict[str, float] = {clave: float(k[clave]) for clave in k["metric_order"]}

    prefijos = {"utilizacion_maquinas_pct": "util_disp",
                "utilizacion_neta_pct": "util_neta",
                "tiempo_falla_pct": "falla"}
    for clave, prefijo in prefijos.items():
        for nombre, val in k.get(clave, {}).items():
            fila[f"{prefijo}_{nombre}"] = float(val)

    fila.update(_metricas_paradas(taller))
    return fila
