"""
Definition of events and instantaneous states (snapshots) of the simulation.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from .enums import GrindingType


class ChangeEvent:
    """Represents a scheduled cylinder-change event in the workshop."""

    def __init__(
        self,
        event_id: str,
        time: datetime,
        stand: int,
        grinding_type: GrindingType,
        mm_to_grind: float,
        note: str = ""
    ):
        self.id: str = event_id
        self.time: datetime = time
        self.stand: int = stand
        self.grinding_type: GrindingType = grinding_type
        self.mm_to_grind: float = mm_to_grind
        self.note: str = note


class Alert:
    """Notification generated during the simulation (INFO, WARNING or CRITICO)."""

    def __init__(self, time: datetime, alert_type: str, message: str, stand: Optional[int] = None):
        self.time: datetime = time
        self.type: str = alert_type   # "INFO" | "WARNING" | "CRITICO"
        self.message: str = message
        self.stand: Optional[int] = stand


class Snapshot:
    """
    Captures the full workshop state at one instant of the simulation.
    Used for GUI playback and chart generation.

    NOTE: the public attribute names below stay in Spanish on purpose. The
    regression golden master hashes ``Snapshot.__dict__`` (its keys are these
    attribute names), so renaming any of them would move ``snapshots_sha256``
    and break the golden master. This is the one class whose fields stay Spanish.
    """

    def __init__(self, tiempo: datetime):
        self.tiempo: datetime = tiempo

        # Global counts by state
        self.conteo_por_estado: Dict[str, int] = {}
        self.cantidad_disponibles: int = 0
        self.cantidad_crc_total: int = 0
        self.cantidad_bajas: int = 0
        self.maquinas_ocupadas: int = 0

        # Counts by SubStock
        self.conteo_por_substock: Dict[str, Dict[str, int]] = {}
        self.disponibles_por_substock: Dict[str, int] = {}

        # CRC count per stand
        self.crc_por_jaula: Dict[int, int] = {}

        # Stands halted (STOPPED) at this instant due to lack of stock
        self.jaulas_paradas: List[int] = []

        # Detail for real-time visualization
        self.detalle_jaulas: Dict[int, List[Dict[str, Any]]] = {}       # {stand_id: [{"id", "d"}]}
        self.detalle_crc: Dict[int, List[Dict[str, Any]]] = {}          # {stand_id: [{"id", "d"}]}
        self.detalle_maquinas: Dict[str, Optional[Dict[str, Any]]] = {} # {machine_id: {"id","d","progreso"} | None}
        self.detalle_maquinas_operativa: Dict[str, bool] = {}           # {machine_id: within operative shift}
        self.detalle_cola_rectificado: List[Dict[str, Any]] = []        # [{"id", "d"}]
        self.detalle_enfriando: List[Dict[str, Any]] = []               # [{"id", "d"}]
