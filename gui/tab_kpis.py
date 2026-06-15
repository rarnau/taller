"""KPIs adaptados."""
import customtkinter as ctk
import numpy as np
from modelos.enums import EstadoCilindro
from config.tema import *

def _ct(p, l, v, co, r, c):
    f = ctk.CTkFrame(p, border_width=1, border_color=co)
    f.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")

    ctk.CTkLabel(f, text=l.upper(), font=ctk.CTkFont(size=11, weight="bold"), text_color=FG2).pack(pady=(15, 5))
    ctk.CTkLabel(f, text=v, font=ctk.CTkFont(size=24, weight="bold"), text_color=co).pack(pady=(0, 15))


def llenar_kpis(tab, taller):
    for w in tab.winfo_children():
        w.destroy()

    container = ctk.CTkScrollableFrame(tab, fg_color="transparent")
    container.pack(fill="both", expand=True, padx=20, pady=20)

    t2 = len(taller.cilindros)
    act = len([c for c in taller.cilindros.values() if c.estado != EstadoCilindro.BAJA])
    baj = t2 - act
    nc = sum(1 for a in taller.alertas if a.tipo == "CRITICO")
    nr = sum(len(mq.historial_trabajo) for mq in taller.maquinas.values())

    th = 0
    if taller.snapshots:
        th = (taller.snapshots[-1].tiempo - taller.snapshots[0].tiempo).total_seconds() / 3600

    da = np.mean([c.diametro for c in taller.cilindros.values() if c.estado != EstadoCilindro.BAJA]) if act else 0
    dl = [c.diametro_original - c.diametro for c in taller.cilindros.values() if c.diametro_original != c.diametro]
    dd = np.mean(dl) if dl else 0

    kpis = [
        ("Cilindros Totales", str(t2), ACCENT),
        ("Activos", str(act), GREEN),
        ("Bajas", str(baj), RED if baj else GREEN),
        ("Alertas Críticas", str(nc), RED if nc else GREEN),
        ("Cambios Programados", str(len(taller.eventos_programados)), ORANGE),
        ("Rectificados Realizados", str(nr), PURPLE),
        ("Horizonte Simulación (h)", f"{th:.1f}", CYAN),
        ("Diámetro Promedio", f"{da:.1f} mm", YELLOW),
        ("Desgaste Medio", f"{dd:.2f} mm", "#F97316")
    ]

    for mn, mq in taller.maquinas.items():
        pct = (mq.tiempo_total_ocupada_min / 60) / th * 100 if th else 0
        kpis.append((f"Utilización {mn}", f"{pct:.0f}%", GREEN if pct < 85 else ORANGE))

    cols = 3
    for i, (lbl, val, co) in enumerate(kpis):
        r, c2 = divmod(i, cols)
        _ct(container, lbl, val, co, r, c2)

    for i in range(cols):
        container.columnconfigure(i, weight=1)
