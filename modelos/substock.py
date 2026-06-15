"""
Representa un grupo de cilindros dentro de un rango de diámetros específico.
"""

class SubStock:
    """
    Define un rango de diámetros (SubStock) asignado a una jaula.
    """

    def __init__(self, nombre: str, id_substock: int, desde: float, hasta: float, jaula_asignada: int = 0):
        self.nombre = nombre
        self.id_substock = id_substock
        self.desde = desde
        self.hasta = hasta
        self.jaula_asignada = jaula_asignada

    def contiene_diametro(self, diametro: float) -> bool:
        """Verifica si un diámetro dado pertenece a este SubStock."""
        # Se asume que 'desde' es el valor mayor y 'hasta' el menor según el código original
        return self.hasta < diametro <= self.desde

    def __repr__(self):
        return f"SubStock({self.nombre}, {self.hasta}-{self.desde} mm)"
