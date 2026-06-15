"""SubStock."""
class SubStock:
    def __init__(self,nombre,rid,desde,hasta,jaula_asignada=0):
        self.nombre=nombre;self.rid=rid;self.desde=desde;self.hasta=hasta;self.jaula_asignada=jaula_asignada
    def contiene(self,d): return self.hasta<d<=self.desde
