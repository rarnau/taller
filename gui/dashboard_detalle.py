"""Dashboard detallado."""
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.dates import DateFormatter
from modelos.enums import EstadoCilindro
from config.tema import BG, BG2, BG3, FG, FG2, ACCENT, RED, GREEN, COLORES_ESTADO
def _style_ax(ax, title):
    ax.set_facecolor(BG2)
    ax.set_title(title, color=ACCENT, fontsize=13, fontweight="bold", pad=10)
    ax.tick_params(colors=FG, labelsize=9)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.12, color="white", linestyle="--")
    for sp in ax.spines.values():
        sp.set_color(BG3)
        sp.set_linewidth(0.6)
def crear_dashboard_detalle(t):
    fig = Figure(figsize=(18, 16), facecolor=BG)
    gs = GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.3, left=0.06, right=0.96, top=0.96, bottom=0.04)
    ax1 = fig.add_subplot(gs[0, :])
    _style_ax(ax1, "Mapa de Cilindros (Estado x Di\u00e1metro)")
    ey = {"Trabajando":5,"CRC":4,"Disponible":3,"A rectificar":2,"Rectificando":1,"Baja":0}
    for en, yv in ey.items():
        cls = [c for c in t.cils.values() if c.estado.value == en]
        if cls: ax1.scatter([c.diametro for c in cls],[yv]*len(cls),c=COLORES_ESTADO.get(en,"#999"),s=[max(30,(c.diametro-510)*3) for c in cls],alpha=0.75,edgecolors="white",linewidths=0.5,zorder=3,label=en)
    ax1.set_yticks(list(ey.values())); ax1.set_yticklabels(list(ey.keys()),color=FG,fontsize=10)
    ax1.set_xlim(515,580); ax1.set_xlabel("Di\u00e1metro (mm)",color=FG2,fontsize=10)
    ax1.legend(fontsize=8,facecolor=BG3,edgecolor=BG3,labelcolor=FG,ncol=6)
    ax3 = fig.add_subplot(gs[1, 0])
    _style_ax(ax3, "Distribuci\u00f3n de Di\u00e1metros")
    diams = [c.diametro for c in t.cils.values() if c.estado != EstadoCilindro.BAJA]
    if diams: ax3.hist(diams,bins=20,color=ACCENT,alpha=0.8,edgecolor="white",lw=0.5)
    ax3.axvline(x=t.d_min,color=RED,lw=2,label=f"M\u00edn {t.d_min}"); ax3.axvline(x=t.d_max,color=GREEN,lw=2,label=f"M\u00e1x {t.d_max}")
    ax3.set_xlabel("Di\u00e1metro (mm)",color=FG2,fontsize=10); ax3.set_ylabel("Cantidad",color=FG2,fontsize=10)
    ax3.legend(fontsize=8,facecolor=BG3,edgecolor=BG3,labelcolor=FG)
    ax4 = fig.add_subplot(gs[1, 1])
    _style_ax(ax4, "Timeline de Cambios")
    for tn, ce in [("produccion",GREEN),("desbaste","#F97316")]:
        evs = [e for e in t.eventos if e.tipo.value == tn]
        if evs: ax4.scatter([e.t for e in evs],[e.jaula for e in evs],c=ce,s=100,zorder=5,edgecolors="white",linewidths=0.5,alpha=0.85,label=tn.capitalize())
    ax4.set_yticks([1,2,3,4]); ax4.set_yticklabels(["J1","J2","J3","J4"],color=FG,fontsize=10)
    ax4.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M")); ax4.set_ylim(0.5,4.5)
    ax4.set_xlabel("Fecha / Hora",color=FG2,fontsize=10); ax4.legend(fontsize=9,facecolor=BG3,edgecolor=BG3,labelcolor=FG)
    return fig
