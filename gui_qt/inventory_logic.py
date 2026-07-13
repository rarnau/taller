"""Lógica pura (sin Qt) de ordenamiento y filtrado de la pestaña Inventario.

Opera sobre los registros tipados de la vista:
``{"id": str, "diametro": float, "original": float, "desgaste": float,
   "estado": str, "jaula": int | None}``.

Vive en ``gui_qt`` porque es lógica de presentación (las columnas de la vista
no existen en el motor), pero no importa Qt: es testeable headless.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Columnas de la vista, en el orden de la tabla.
COLUMNAS_VISTA = ["id", "diametro", "original", "desgaste", "estado", "jaula"]
_NUMERICAS = {"diametro", "original", "desgaste"}


def ordenar_registros(
    registros: List[Dict[str, Any]], columna: str, descendente: bool
) -> List[Dict[str, Any]]:
    """Devuelve una lista nueva ordenada por ``columna``.

    Numéricas por valor; id/estado por texto case-insensitive; jaula numérica
    con los sin-jaula (None) siempre al final, en ambas direcciones.
    """
    if columna == "jaula":
        con = [r for r in registros if r["jaula"] is not None]
        sin = [r for r in registros if r["jaula"] is None]
        con.sort(key=lambda r: r["jaula"], reverse=descendente)
        return con + sin
    if columna in _NUMERICAS:
        clave = lambda r: r[columna]
    else:
        clave = lambda r: str(r[columna]).casefold()
    return sorted(registros, key=clave, reverse=descendente)


def filtrar_registros(
    registros: List[Dict[str, Any]],
    texto_id: str = "",
    estado: Optional[str] = None,
    jaula: Optional[object] = None,
    diametro_min: float = 0.0,
    diametro_max: float = 0.0,
) -> List[Dict[str, Any]]:
    """Aplica los filtros activos (composición AND). Devuelve una lista nueva.

    - ``texto_id``: substring case-insensitive sobre el ID ("" = sin filtro).
    - ``estado``: valor exacto de EstadoCilindro (None = todos).
    - ``jaula``: int (jaula exacta), la cadena ``"sin"`` (sin jaula) o None (todas).
    - ``diametro_min`` / ``diametro_max``: límites inclusivos; 0 = sin límite.
    """
    texto = texto_id.strip().casefold()
    out = []
    for r in registros:
        if texto and texto not in str(r["id"]).casefold():
            continue
        if estado is not None and r["estado"] != estado:
            continue
        if jaula == "sin":
            if r["jaula"] is not None:
                continue
        elif jaula is not None and r["jaula"] != jaula:
            continue
        if diametro_min > 0 and r["diametro"] < diametro_min:
            continue
        if diametro_max > 0 and r["diametro"] > diametro_max:
            continue
        out.append(r)
    return out
