"""Extracción de series para la pestaña Análisis Qt nativa."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

import pandas as pd

from config import tema
from modelos.enums import EstadoCilindro


# Serie extra de la evolución de stock: activos cuyo diámetro no cae en ninguna
# banda (clave 0 de Snapshot.activos_por_jaula). Solo aparece si tiene valores.
NOMBRE_SIN_BANDA = "Sin banda"


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
    dist_bins_por_snapshot: List[List[HistogramBin]]
    dist_max_count: int
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
    dist_bins_por_snapshot=[],
    dist_max_count=1,
    dist_min=0.0,
    dist_max=1.0,
    zonas_substock=[],
    tiempos=[],
    evol_substock={},
    colores_substock={},
    paradas=[],
)


def _build_histogram_fixed(values: Sequence[float], lo: float, hi: float,
                           bins: int) -> List[HistogramBin]:
    """Histograma con bordes FIJOS ``[lo, hi]`` (mismos bins en cada snapshot).

    A diferencia de ``_build_histogram`` (que deriva lo/hi de los valores), acá
    los bordes se fijan afuera, de modo que la distribución por snapshot use la
    MISMA grilla y las barras no salten al mover el timeline. Con ``values``
    vacío devuelve igual ``bins`` barras (todas en 0), no ``[]``.
    """
    n = max(1, bins)
    if hi <= lo:
        hi = lo + 1.0
    width = (hi - lo) / n
    counts = [0 for _ in range(n)]
    for value in values:
        idx = int((value - lo) / width)
        idx = 0 if idx < 0 else (n - 1 if idx >= n else idx)
        counts[idx] += 1
    return [HistogramBin(left=lo + i * width, right=lo + (i + 1) * width, count=c)
            for i, c in enumerate(counts)]


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

    # Distribución de diámetros POR SNAPSHOT: reconstruida del mismo mapa que ya
    # varía con el timeline (mapa_puntos_por_snapshot), filtrando los BAJA. Los
    # bordes de los bins son FIJOS (rango global de activos sobre todos los
    # snapshots) para que las barras no salten, y la escala de altura usa el
    # máximo global (dist_max_count) para que las alturas sean comparables al
    # mover el cursor. Fuera de simulación cae al histograma del estado final.
    _BAJA = EstadoCilindro.BAJA.value
    _BINS = 13
    activos_por_snap = [
        [d for (d, est) in pts if est != _BAJA]
        for pts in mapa_puntos_por_snapshot
    ]
    _todos = [d for lst in activos_por_snap for d in lst] or activos
    g_lo = min(_todos) if _todos else float(taller.diametro_minimo)
    g_hi = max(_todos) if _todos else float(taller.diametro_maximo)
    dist_bins_por_snapshot = [
        _build_histogram_fixed(lst, g_lo, g_hi, _BINS) for lst in activos_por_snap
    ]
    dist_max_count = max(
        (b.count for bins in dist_bins_por_snapshot for b in bins), default=1)
    # dist_bins (fallback sin cursor / estado vacío) = última foto si la hay,
    # con los MISMOS bordes que la serie por snapshot.
    dist_bins = (dist_bins_por_snapshot[-1] if dist_bins_por_snapshot
                 else _build_histogram_fixed(activos, g_lo, g_hi, _BINS))

    zonas = []
    colores_substock: Dict[str, str] = {}
    for i, ss in enumerate(taller.lista_substocks):
        color = tema.JAULA_COLORS[(ss.jaula_asignada - 1) % len(tema.JAULA_COLORS)]
        zonas.append((f"J{ss.jaula_asignada}", ss.hasta, ss.desde, color))
        colores_substock[ss.nombre] = color

    tiempos = [s.tiempo for s in taller.snapshots]
    # Evolución de stock por jaula con atribución ÚNICA (Snapshot.activos_por_jaula):
    # cada cilindro activo cuenta en una sola serie aunque las bandas se solapen,
    # así el total de las series es el total de activos (no BAJA). La clave 0
    # agrupa los activos fuera de toda banda; la serie se agrega solo si aparece.
    evol = {
        ss.nombre: [getattr(snap, "activos_por_jaula", {}).get(ss.jaula_asignada, 0)
                    for snap in taller.snapshots]
        for ss in taller.lista_substocks
    }
    sin_banda = [getattr(snap, "activos_por_jaula", {}).get(0, 0) for snap in taller.snapshots]
    if any(sin_banda):
        evol[NOMBRE_SIN_BANDA] = sin_banda
        colores_substock[NOMBRE_SIN_BANDA] = tema.DASH_TICK_TEXT
    paradas = _tramos_parada(tiempos, taller.snapshots)

    return AnalysisData(
        estados=estados,
        mapa_puntos=mapa_puntos,
        mapa_puntos_por_snapshot=mapa_puntos_por_snapshot,
        diametro_minimo=float(taller.diametro_minimo),
        diametro_maximo=float(taller.diametro_maximo),
        dist_bins=dist_bins,
        dist_bins_por_snapshot=dist_bins_por_snapshot,
        dist_max_count=dist_max_count,
        dist_min=g_lo,
        dist_max=g_hi,
        zonas_substock=zonas,
        tiempos=tiempos,
        evol_substock=evol,
        colores_substock=colores_substock,
        paradas=paradas,
    )
