"""
Enumerations for the cylinder simulator.
Defines the possible states of a cylinder and the grinding pass types.

Note: the enum *member* identifiers are English, but their string *values* stay
in Spanish on purpose. Those values are serialized into snapshots and the
regression golden master, and are validated against the Spanish cell values of
the input Excel files, so changing them would break those external contracts.
"""
from enum import Enum


class CylinderState(Enum):
    """States a cylinder can go through inside the workshop."""
    WORKING = "Trabajando"
    CRC = "CRC"
    AVAILABLE = "Disponible"
    COOLING = "Enfriando"
    TO_GRIND = "A rectificar"
    GRINDING = "Rectificando"
    SCRAPPED = "Baja"


class GrindingType(Enum):
    """Grinding pass types applicable to the cylinders."""
    PRODUCTION = "produccion"
    ROUGHING = "desbaste"
