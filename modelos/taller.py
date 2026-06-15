"""Motor de simulacion."""
import pandas as pd
from datetime import datetime,timedelta
from .enums import EstadoCilindro,TipoRectificado
from .cilindro import Cilindro
from .substock import SubStock
from .maquina import MaquinaRect
from .jaula import Jaula
from .eventos import EvtCambio,Alerta,Snapshot
class TallerCilindros:
    ESTADOS_NAMES=["Trabajando","CRC","Disponible","A rectificar","Rectificando","Baja"]
    def __init__(self):
        self.cils={};self.ss_list=[];self.maqs={};self.jaulas={};self.eventos=[];self.alertas=[];self.snaps=[]
        self.d_max=575.0;self.d_min=520.0;self.t_disp_crc=10.0;self.n_jaulas=4;self.estrategia="mayor_diametro"
    def configurar_substocks(self,rangos):
        self.ss_list.clear()
        for r in rangos:
            j=int(r["jaula"]);d=float(r["desde"]);h=float(r["hasta"])
            self.ss_list.append(SubStock(f"SS{j} ({h:.0f}-{d:.0f})",j,d,h,jaula_asignada=j))
    def aplicar_prioridades(self,prios):
        for n,tp in prios.items():
            if n in self.maqs: self.maqs[n].prioridad=TipoRectificado(tp)
    def cargar(self,fp):
        self.cils.clear();self.maqs.clear();self.jaulas.clear();self.eventos.clear();self.alertas.clear();self.snaps.clear()
        dc=pd.read_excel(fp,sheet_name="Configuraci\u00f3n",engine="openpyxl");cfg=dict(zip(dc["Par\u00e1metro"],dc["Valor"]))
        self.d_max=float(cfg.get("Di\u00e1metro M\u00e1ximo (mm)",575));self.d_min=float(cfg.get("Di\u00e1metro M\u00ednimo (mm)",520))
        self.t_disp_crc=float(cfg.get("Tiempo Disponible\u2192CRC por pareja (min)",10));self.n_jaulas=int(cfg.get("Cantidad de Jaulas",4))
        dm=pd.read_excel(fp,sheet_name="M\u00e1quinas",engine="openpyxl")
        for _,row in dm.iterrows():
            n=str(row["M\u00e1quina"])
            if n not in self.maqs: self.maqs[n]=MaquinaRect(n)
            self.maqs[n].config_tasa(str(row["Tipo_Rectificado"]),float(row["mm_removidos"]),float(row["Tiempo_min"]))
        ds=pd.read_excel(fp,sheet_name="Stock_Inicial",engine="openpyxl")
        for _,row in ds.iterrows():
            estado=EstadoCilindro(row["Estado"]);jaula=int(row["Jaula_Asignada"]) if pd.notna(row.get("Jaula_Asignada")) else None
            pos=int(row["Posici\u00f3n"]) if pd.notna(row.get("Posici\u00f3n")) else None
            cil=Cilindro(str(row["ID_Cilindro"]),float(row["Di\u00e1metro_mm"]),estado,jaula,pos)
            if estado in (EstadoCilindro.A_RECTIFICAR,EstadoCilindro.RECTIFICANDO):
                cil.mm_rect=float(row["mm_a_Rectificar"]) if "mm_a_Rectificar" in row.index and pd.notna(row.get("mm_a_Rectificar")) else 0.8
                cil.tipo_rect=TipoRectificado(str(row["Tipo_Rectificado"])) if "Tipo_Rectificado" in row.index and pd.notna(row.get("Tipo_Rectificado")) else TipoRectificado.PRODUCCION
                if estado==EstadoCilindro.RECTIFICANDO: cil.estado=EstadoCilindro.A_RECTIFICAR
            self.cils[cil.id]=cil
        for j in range(1,self.n_jaulas+1): self.jaulas[j]=Jaula(j)
        for cil in self.cils.values():
            if cil.estado==EstadoCilindro.TRABAJANDO and cil.jaula: self.jaulas[cil.jaula].trabajando.append(cil)
            elif cil.estado==EstadoCilindro.CRC and cil.jaula: self.jaulas[cil.jaula].crc.append(cil)
        self._gp()
        dc2=pd.read_excel(fp,sheet_name="Programa_Cambios",engine="openpyxl")
        for _,row in dc2.iterrows():
            self.eventos.append(EvtCambio(str(row["ID_Cambio"]),pd.to_datetime(row["Fecha_Hora"]),int(row["Jaula"]),TipoRectificado(str(row["Tipo_Rectificado"])),float(row["mm_a_Rectificar"]),str(row.get("Observaci\u00f3n",""))))
        self.eventos.sort(key=lambda e:e.t)
    def _gp(self):
        for jn,jl in self.jaulas.items():
            while len(jl.trabajando)<2:
                if jl.crc: c=jl.crc.pop(0);c.estado=EstadoCilindro.TRABAJANDO;c.jaula=jn;jl.trabajando.append(c);continue
                disp=sorted(self.disponibles_para_jaula(jn),key=lambda c:c.diametro,reverse=True)
                if disp: c=disp[0];c.estado=EstadoCilindro.TRABAJANDO;c.jaula=jn;jl.trabajando.append(c);continue
                break
    def get_ss(self,d):
        for ss in self.ss_list:
            if ss.contiene(d): return ss
        return None
    def get_ss_for_jaula(self,jn):
        for ss in self.ss_list:
            if ss.jaula_asignada==jn: return ss
        return None
    def by_estado(self,est): return[c for c in self.cils.values() if c.estado==est]
    def disponibles(self): return self.by_estado(EstadoCilindro.DISPONIBLE)
    def disponibles_para_jaula(self,jn):
        ss=self.get_ss_for_jaula(jn)
        if ss is None: return self.disponibles()
        return[c for c in self.disponibles() if ss.contiene(c.diametro)]
    def cola_rect(self): return self.by_estado(EstadoCilindro.A_RECTIFICAR)
    def pick(self,cola):
        if not cola: return None
        if self.estrategia=="mayor_diametro": return max(cola,key=lambda c:c.diametro)
        elif self.estrategia=="menor_diametro": return min(cola,key=lambda c:c.diametro)
        return cola[0]
    def snap(self,t):
        sn=Snapshot(t)
        for est in EstadoCilindro: sn.por_estado[est.value]=len(self.by_estado(est))
        sn.disp=sn.por_estado.get("Disponible",0);sn.crc_total=sn.por_estado.get("CRC",0);sn.bajas=sn.por_estado.get("Baja",0)
        sn.maq_ocup=sum(1 for m in self.maqs.values() if m.ocupada)
        for j,jl in self.jaulas.items(): sn.crc_jaula[j]=len(jl.crc)
        for ss in self.ss_list:
            cnt={}
            for c in self.cils.values():
                if c.estado!=EstadoCilindro.BAJA and ss.contiene(c.diametro): cnt[c.estado.value]=cnt.get(c.estado.value,0)+1
            sn.por_ss[ss.nombre]=cnt;sn.disp_ss[ss.nombre]=cnt.get("Disponible",0)
        self.snaps.append(sn)
    def asignar_maq(self,t):
        nv=[]
        for nm,mq in self.maqs.items():
            if mq.ocupada: continue
            cola=self.cola_rect()
            if not cola: break
            c=self.pick(cola)
            if c is None: continue
            mm=c.mm_rect if c.mm_rect>0 else 0.8;tp=c.tipo_rect if c.tipo_rect else mq.prioridad;nd=c.diametro-mm
            if nd<self.d_min: c.estado=EstadoCilindro.BAJA;c.log(t,"BAJA");self.alertas.append(Alerta(t,"INFO",f"Cil {c.id} BAJA"));continue
            mq.iniciar(c,t,tp,mm);nv.append(("FIN",mq.fin_rect,nm))
        return nv
    def reponer_crc(self,jn,t):
        jl=self.jaulas[jn];need=2-len(jl.crc)
        if need<=0: return True
        disp=sorted(self.disponibles_para_jaula(jn),key=lambda c:c.diametro,reverse=True);ok=0
        for c in disp:
            if ok>=need: break
            c.estado=EstadoCilindro.CRC;c.jaula=jn;jl.crc.append(c);c.log(t,f"CRC J{jn}");ok+=1
        return ok>=need
    def simular(self,estrategia="mayor_diametro",log_callback=None):
        self.estrategia=estrategia;self.alertas.clear();self.snaps.clear()
        def _l(m):
            if log_callback: log_callback(m)
        if not self.eventos: _l("Sin eventos.");return
        _l(f"Inicio|{estrategia}|{len(self.cils)}cils|{len(self.eventos)}evts")
        for j,jl in self.jaulas.items(): _l(f"  J{j}: T={len(jl.trabajando)} CRC={len(jl.crc)}")
        t0=self.eventos[0].t-timedelta(minutes=1);self.snap(t0)
        eq=[("CAM",ev.t,ev) for ev in self.eventos];nf=self.asignar_maq(t0);eq.extend(nf);eq.sort(key=lambda x:x[1])
        done=set();itr=0
        while eq and itr<5000:
            itr+=1;tp_e,te,data=eq.pop(0)
            if tp_e=="FIN":
                mn=data;mq=self.maqs.get(mn)
                if not mq or not mq.ocupada: continue
                if mq.fin_rect and abs((mq.fin_rect-te).total_seconds())>2: continue
                c=mq.finalizar(te)
                if c:
                    for jn in range(1,self.n_jaulas+1):
                        if len(self.jaulas[jn].crc)<2: self.reponer_crc(jn,te+timedelta(minutes=self.t_disp_crc))
                nf=self.asignar_maq(te);eq.extend(nf);eq.sort(key=lambda x:x[1]);self.snap(te)
            elif tp_e=="CAM":
                ev=data
                if ev.id in done: continue
                done.add(ev.id);jl=self.jaulas[ev.jaula]
                _l(f"  {ev.t.strftime('%m-%d %H:%M')}|J{ev.jaula}|{ev.tipo.value}|{ev.mm}mm|CRC={len(jl.crc)}")
                for c in list(jl.trabajando): c.estado=EstadoCilindro.A_RECTIFICAR;c.jaula=None;c.tipo_rect=ev.tipo;c.mm_rect=ev.mm
                jl.trabajando.clear()
                if len(jl.crc)>=2:
                    for c in list(jl.crc[:2]): c.estado=EstadoCilindro.TRABAJANDO;c.jaula=ev.jaula;jl.crc.remove(c);jl.trabajando.append(c)
                else:
                    for c in list(jl.crc): c.estado=EstadoCilindro.TRABAJANDO;c.jaula=ev.jaula;jl.crc.remove(c);jl.trabajando.append(c)
                    deficit=2-len(jl.trabajando)
                    if deficit>0:
                        em=sorted(self.disponibles_para_jaula(ev.jaula),key=lambda c:c.diametro,reverse=True)
                        for c in em[:deficit]: c.estado=EstadoCilindro.TRABAJANDO;c.jaula=ev.jaula;jl.trabajando.append(c);deficit-=1
                    if deficit>0: self.alertas.append(Alerta(ev.t,"CRITICO",f"SIN STOCK J{ev.jaula} falta {deficit}",ev.jaula));_l(f"  >>>CRITICA J{ev.jaula}<<<")
                self.reponer_crc(ev.jaula,ev.t+timedelta(minutes=self.t_disp_crc))
                nf=self.asignar_maq(ev.t);eq.extend(nf);eq.sort(key=lambda x:x[1]);self.snap(ev.t)
        for _ in range(200):
            busy=False
            for mq in self.maqs.values():
                if mq.ocupada and mq.fin_rect:
                    busy=True;tf=mq.fin_rect;mq.finalizar(tf)
                    for jn in range(1,self.n_jaulas+1):
                        if len(self.jaulas[jn].crc)<2: self.reponer_crc(jn,tf+timedelta(minutes=self.t_disp_crc))
                    self.asignar_maq(tf);self.snap(tf)
            if not busy: break
        tf2=max(s.t for s in self.snaps)+timedelta(minutes=30) if self.snaps else datetime.now();self.snap(tf2)
        nc=sum(1 for a in self.alertas if a.tipo=="CRITICO");nb=len(self.by_estado(EstadoCilindro.BAJA))
        _l(f"\nFin|Crit:{nc}|Bajas:{nb}")
        for est in EstadoCilindro:
            n=len(self.by_estado(est))
            if n: _l(f"  {est.value:20s}:{n}")
    def exportar_resultados(self,fp):
        rows=[{"ID":c.id,"D_Orig":c.diam_original,"D_Final":c.diametro,"Desgaste":round(c.diam_original-c.diametro,2),
               "Estado":c.estado.value,"SubStock":(self.get_ss(c.diametro).nombre if self.get_ss(c.diametro) else "-"),
               "Jaula":c.jaula or "-"} for c in self.cils.values()]
        df_f=pd.DataFrame(rows).sort_values("D_Final",ascending=False)
        al=[{"Tiempo":a.t,"Tipo":a.tipo,"Msg":a.msg,"Jaula":a.jaula or "-"} for a in self.alertas]
        df_a=pd.DataFrame(al) if al else pd.DataFrame(columns=["Tiempo","Tipo","Msg","Jaula"])
        with pd.ExcelWriter(fp,engine="openpyxl") as w:
            df_f.to_excel(w,sheet_name="Stock_Final",index=False);df_a.to_excel(w,sheet_name="Alertas",index=False)
