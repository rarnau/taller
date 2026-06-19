"""
Modelo que representa un cilindro físico en el taller.
"""
from datetime import datetime
from typing import Any

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
        jaula: int | None = None,
        posicion: int | None = None
    ):
        self.id: str = id_cilindro
        self.diametro: float = diametro
        self.diametro_original: float = diametro
        self.estado: EstadoCilindro = estado
        self.jaula: int | None = jaula
        self.posicion: int | None = posicion

        # Información de rectificado en curso
        self.maquina_actual: str | None = None
        self.rectificado_inicio: datetime | None = None
        self.rectificado_fin: datetime | None = None
        self.tipo_rectificado_actual: TipoRectificado | None = None
        self.mm_a_rectificar: float = 0.0

        # Perfil (bombatura) físico del cilindro: propiedad "pegajosa" que sólo
        # cambia al rectificar (= perfil de la jaula destino elegida). None = sin
        # perfil definido. jaula_destino marca la jaula a la que se lo destinó al
        # iniciar el rectificado (None = stock sin destino, p. ej. el inicial).
        self.perfil: str | None = None
        self.jaula_destino: int | None = None

        # Historial de eventos para trazabilidad
        self.historial: list[dict[str, Any]] = []

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
