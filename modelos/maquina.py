"""
Modelo de una máquina rectificadora de cilindros.
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from .enums import EstadoCilindro, TipoRectificado
from .cilindro import Cilindro


class MaquinaRectificadora:
    """
    Simula el comportamiento de una rectificadora: capacidad, tiempos de proceso
    e historial de trabajos realizados.

    Tasas de rectificado:
      Cada tipo de pase (produccion/desbaste) tiene su propia tasa en mm/min.
      Si la tasa es 0 o el tipo no está configurado, calcular_tiempo_proceso
      devuelve float('inf'), indicando que ese tipo de pase no es posible.
    """

    def __init__(self, nombre: str):
        self.nombre: str = nombre
        self.ocupada: bool = False
        self.cilindro_actual: Optional[Cilindro] = None
        self.tiempo_fin_rectificado: Optional[datetime] = None

        # {tipo_str: {"mm": float, "t_min": float, "rate": float}}
        self.tasas_rectificado: Dict[str, Dict[str, float]] = {}
        self.prioridad_defecto: TipoRectificado = TipoRectificado.PRODUCCION

        self.historial_trabajo: List[Dict[str, Any]] = []
        self.tiempo_total_ocupada_min: float = 0.0

    def configurar_tasa(self, tipo: str, mm_removidos: float, tiempo_minutos: float) -> None:
        """Registra la velocidad de rectificado para un tipo de pase."""
        tasa = mm_removidos / tiempo_minutos if tiempo_minutos > 0 else 0.0
        self.tasas_rectificado[tipo] = {
            "mm": mm_removidos,
            "t_min": tiempo_minutos,
            "rate": tasa
        }

    def calcular_tiempo_proceso(self, mm_a_rectificar: float, tipo: str) -> float:
        """
        Calcula cuántos minutos tomará rectificar la cantidad indicada.

        Devuelve float('inf') si el tipo no está configurado o su tasa es 0,
        lo que excluirá este trabajo de la asignación.
        """
        cfg = self.tasas_rectificado.get(tipo)
        if cfg is None or cfg["rate"] <= 0:
            return float("inf")
        return mm_a_rectificar / cfg["rate"]

    def iniciar_rectificado(
        self,
        cilindro: Cilindro,
        tiempo_actual: datetime,
        tipo: TipoRectificado,
        mm: float
    ) -> None:
        """Inicia el proceso de rectificado para un cilindro."""
        duracion_minutos = self.calcular_tiempo_proceso(mm, tipo.value)
        self.ocupada = True
        self.cilindro_actual = cilindro
        self.tiempo_fin_rectificado = tiempo_actual + timedelta(minutes=duracion_minutos)

        cilindro.estado = EstadoCilindro.RECTIFICANDO
        cilindro.maquina_actual = self.nombre
        cilindro.rectificado_inicio = tiempo_actual
        cilindro.rectificado_fin = self.tiempo_fin_rectificado
        cilindro.tipo_rectificado_actual = tipo
        cilindro.mm_a_rectificar = mm

        cilindro.registrar_evento(
            tiempo_actual,
            f"Inicio rectificado {tipo.value} en {self.nombre}",
            f"D{cilindro.diametro}->{round(cilindro.diametro - mm, 2)} ({duracion_minutos:.0f} min)"
        )

        self.historial_trabajo.append({
            "cilindro_id": cilindro.id,
            "inicio": tiempo_actual,
            "fin": self.tiempo_fin_rectificado,
            "tipo": tipo.value,
            "mm": mm,
            "duracion": duracion_minutos
        })
        self.tiempo_total_ocupada_min += duracion_minutos

    def finalizar_rectificado(self, tiempo_actual: datetime) -> Optional[Cilindro]:
        """Finaliza el proceso actual, actualiza el cilindro y libera la máquina."""
        if not self.ocupada or not self.cilindro_actual:
            return None

        cilindro = self.cilindro_actual
        cilindro.rectificar(cilindro.mm_a_rectificar)
        cilindro.estado = EstadoCilindro.DISPONIBLE
        cilindro.maquina_actual = None

        # El rectificado ya fue aplicado arriba; se limpia el tipo/mm pendientes
        # para que el cilindro DISPONIBLE no arrastre datos del pase previo. El
        # próximo CAMBIO los reasigna antes de que vuelva a rectificarse, así que
        # esto no altera ninguna lógica (es solo higiene de estado).
        cilindro.tipo_rectificado_actual = None
        cilindro.mm_a_rectificar = 0.0

        cilindro.registrar_evento(
            tiempo_actual,
            f"Fin rectificado en {self.nombre}",
            f"Nuevo diámetro: {cilindro.diametro} mm"
        )

        self.ocupada = False
        self.cilindro_actual = None
        self.tiempo_fin_rectificado = None

        return cilindro
