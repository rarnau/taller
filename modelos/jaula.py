"""
Representa una jaula de laminación.
"""
from typing import List
from .cilindro import Cilindro


class Jaula:
    """
    Una jaula que contiene cilindros trabajando y cilindros en el buffer CRC.
    """

    def __init__(self, numero: int):
        self.numero = numero
        self.cilindros_trabajando: List[Cilindro] = []
        self.cilindros_crc: List[Cilindro] = []

    def __repr__(self):
        return f"Jaula(J{self.numero}, Trab={len(self.cilindros_trabajando)}, CRC={len(self.cilindros_crc)})"
