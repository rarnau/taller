"""
Definición de eventos y estados instantáneos (snapshots) de la simulación.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from .enums import TipoRectificado


class EventoCambio:
    """Representa un evento de cambio de cilindros programado."""
    def __init__(self, id_evento: str, tiempo: datetime, jaula: int, tipo: TipoRectificado, mm_a_rectificar: float, observacion: str = ""):
        self.id = id_evento
        self.tiempo = tiempo
        self.jaula = jaula
        self.tipo = tipo
        self.mm_a_rectificar = mm_a_rectificar
        self.observacion = observacion


class Alerta:
    """Representa una notificación o alerta generada durante la simulación."""
    def __init__(self, tiempo: datetime, tipo: str, mensaje: str, jaula: Optional[int] = None):
        self.tiempo = tiempo
        self.tipo = tipo  # "INFO", "CRITICO", etc.
        self.mensaje = mensaje
        self.jaula = jaula


class Snapshot:
    """
    Captura el estado completo del taller en un momento específico del tiempo.
    Se utiliza para la reproducción de la simulación y gráficos.
    """
    def __init__(self, tiempo: datetime):
        self.tiempo = tiempo
        self.conteo_por_estado: Dict[str, int] = {}
        self.conteo_por_substock: Dict[str, Dict[str, int]] = {}
        self.maquinas_ocupadas = 0
        self.cantidad_bajas = 0
        self.cantidad_disponibles = 0
        self.cantidad_crc_total = 0
        self.crc_por_jaula: Dict[int, int] = {}
        self.disponibles_por_substock: Dict[str, int] = {}

        # Nuevos campos para visualización detallada en tiempo real
        self.detalle_jaulas: Dict[int, List[Dict[str, Any]]] = {}  # {jaula_id: [{"id": id, "d": diam}, ...]}
        self.detalle_crc: Dict[int, List[Dict[str, Any]]] = {}     # {jaula_id: [{"id": id, "d": diam}, ...]}
        self.detalle_maquinas: Dict[str, Optional[Dict[str, Any]]] = {} # {maq_id: {"id": id, "d": diam, "progreso": %}}
        self.detalle_cola_rectificado: List[Dict[str, Any]] = []    # [{"id": id, "d": diam}, ...]
