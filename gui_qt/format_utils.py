"""Utilidades de formato para la GUI Qt (puras, sin dependencias de Qt)."""

from __future__ import annotations

# Promedios usados para que el cambio de unidad sea monótono:
#   12 meses × 30.44 d ≈ 365 d ≈ 1 año.
_DIAS_POR_MES = 30.44
_DIAS_POR_ANIO = 365.25


def formato_horizonte(horas: float) -> str:
    """Formatea una duración en horas eligiendo la unidad más legible.

    Tramos (siempre con 1 decimal y cambiando la anotación de unidad):
      - < 24 h           → horas
      - < 7 días         → días
      - < 12 meses       → meses
      - resto            → años
    """
    horas = float(horas)
    if horas < 24:
        return f"{horas:.1f} h"
    dias = horas / 24.0
    if dias < 7:
        return f"{dias:.1f} d"
    meses = dias / _DIAS_POR_MES
    if meses < 12:
        return f"{meses:.1f} meses"
    return f"{dias / _DIAS_POR_ANIO:.1f} años"
