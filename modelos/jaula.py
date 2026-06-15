"""
Representa una jaula de laminación.
"""
from datetime import datetime
from typing import List, Optional
from .cilindro import Cilindro


class Jaula:
    """
    Una jaula que contiene cilindros trabajando y cilindros en el buffer CRC.

    Una jaula opera siempre con una pareja completa de cilindros. Si en un
    cambio no hay stock para formar la pareja, la jaula queda en PARADA
    (la línea se detiene) hasta que haya stock disponible para rearmarla.
    """

    def __init__(self, numero: int):
        self.numero = numero
        self.cilindros_trabajando: List[Cilindro] = []
        self.cilindros_crc: List[Cilindro] = []
        self.parada: bool = False
        self.parada_desde: Optional[datetime] = None

    def __repr__(self):
        estado = " PARADA" if self.parada else ""
        return f"Jaula(J{self.numero}, Trab={len(self.cilindros_trabajando)}, CRC={len(self.cilindros_crc)}{estado})"

