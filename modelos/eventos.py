"""
Definición de eventos y estados instantáneos (snapshots) de la simulación.
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
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

    def __init__(self, tiempo: datetime, tipo: str, mensaje: str, jaula: Optional[int] = None):
        self.tiempo: datetime = tiempo
        self.tipo: str = tipo       # "INFO" | "WARNING" | "CRITICO"
        self.mensaje: str = mensaje
        self.jaula: Optional[int] = jaula


class Snapshot:
    """
    Captura el estado completo del taller en un instante de la simulación.
    Utilizado para reproducción en la GUI y generación de gráficos.
    """

    def __init__(self, tiempo: datetime):
        self.tiempo: datetime = tiempo

        # Conteos globales por estado
        self.conteo_por_estado: Dict[str, int] = {}
        self.cantidad_disponibles: int = 0
        self.cantidad_crc_total: int = 0
        self.cantidad_bajas: int = 0
        self.maquinas_ocupadas: int = 0

        # Conteos por SubStock
        self.conteo_por_substock: Dict[str, Dict[str, int]] = {}
        self.disponibles_por_substock: Dict[str, int] = {}

        # Cilindros activos (no BAJA) atribuidos a UNA única jaula cada uno
        # (trabajando/CRC → su jaula; destinado → su destino; resto → banda por
        # diámetro; 0 = sin banda). A diferencia de los conteos por SubStock,
        # con bandas solapadas no repite cilindros: la suma de valores es el
        # total de activos. Alimenta la evolución de stock por jaula (Análisis).
        self.activos_por_jaula: Dict[int, int] = {}

        # Conteo de CRC por jaula
        self.crc_por_jaula: Dict[int, int] = {}

        # Jaulas detenidas (PARADA) en este instante por falta de stock
        self.jaulas_paradas: List[int] = []

        # Detalle para visualización en tiempo real
        self.detalle_jaulas: Dict[int, List[Dict[str, Any]]] = {}       # {jaula_id: [{"id", "d"}]}
        self.detalle_crc: Dict[int, List[Dict[str, Any]]] = {}          # {jaula_id: [{"id", "d"}]}
        self.detalle_maquinas: Dict[str, Optional[Dict[str, Any]]] = {} # {maq_id: {"id","d","progreso"} | None}
        self.detalle_maquinas_operativa: Dict[str, bool] = {}           # {maq_id: dentro de turno operativo}
        self.detalle_maquinas_falla: Dict[str, bool] = {}               # {maq_id: caída por falla en este instante}
        self.detalle_cola_rectificado: List[Dict[str, Any]] = []        # [{"id", "d"}]
        self.detalle_enfriando: List[Dict[str, Any]] = []               # [{"id", "d"}]


# Campos de Snapshot que consumen los KPIs (modelos/kpis.py) — ÚNICA declaración.
#
# El modo de snapshot liviano del motor (TallerCilindros.snapshot_ligero, pensado
# para Monte Carlo, donde el taller se descarta tras extraer las métricas) computa
# SOLO estos campos; el resto queda en su valor vacío de Snapshot.__init__.
# Regla: si un KPI nuevo lee otro campo de los snapshots, hay que agregarlo acá
# (y su bloque de cómputo en TallerCilindros._BLOQUES_SNAPSHOT_KPI, que un test
# verifica que cubre exactamente este registro: tests/test_snapshot_ligero.py).
# Vive acá (junto a Snapshot) y no en kpis.py porque taller.py no puede importar
# kpis (kpis importa taller: habría ciclo).
CAMPOS_SNAPSHOT_KPI: tuple = (
    "tiempo",                # horizonte_simulacion_h, t0/t1 de utilización y duración
                             # de tramos en _tiempo_y_pct_parada (calcular_kpis)
    "jaulas_paradas",        # tiempo_parada_h / parada_pct (_tiempo_y_pct_parada) y
                             # episodios "paradas" (_metricas_paradas)
    "cantidad_disponibles",  # stock_min (_metricas_paradas)
)
