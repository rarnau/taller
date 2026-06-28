"""Extracción de series para la pestaña Análisis Qt nativa."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

import pandas as pd

from config import tema
from modelos.enums import EstadoCilindro


@dataclass
class HistogramBin:
    """Bin de histograma para distribución de diámetros."""

    left: float
    right: float
    count: int


@dataclass
class AnalysisData:
    """Series listas para dibujar las 3 cards del panel Análisis."""

    estados: List[str]
    mapa_puntos: List[Tuple[float, str]]
    mapa_puntos_por_snapshot: List[List[Tuple[float, str]]]
    diametro_minimo: float
    diametro_maximo: float
    dist_bins: List[HistogramBin]
    dist_min: float
    dist_max: float
    zonas_substock: List[Tuple[str, float, float, str]]
    tiempos: List[datetime]
    evol_substock: Dict[str, List[int]]
    colores_substock: Dict[str, str]
    paradas: List[Tuple[datetime, datetime]]


EMPTY_ANALYSIS_DATA = AnalysisData(
    estados=[e.value for e in EstadoCilindro],
    mapa_puntos=[],
    mapa_puntos_por_snapshot=[],
    diametro_minimo=0.0,
    diametro_maximo=1.0,
    dist_bins=[],
    dist_min=0.0,
    dist_max=1.0,
    zonas_substock=[],
    tiempos=[],
    evol_substock={},
    colores_substock={},
    paradas=[],
)


def _build_histogram(values: Sequence[float], bins: int) -> List[HistogramBin]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / max(1, bins)
    counts = [0 for _ in range(max(1, bins))]
    for value in values:
        idx = int((value - lo) / width)
        if idx >= len(counts):
            idx = len(counts) - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    out: List[HistogramBin] = []
    for i, count in enumerate(counts):
        left = lo + i * width
        right = left + width
        out.append(HistogramBin(left=left, right=right, count=count))
    return out


def _tramos_parada(tiempos: Sequence[datetime], snapshots: Sequence[object]) -> List[Tuple[datetime, datetime]]:
    flags = [bool(getattr(s, "jaulas_paradas", [])) for s in snapshots]
    tramos: List[Tuple[datetime, datetime]] = []
    en_parada = False
    inicio = None
    for i, flag in enumerate(flags):
        if flag and not en_parada:
            en_parada = True
            inicio = tiempos[i]
        elif not flag and en_parada and inicio is not None:
            en_parada = False
            tramos.append((inicio, tiempos[i]))
            inicio = None
    if en_parada and inicio is not None and tiempos:
        tramos.append((inicio, tiempos[-1]))
    return tramos


def _build_snapshot_points(taller, stock_df: pd.DataFrame | None) -> List[List[Tuple[float, str]]]:
    """Reconstruye (diametro, estado) por snapshot sin tocar el motor.

    Fuente de verdad inicial: ``stock_df`` (si está disponible). Luego se aplican
    los eventos de ``cil.historial`` en orden temporal para avanzar snapshot a
    snapshot. Si no hay ``stock_df``, cae a estado/diametro actuales.
    """
    tiempos = [s.tiempo for s in taller.snapshots]
    if not tiempos:
        return []

    current: Dict[str, Tuple[float, str]] = {}
    if stock_df is not None and not stock_df.empty:
        for _, row in stock_df.iterrows():
            cid = str(row.get("ID_Cilindro", ""))
            if not cid:
                continue
            diam = float(row.get("Diámetro_mm", 0.0))
            estado = str(row.get("Estado", EstadoCilindro.DISPONIBLE.value))
            current[cid] = (diam, estado)

    for cid, cil in taller.cilindros.items():
        if cid not in current:
            current[cid] = (float(cil.diametro), cil.estado.value)

    eventos: List[Tuple[datetime, str, float, str]] = []
    for cid, cil in taller.cilindros.items():
        for ev in getattr(cil, "historial", []):
            t_ev = ev.get("tiempo")
            if t_ev is None:
                continue
            try:
                diam = float(ev.get("diametro", current[cid][0]))
            except (TypeError, ValueError):
                diam = current[cid][0]
            estado = str(ev.get("estado", current[cid][1]))
            eventos.append((t_ev, cid, diam, estado))
    eventos.sort(key=lambda it: it[0])

    out: List[List[Tuple[float, str]]] = []
    ie = 0
    for t_snap in tiempos:
        while ie < len(eventos) and eventos[ie][0] <= t_snap:
            _, cid, diam, estado = eventos[ie]
            current[cid] = (diam, estado)
            ie += 1
        out.append(list(current.values()))
    return out


def extraer_datos_analisis(taller, stock_df: pd.DataFrame | None = None) -> AnalysisData:
    """Construye los datos de Análisis para un taller simulado."""
    estados = [e.value for e in EstadoCilindro]
    mapa_puntos_por_snapshot = _build_snapshot_points(taller, stock_df)
    mapa_puntos = mapa_puntos_por_snapshot[-1] if mapa_puntos_por_snapshot else [
        (c.diametro, c.estado.value) for c in taller.cilindros.values()
    ]
    activos = [
        c.diametro for c in taller.cilindros.values() if c.estado != EstadoCilindro.BAJA
    ]
    dist_bins = _build_histogram(activos, bins=13)

    zonas = []
    colores_substock: Dict[str, str] = {}
    for i, ss in enumerate(taller.lista_substocks):
        color = tema.JAULA_COLORS[(ss.jaula_asignada - 1) % len(tema.JAULA_COLORS)]
        zonas.append((f"J{ss.jaula_asignada}", ss.hasta, ss.desde, color))
        colores_substock[ss.nombre] = color

    tiempos = [s.tiempo for s in taller.snapshots]
    evol = {
        ss.nombre: [snap.disponibles_por_substock.get(ss.nombre, 0) for snap in taller.snapshots]
        for ss in taller.lista_substocks
    }
    paradas = _tramos_parada(tiempos, taller.snapshots)

    return AnalysisData(
        estados=estados,
        mapa_puntos=mapa_puntos,
        mapa_puntos_por_snapshot=mapa_puntos_por_snapshot,
        diametro_minimo=float(taller.diametro_minimo),
        diametro_maximo=float(taller.diametro_maximo),
        dist_bins=dist_bins,
        dist_min=min(activos) if activos else float(taller.diametro_minimo),
        dist_max=max(activos) if activos else float(taller.diametro_maximo),
        zonas_substock=zonas,
        tiempos=tiempos,
        evol_substock=evol,
        colores_substock=colores_substock,
        paradas=paradas,
    )
