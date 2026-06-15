"""Enumeraciones."""
from enum import Enum
class EstadoCilindro(Enum):
    TRABAJANDO="Trabajando"; CRC="CRC"; DISPONIBLE="Disponible"
    A_RECTIFICAR="A rectificar"; RECTIFICANDO="Rectificando"; BAJA="Baja"
class TipoRectificado(Enum):
    PRODUCCION="produccion"; DESBASTE="desbaste"
