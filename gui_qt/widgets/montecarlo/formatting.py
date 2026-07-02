"""Formato y catálogo de KPIs destacados del panel Monte Carlo."""

from __future__ import annotations

from typing import List, Tuple

from config import tema

# KPIs destacados en cards + histogramas (clave, etiqueta, color).
KPI_DESTACADOS: List[Tuple[str, str, str]] = [
    ("bajas", "Bajas", tema.RED),
    ("paradas", "Paradas de jaula", tema.ORANGE),
    ("tiempo_parada_h", "Tiempo de parada", tema.DASH_PARADA_BAND),
    ("parada_pct", "Tiempo en parada %", tema.DASH_PARADA),
    ("stock_min", "Stock mínimo", tema.GREEN),
    ("mm_medio_desbaste_mm", "mm medios desbaste", tema.KPI_COLOR_DESGASTE),
    ("mm_medio_produccion_mm", "mm medios producción", tema.KPI_COLOR_DESGASTE),
]


def fmt_mc_kpi(clave: str, valor: float, *, compact: bool = False) -> str:
    """Formatea valores de KPIs de Monte Carlo para cards/tabla."""
    v = float(valor)
    if clave == "tiempo_parada_h":
        return f"{v:.1f} h"
    if clave == "parada_pct":
        return f"{v:.1f}%"
    if clave in {"mm_medio_desbaste_mm", "mm_medio_produccion_mm"}:
        return f"{v:.2f} mm"
    if clave in {"bajas", "paradas", "stock_min"}:
        return f"{v:.0f}" if compact else f"{v:.2f}"
    return f"{v:.0f}" if compact else f"{v:.2f}"
