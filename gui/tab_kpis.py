"""KPIs adaptados."""
import customtkinter as ctk
from modelos.kpis import calcular_kpis
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

    k = calcular_kpis(taller)
    baj = k["bajas"]
    nc = k["alertas_criticas"]

    kpis = [
        ("Cilindros Totales", str(k["cilindros_totales"]), ACCENT),
        ("Activos", str(k["activos"]), GREEN),
        ("Bajas", str(baj), RED if baj else GREEN),
        ("Alertas Críticas", str(nc), RED if nc else GREEN),
        ("Cambios Programados", str(k["cambios_programados"]), ORANGE),
        ("Rectificados Realizados", str(k["rectificados_realizados"]), PURPLE),
        ("Horizonte Simulación (h)", f"{k['horizonte_simulacion_h']:.1f}", CYAN),
        ("Diámetro Promedio", f"{k['diametro_promedio_mm']:.1f} mm", YELLOW),
        ("Desgaste Medio", f"{k['desgaste_medio_mm']:.2f} mm", "#F97316")
    ]

    neta = k["utilizacion_neta_pct"]
    for mn, pct in k["utilizacion_maquinas_pct"].items():
        kpis.append((f"Util. disponible {mn}", f"{pct:.0f}%", GREEN if pct < 85 else ORANGE))
        pn = neta.get(mn, 0.0)
        kpis.append((f"Util. neta {mn}", f"{pn:.0f}%", GREEN if pn < 85 else ORANGE))

    cols = 3
    for i, (lbl, val, co) in enumerate(kpis):
        r, c2 = divmod(i, cols)
        _ct(container, lbl, val, co, r, c2)

    for i in range(cols):
        container.columnconfigure(i, weight=1)
