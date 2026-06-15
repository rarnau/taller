"""
Representa un grupo de cilindros dentro de un rango de diámetros específico.

Convención de nombres:
  - 'desde' = límite superior del rango (mayor valor, ej. 533 mm)
  - 'hasta' = límite inferior del rango (menor valor, ej. 520 mm)
  Un cilindro pertenece al SubStock si: hasta < diámetro <= desde
"""


class SubStock:
    """
    Define un rango de diámetros (SubStock) asignado a una jaula.

    'desde' debe ser mayor o igual a 'hasta'. Un diámetro `d` pertenece
    a este SubStock si se cumple: hasta < d <= desde.
    """

    def __init__(self, nombre: str, id_substock: int, desde: float, hasta: float, jaula_asignada: int = 0):
        if desde < hasta:
            raise ValueError(
                f"SubStock '{nombre}': 'desde' ({desde}) debe ser >= 'hasta' ({hasta}). "
                "'desde' representa el límite superior y 'hasta' el inferior."
            )
        self.nombre = nombre
        self.id_substock = id_substock
        self.desde = desde      # límite superior (mayor diámetro, inclusive)
        self.hasta = hasta      # límite inferior (menor diámetro, exclusive)
        self.jaula_asignada = jaula_asignada

    def contiene_diametro(self, diametro: float) -> bool:
        """Devuelve True si el diámetro pertenece al rango (hasta, desde]."""
        return self.hasta < diametro <= self.desde

    def __repr__(self) -> str:
        return f"SubStock({self.nombre}, {self.hasta}-{self.desde} mm)"
