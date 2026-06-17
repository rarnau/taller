"""Dashboard detallado adaptado."""
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.dates import DateFormatter
from modelos.enums import EstadoCilindro
from config.tema import BG, BG2, BG3, FG, FG2, ACCENT, RED, GREEN, ORANGE, COLORES_ESTADO

def _style_ax(ax, title):
    ax.set_facecolor("#222")
    ax.set_title(title, color=ACCENT, fontsize=12, fontweight="bold", pad=10)
    ax.tick_params(colors=FG, labelsize=8)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.1, color="white", linestyle="--")
    for sp in ax.spines.values():
        sp.set_color("#444")
        sp.set_linewidth(0.5)

def crear_dashboard_detalle(t):
    fig = Figure(figsize=(18, 12), facecolor="#1A1A1A")
    gs = GridSpec(2, 2, figure=fig, hspace=0.3, wspace=0.2, left=0.06, right=0.96, top=0.94, bottom=0.06)

    # 1. Mapa de Cilindros (Estado x Diámetro)
    ax1 = fig.add_subplot(gs[0, :])
    _style_ax(ax1, "Mapa de Cilindros: Estado vs Diámetro")
    # Posición Y por estado, derivada del enum (orden de definición de arriba a
    # abajo) para no duplicar la lista: el primer estado va arriba, el último abajo.
    estados = [e.value for e in EstadoCilindro]
    ey = {nombre: len(estados) - 1 - i for i, nombre in enumerate(estados)}
    for en, yv in ey.items():
        cls = [c for c in t.cilindros.values() if c.estado.value == en]
        if cls:
            ax1.scatter([c.diametro for c in cls], [yv]*len(cls),
                        c=COLORES_ESTADO.get(en, "#999"), s=80, alpha=0.7,
                        edgecolors="white", linewidths=0.5, zorder=3, label=en)
    ax1.set_yticks(list(ey.values()))
    ax1.set_yticklabels(list(ey.keys()), color=FG, fontsize=9)
    ax1.set_xlim(t.diametro_minimo - 5, t.diametro_maximo + 5)
    ax1.legend(fontsize=8, facecolor="#333", edgecolor="#333", labelcolor=FG, ncol=7, loc="upper center")

    # 2. Distribución de Diámetros
    ax2 = fig.add_subplot(gs[1, 0])
    _style_ax(ax2, "Distribución de Diámetros (Activos)")
    diams = [c.diametro for c in t.cilindros.values() if c.estado != EstadoCilindro.BAJA]
    if diams:
        ax2.hist(diams, bins=15, color=ACCENT, alpha=0.7, edgecolor="white", lw=0.5)
    ax2.axvline(x=t.diametro_minimo, color=RED, lw=2, ls="--", label=f"Mín {t.diametro_minimo}")
    ax2.axvline(x=t.diametro_maximo, color=GREEN, lw=2, ls="--", label=f"Máx {t.diametro_maximo}")
    ax2.legend(fontsize=8, facecolor="#333", edgecolor="#333", labelcolor=FG)

    # 3. Timeline de Cambios
    ax3 = fig.add_subplot(gs[1, 1])
    _style_ax(ax3, "Timeline de Cambios por Jaula")
    for tn, ce in [("produccion", GREEN), ("desbaste", ORANGE)]:
        evs = [e for e in t.eventos_programados if e.tipo.value == tn]
        if evs:
            ax3.scatter([e.tiempo for e in evs], [e.jaula for e in evs],
                        c=ce, s=100, zorder=5, edgecolors="white",
                        linewidths=0.5, alpha=0.8, label=tn.capitalize())
    n_jaulas = t.cantidad_jaulas
    ax3.set_yticks(list(range(1, n_jaulas + 1)))
    ax3.set_yticklabels([f"J{i}" for i in range(1, n_jaulas + 1)], color=FG, fontsize=9)
    ax3.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M"))
    ax3.set_ylim(0.5, n_jaulas + 0.5)
    ax3.legend(fontsize=8, facecolor="#333", edgecolor="#333", labelcolor=FG)

    return fig
