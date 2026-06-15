"""
Modelo de una máquina rectificadora de cilindros.
"""
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from .enums import EstadoCilindro, TipoRectificado
from .cilindro import Cilindro


class MaquinaRectificadora:
    """
    Simula el comportamiento de una rectificadora, su capacidad y tiempos de proceso.
    """

    def __init__(self, nombre: str):
        self.nombre = nombre
        self.ocupada = False
        self.cilindro_actual: Optional[Cilindro] = None
        self.tiempo_fin_rectificado: Optional[datetime] = None

        # Tasas de rectificado: {tipo: {"mm": mm, "t_min": min, "rate": mm/min}}
        self.tasas_rectificado: Dict[str, Dict[str, float]] = {}
        self.prioridad_defecto = TipoRectificado.PRODUCCION

        # Estadísticas e historial
        self.historial_trabajo: List[Dict[str, Any]] = []
        self.tiempo_total_ocupada_min = 0.0

    def configurar_tasa(self, tipo: str, mm_removidos: float, tiempo_minutos: float):
        """Configura la velocidad de rectificado para un tipo de pase."""
        tasa = mm_removidos / tiempo_minutos if tiempo_minutos > 0 else 0.0
        self.tasas_rectificado[tipo] = {
            "mm": mm_removidos,
            "t_min": tiempo_minutos,
            "rate": tasa
        }

    def calcular_tiempo_proceso(self, mm_a_rectificar: float, tipo: str) -> float:
        """Calcula cuántos minutos tomará rectificar una cantidad de mm."""
        if tipo not in self.tasas_rectificado or self.tasas_rectificado[tipo]["rate"] <= 0:
            return float("inf")
        return mm_a_rectificar / self.tasas_rectificado[tipo]["rate"]

    def iniciar_rectificado(self, cilindro: Cilindro, tiempo_actual: datetime, tipo: TipoRectificado, mm: float):
        """Inicia el proceso de rectificado para un cilindro."""
        duracion_minutos = self.calcular_tiempo_proceso(mm, tipo.value)
        self.ocupada = True
        self.cilindro_actual = cilindro
        self.tiempo_fin_rectificado = tiempo_actual + timedelta(minutes=duracion_minutos)

        # Actualizar estado del cilindro
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

        # Registrar en historial de la máquina
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
        """Finaliza el proceso actual y libera la máquina."""
        if not self.ocupada or not self.cilindro_actual:
            return None

        cilindro = self.cilindro_actual
        cilindro.rectificar(cilindro.mm_a_rectificar)
        cilindro.estado = EstadoCilindro.DISPONIBLE
        cilindro.maquina_actual = None

        cilindro.registrar_evento(
            tiempo_actual,
            f"Fin rectificado en {self.nombre}",
            f"Nuevo diámetro: {cilindro.diametro} mm"
        )

        self.ocupada = False
        self.cilindro_actual = None
        self.tiempo_fin_rectificado = None

        return cilindro
