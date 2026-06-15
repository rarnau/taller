"""KPIs."""
import tkinter as tk
import numpy as np
from modelos.enums import EstadoCilindro
from config.tema import BG, BG2, BG3, BG_CARD, FG2, ACCENT, GREEN, ORANGE, RED, PURPLE, CYAN, YELLOW, FONT_FAMILY, FONT_SIZE, FONT_SIZE_KPI


def _ct(p, l, v, co, r, c):
    f = tk.Frame(p, bg=BG_CARD, bd=1, relief="solid", highlightbackground=co, highlightthickness=1)
    f.grid(row=r, column=c, padx=12, pady=10, sticky="nsew", ipadx=20, ipady=16)
    tk.Frame(f, bg=co, height=3).pack(fill="x", side="top")
    tk.Label(f, text=l.upper(), bg=BG_CARD, fg=FG2, font=(FONT_FAMILY, FONT_SIZE, "bold")).pack(pady=(12, 4))
    tk.Label(f, text=v, bg=BG_CARD, fg=co, font=(FONT_FAMILY, FONT_SIZE_KPI, "bold")).pack(pady=(0, 12))


def llenar_kpis(tab, taller):
    for w in tab.winfo_children():
        w.destroy()
    shell = tk.Frame(tab, bg=BG, padx=10, pady=10)
    shell.pack(fill="both", expand=True)
    card = tk.Frame(shell, bg=BG2, bd=1, relief="solid", highlightbackground=BG3, highlightthickness=1)
    card.pack(fill="both", expand=True)
    header = tk.Frame(card, bg=BG3, height=44)
    header.pack(fill="x")
    header.pack_propagate(False)
    tk.Label(header, text="Indicadores clave de rendimiento", bg=BG3, fg=ACCENT, font=(FONT_FAMILY, 13, "bold")).pack(side="left", padx=12, pady=8)
    m = tk.Frame(card, bg=BG2, padx=14, pady=10)
    m.pack(fill="both", expand=True)
    t2 = len(taller.cils)
    act = len([c for c in taller.cils.values() if c.estado != EstadoCilindro.BAJA])
    baj = t2 - act
    nc = sum(1 for a in taller.alertas if a.tipo == "CRITICO")
    nr = sum(len(mq.hist) for mq in taller.maqs.values())
    th = (taller.snaps[-1].t - taller.snaps[0].t).total_seconds() / 3600 if taller.snaps else 0
    da = np.mean([c.diametro for c in taller.cils.values() if c.estado != EstadoCilindro.BAJA]) if act else 0
    dl = [c.diam_original - c.diametro for c in taller.cils.values() if c.diam_original != c.diametro]
    dd = np.mean(dl) if dl else 0
    kpis = [("Cilindros Totales", str(t2), ACCENT), ("Activos", str(act), GREEN), ("Bajas", str(baj), RED if baj else GREEN), ("Alertas Críticas", str(nc), RED if nc else GREEN), ("Cambios", str(len(taller.eventos)), ORANGE), ("Rectificados", str(nr), PURPLE), ("Horizonte (h)", f"{th:.1f}", CYAN), ("Diam. Promedio", f"{da:.1f} mm", YELLOW), ("Desgaste Medio", f"{dd:.2f} mm", "#F97316")]
    for mn, mq in taller.maqs.items():
        pct = (mq.t_ocupada / 60) / th * 100 if th else 0
        kpis.append((f"Util. {mn}", f"{pct:.0f}%", GREEN if pct < 85 else ORANGE))
    cols = 3
    for i, (lbl, val, co) in enumerate(kpis):
        r, c2 = divmod(i, cols)
        _ct(m, lbl, val, co, r, c2)
    for i in range(cols):
        m.columnconfigure(i, weight=1)
    for i in range((len(kpis) + cols - 1) // cols):
        m.rowconfigure(i, weight=1)
