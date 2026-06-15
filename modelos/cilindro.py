"""
Modelo que representa un cilindro físico en el taller.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from .enums import EstadoCilindro, TipoRectificado


class Cilindro:
    """
    Representa un cilindro con su diámetro, estado y ubicación en el taller.

    Atributos principales:
      id                      Identificador único del cilindro.
      diametro                Diámetro actual en mm (decrece con cada rectificado).
      diametro_original       Diámetro con el que entró al sistema.
      estado                  Estado actual (EstadoCilindro).
      jaula                   Número de jaula asignada, o None si no está en jaula.
      posicion                Posición dentro de la jaula (opcional).
      mm_a_rectificar         Milímetros a remover en el próximo rectificado.
      tipo_rectificado_actual Tipo de rectificado pendiente o en curso.
      historial               Lista de eventos registrados para trazabilidad.
    """

    def __init__(
        self,
        id_cilindro: str,
        diametro: float,
        estado: EstadoCilindro = EstadoCilindro.DISPONIBLE,
        jaula: Optional[int] = None,
        posicion: Optional[int] = None
    ):
        self.id: str = id_cilindro
        self.diametro: float = diametro
        self.diametro_original: float = diametro
        self.estado: EstadoCilindro = estado
        self.jaula: Optional[int] = jaula
        self.posicion: Optional[int] = posicion

        # Información de rectificado en curso
        self.maquina_actual: Optional[str] = None
        self.rectificado_inicio: Optional[datetime] = None
        self.rectificado_fin: Optional[datetime] = None
        self.tipo_rectificado_actual: Optional[TipoRectificado] = None
        self.mm_a_rectificar: float = 0.0

        # Historial de eventos para trazabilidad
        self.historial: List[Dict[str, Any]] = []

    def registrar_evento(self, tiempo: datetime, evento: str, detalle: str = "") -> None:
        """Añade una entrada al historial del cilindro."""
        self.historial.append({
            "tiempo": tiempo,
            "evento": evento,
            "estado": self.estado.value,
            "diametro": self.diametro,
            "detalle": detalle
        })

    def rectificar(self, milimetros: float) -> None:
        """Reduce el diámetro del cilindro en la cantidad indicada."""
        if milimetros < 0:
            raise ValueError(f"milimetros debe ser >= 0, recibido: {milimetros}")
        self.diametro = round(self.diametro - milimetros, 2)

    def __repr__(self) -> str:
        return f"Cilindro({self.id}, D={self.diametro}, Est={self.estado.value})"
