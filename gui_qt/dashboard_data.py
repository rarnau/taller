"""Extracción de series para el Dashboard Qt nativo.

Porta la lógica de datos que antes vivía en ``gui/dashboard_principal.py``
(conteos por estado a lo largo de los snapshots, buffer Disp/CRC, utilización
de máquinas y segmentos del Gantt) a una estructura sin dependencia de
Matplotlib, consumible por los widgets de ``gui_qt/widgets/dashboard_charts_qt``.

No recomputa KPIs: la utilización sale de ``modelos.kpis.calcular_kpis`` (la
fuente única que también consumen la pestaña KPIs y el CLI).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

from config import tema
from modelos.kpis import calcular_kpis


def tramos_parada_maquina(maquina, t0: datetime, t1: datetime) -> List[Tuple[datetime, datetime]]:
    """Tramos (inicio, fin) en [t0, t1) donde la máquina NO está operativa (turno cerrado).

    Devuelve ``[]`` para máquinas 24/7 (``grilla_operativa is None``). Portado de
    ``gui.dashboard_principal._tramos_parada_maquina`` (lógica idéntica).
    """
    if getattr(maquina, "grilla_operativa", None) is None:
        return []
    tramos: List[Tuple[datetime, datetime]] = []
    t = t0.replace(minute=0, second=0, microsecond=0)
    ini = None
    while t < t1:
        if not maquina.esta_operativa(t):
            if ini is None:
                ini = max(t, t0)
        elif ini is not None:
            tramos.append((ini, t))
            ini = None
        t += timedelta(hours=1)
    if ini is not None:
        tramos.append((ini, t1))
    return tramos


def tramos_falla_maquina(maquina, t0: datetime, t1: datetime) -> List[Tuple[datetime, datetime]]:
    """Tramos (inicio, fin) en [t0, t1) donde la máquina está EN FALLA dentro de turno.

    Sibling de ``tramos_parada_maquina`` pero la condición es "hora operativa Y en
    falla" (la falla es del tiempo disponible). Devuelve ``[]`` si la máquina no
    modela fallas en esta corrida. Por construcción es **disjunto** de los tramos de
    parada (turno cerrado), así que en el Gantt nunca se pisan.
    """
    if not getattr(maquina, "_tiene_fallas", lambda: False)():
        return []
    tramos: List[Tuple[datetime, datetime]] = []
    t = t0.replace(minute=0, second=0, microsecond=0)
    ini = None
    while t < t1:
        if maquina.esta_operativa(t) and maquina.en_falla(t):
            if ini is None:
                ini = max(t, t0)
        elif ini is not None:
            tramos.append((ini, t))
            ini = None
        t += timedelta(hours=1)
    if ini is not None:
        tramos.append((ini, t1))
    return tramos


@dataclass
class DashboardData:
    """Series listas para dibujar las 4 tarjetas del dashboard."""

    tiempos: List[datetime]
    estados: List[str]
    series_estado: Dict[str, List[int]]
    colores_estado: Dict[str, str]
    disponibles: List[int]
    crc: List[int]
    buffer: List[int]
    maquinas: List[str]
    util_disponible: Dict[str, float]
    util_neta: Dict[str, float]
    gantt: Dict[str, List[Tuple[datetime, datetime, str]]]
    paradas_turno: Dict[str, List[Tuple[datetime, datetime]]] = field(default_factory=dict)
    tramos_falla: Dict[str, List[Tuple[datetime, datetime]]] = field(default_factory=dict)

    @property
    def t0(self) -> datetime:
        return self.tiempos[0]

    @property
    def t1(self) -> datetime:
        return self.tiempos[-1]


def extraer_datos_dashboard(taller) -> DashboardData:
    """Construye :class:`DashboardData` a partir de un taller ya simulado.

    Precondición: ``taller.snapshots`` no vacío (el panel muestra un banner si lo
    está, sin llamar acá).
    """
    snaps = taller.snapshots
    tiempos = [s.tiempo for s in snaps]
    estados = list(taller.ESTADOS_NOMBRES)

    series_estado = {
        e: [s.conteo_por_estado.get(e, 0) for s in snaps] for e in estados
    }
    colores_estado = {
        e: tema.COLORES_ESTADO_DASH.get(e, tema.COLORES_ESTADO.get(e, "#999999"))
        for e in estados
    }

    disponibles = [s.cantidad_disponibles for s in snaps]
    crc = [s.cantidad_crc_total for s in snaps]
    buffer = [d + c for d, c in zip(disponibles, crc)]

    kpis = calcular_kpis(taller)
    util_disp = dict(kpis["utilizacion_maquinas_pct"])
    util_neta = dict(kpis["utilizacion_neta_pct"])
    maquinas = list(taller.maquinas.keys())

    t0, t1 = tiempos[0], tiempos[-1]
    gantt: Dict[str, List[Tuple[datetime, datetime, str]]] = {}
    paradas_turno: Dict[str, List[Tuple[datetime, datetime]]] = {}
    tramos_falla: Dict[str, List[Tuple[datetime, datetime]]] = {}
    for nombre, maq in taller.maquinas.items():
        gantt[nombre] = [
            (h["inicio"], h["fin"], h.get("tipo", ""))
            for h in getattr(maq, "historial_trabajo", [])
        ]
        paradas_turno[nombre] = tramos_parada_maquina(maq, t0, t1)
        tramos_falla[nombre] = tramos_falla_maquina(maq, t0, t1)

    return DashboardData(
        tiempos=tiempos,
        estados=estados,
        series_estado=series_estado,
        colores_estado=colores_estado,
        disponibles=disponibles,
        crc=crc,
        buffer=buffer,
        maquinas=maquinas,
        util_disponible=util_disp,
        util_neta=util_neta,
        gantt=gantt,
        paradas_turno=paradas_turno,
        tramos_falla=tramos_falla,
    )
