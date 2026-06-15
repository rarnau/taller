"""Maquina."""
from datetime import datetime,timedelta
from .enums import EstadoCilindro,TipoRectificado
from .cilindro import Cilindro
class MaquinaRect:
    def __init__(self,nombre):
        self.nombre=nombre;self.ocupada=False;self.cil_actual=None;self.fin_rect=None
        self.tasas={};self.prioridad=TipoRectificado.PRODUCCION;self.hist=[];self.t_ocupada=0.0
    def config_tasa(self,tipo,mm,t_min): self.tasas[tipo]={"mm":mm,"t_min":t_min,"rate":mm/t_min if t_min>0 else 0.0}
    def calc_tiempo(self,mm_rect,tipo):
        if tipo not in self.tasas or self.tasas[tipo]["rate"]<=0: return float("inf")
        return mm_rect/self.tasas[tipo]["rate"]
    def iniciar(self,cil,t_now,tipo,mm):
        dur=self.calc_tiempo(mm,tipo.value);self.ocupada=True;self.cil_actual=cil;self.fin_rect=t_now+timedelta(minutes=dur)
        cil.estado=EstadoCilindro.RECTIFICANDO;cil.maquina=self.nombre;cil.rect_inicio=t_now;cil.rect_fin=self.fin_rect;cil.tipo_rect=tipo;cil.mm_rect=mm
        cil.log(t_now,f"Inicio rect. {tipo.value} en {self.nombre}",f"D{cil.diametro}->{round(cil.diametro-mm,2)} ({dur:.0f}min)")
        self.hist.append({"cil":cil.id,"ini":t_now,"fin":self.fin_rect,"tipo":tipo.value,"mm":mm,"dur":dur});self.t_ocupada+=dur
    def finalizar(self,t_now):
        if not self.ocupada or not self.cil_actual: return None
        c=self.cil_actual;c.rectificar(c.mm_rect);c.estado=EstadoCilindro.DISPONIBLE;c.maquina=None
        c.log(t_now,f"Fin rect. {self.nombre}",f"Nuevo D{c.diametro}mm");self.ocupada=False;self.cil_actual=None;self.fin_rect=None;return c
