"""Eventos."""
from datetime import datetime
from .enums import TipoRectificado
class EvtCambio:
    def __init__(self,id_c,t,jaula,tipo,mm,obs=""): self.id=id_c;self.t=t;self.jaula=jaula;self.tipo=tipo;self.mm=mm;self.obs=obs
class Alerta:
    def __init__(self,t,tipo,msg,jaula=None): self.t=t;self.tipo=tipo;self.msg=msg;self.jaula=jaula
class Snapshot:
    def __init__(self,t): self.t=t;self.por_estado={};self.por_ss={};self.maq_ocup=0;self.bajas=0;self.disp=0;self.crc_total=0;self.crc_jaula={};self.disp_ss={}
