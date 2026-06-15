"""
Enumeraciones para el simulador de cilindros.
Define los estados posibles de un cilindro y los tipos de rectificado.
"""
from enum import Enum


class EstadoCilindro(Enum):
    """Estados por los que puede pasar un cilindro en el taller."""
    TRABAJANDO = "Trabajando"
    CRC = "CRC"
    DISPONIBLE = "Disponible"
    A_RECTIFICAR = "A rectificar"
    RECTIFICANDO = "Rectificando"
    BAJA = "Baja"


class TipoRectificado(Enum):
    """Tipos de rectificado aplicables a los cilindros."""
    PRODUCCION = "produccion"
    DESBASTE = "desbaste"
