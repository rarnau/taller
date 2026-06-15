"""Cilindro."""
from datetime import datetime
from .enums import EstadoCilindro, TipoRectificado
class Cilindro:
    def __init__(self,id_cil,diam,estado=EstadoCilindro.DISPONIBLE,jaula=None,pos=None):
        self.id=id_cil;self.diametro=diam;self.diam_original=diam;self.estado=estado
        self.jaula=jaula;self.pos=pos;self.maquina=None;self.rect_inicio=None;self.rect_fin=None
        self.tipo_rect=None;self.mm_rect=0.0;self.historial=[]
    def log(self,t,ev,det=""): self.historial.append({"t":t,"ev":ev,"est":self.estado.value,"d":self.diametro,"det":det})
    def rectificar(self,mm): self.diametro=round(self.diametro-mm,2)
