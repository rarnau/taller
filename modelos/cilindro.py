"""
Modelo que representa un cilindro físico en el taller.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from .enums import EstadoCilindro, TipoRectificado


class Cilindro:
    """
    Representa un cilindro con su información de diámetro, estado y ubicación.
    """

    def __init__(
        self,
        id_cilindro: str,
        diametro: float,
        estado: EstadoCilindro = EstadoCilindro.DISPONIBLE,
        jaula: Optional[int] = None,
        posicion: Optional[int] = None
    ):
        self.id = id_cilindro
        self.diametro = diametro
        self.diametro_original = diametro
        self.estado = estado
        self.jaula = jaula
        self.posicion = posicion

        # Información de rectificado
        self.maquina_actual = None
        self.rectificado_inicio = None
        self.rectificado_fin = None
        self.tipo_rectificado_actual = None
        self.mm_a_rectificar = 0.0

        # Historial de eventos para trazabilidad
        self.historial: List[Dict[str, Any]] = []

    def registrar_evento(self, tiempo: datetime, evento: str, detalle: str = ""):
        """Registra un evento en el historial del cilindro."""
        self.historial.append({
            "tiempo": tiempo,
            "evento": evento,
            "estado": self.estado.value,
            "diametro": self.diametro,
            "detalle": detalle
        })

    def rectificar(self, milimetros: float):
        """Aplica el desgaste por rectificado al diámetro del cilindro."""
        self.diametro = round(self.diametro - milimetros, 2)

    def __repr__(self):
        return f"Cilindro({self.id}, D={self.diametro}, Est={self.estado.value})"
