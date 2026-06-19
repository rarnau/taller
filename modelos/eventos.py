"""
Definición de eventos y estados instantáneos (snapshots) de la simulación.
"""
from datetime import datetime
from typing import Any

from .enums import TipoRectificado


class EventoCambio:
    """Representa un evento de cambio de cilindros programado en el taller."""

    def __init__(
        self,
        id_evento: str,
        tiempo: datetime,
        jaula: int,
        tipo: TipoRectificado,
        mm_a_rectificar: float,
        observacion: str = ""
    ):
        self.id: str = id_evento
        self.tiempo: datetime = tiempo
        self.jaula: int = jaula
        self.tipo: TipoRectificado = tipo
        self.mm_a_rectificar: float = mm_a_rectificar
        self.observacion: str = observacion


class Alerta:
    """Notificación generada durante la simulación (INFO, WARNING o CRITICO)."""

    def __init__(self, tiempo: datetime, tipo: str, mensaje: str, jaula: int | None = None):
        self.tiempo: datetime = tiempo
        self.tipo: str = tipo       # "INFO" | "WARNING" | "CRITICO"
        self.mensaje: str = mensaje
        self.jaula: int | None = jaula


class Snapshot:
    """
    Captura el estado completo del taller en un instante de la simulación.
    Utilizado para reproducción en la GUI y generación de gráficos.
    """

    def __init__(self, tiempo: datetime):
        self.tiempo: datetime = tiempo

        # Conteos globales por estado
        self.conteo_por_estado: dict[str, int] = {}
        self.cantidad_disponibles: int = 0
        self.cantidad_crc_total: int = 0
        self.cantidad_bajas: int = 0
        self.maquinas_ocupadas: int = 0

        # Conteos por SubStock
        self.conteo_por_substock: dict[str, dict[str, int]] = {}
        self.disponibles_por_substock: dict[str, int] = {}

        # Conteo de CRC por jaula
        self.crc_por_jaula: dict[int, int] = {}

        # Jaulas detenidas (PARADA) en este instante por falta de stock
        self.jaulas_paradas: list[int] = []

        # Detalle para visualización en tiempo real
        self.detalle_jaulas: dict[int, list[dict[str, Any]]] = {}       # {jaula_id: [{"id", "d"}]}
        self.detalle_crc: dict[int, list[dict[str, Any]]] = {}          # {jaula_id: [{"id", "d"}]}
        self.detalle_maquinas: dict[str, dict[str, Any] | None] = {} # {maq_id: {"id","d","progreso"} | None}
        self.detalle_maquinas_operativa: dict[str, bool] = {}           # {maq_id: dentro de turno operativo}
        self.detalle_cola_rectificado: list[dict[str, Any]] = []        # [{"id", "d"}]
        self.detalle_enfriando: list[dict[str, Any]] = []               # [{"id", "d"}]
