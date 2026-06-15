"""Dashboard principal adaptado."""
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.dates import DateFormatter
from matplotlib.patches import Patch
from config.tema import (BG, BG2, BG3, FG, FG2, ACCENT, GREEN, ORANGE,
                          COLORES_ESTADO, SS_COLORS, TIPO_RECT_COLORS)

def _style_ax(ax, title, bg=BG2, fontsize=13):
    ax.set_facecolor(bg)
    ax.set_title(title, color=ACCENT, fontsize=fontsize, fontweight="bold", pad=8)
    ax.tick_params(colors=FG, labelsize=8)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.12, color="white", linestyle="--")
    for sp in ax.spines.values():
        sp.set_color(BG3)
        sp.set_linewidth(0.7)

def crear_dashboard_principal(t, substock=None):
    # Usar fondo un poco más oscuro para que combine con CustomTkinter Dark
    fig = Figure(figsize=(18, 12), facecolor="#1A1A1A")

    gs = GridSpec(2, 2, figure=fig, hspace=0.3, wspace=0.2,
                  left=0.06, right=0.96, top=0.94, bottom=0.06)

    ti = [s.tiempo for s in t.snapshots]
    if not ti: return fig

    EN = t.ESTADOS_NOMBRES

    # 1. Evolución Temporal (global o filtrada por SubStock)
    ax = fig.add_subplot(gs[0, 0])
    if substock:
        _style_ax(ax, f"Evolución Temporal de Estados — {substock}")
        ds = {e: [s.conteo_por_substock.get(substock, {}).get(e, 0) for s in t.snapshots] for e in EN}
    else:
        _style_ax(ax, "Evolución Temporal de Estados — Global")
        ds = {e: [s.conteo_por_estado.get(e, 0) for s in t.snapshots] for e in EN}
    ax.stackplot(ti, np.array([ds[e] for e in EN]),
                 labels=EN, colors=[COLORES_ESTADO.get(e, "#999") for e in EN], alpha=0.85)
    ax.legend(loc="upper right", fontsize=7, ncol=3, facecolor="#333", edgecolor="#333", labelcolor=FG)
    ax.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M"))

    # 2. Buffer Global
    ax2 = fig.add_subplot(gs[0, 1])
    _style_ax(ax2, "Buffer de Seguridad Global")
    dv = [s.cantidad_disponibles for s in t.snapshots]
    cv = [s.cantidad_crc_total for s in t.snapshots]
    bv = [d + c for d, c in zip(dv, cv)]
    ax2.fill_between(ti, bv, alpha=0.15, color=GREEN)
    ax2.plot(ti, bv, color=GREEN, lw=2, label="Disp + CRC")
    ax2.plot(ti, dv, color="#66BB6A", lw=1.5, label="Disponible", ls="--")
    ax2.plot(ti, cv, color=ORANGE, lw=1.5, label="CRC", ls="--")
    ax2.legend(fontsize=7, facecolor="#333", edgecolor="#333", labelcolor=FG)
    ax2.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M"))

    # 3. Utilización de Máquinas (Bar chart)
    ax3 = fig.add_subplot(gs[1, 0])
    _style_ax(ax3, "Utilización de Máquinas (%)")
    th = (ti[-1] - ti[0]).total_seconds() / 3600 if len(ti) > 1 else 1
    maqs_n = list(t.maquinas.keys())
    utils = [(m.tiempo_total_ocupada_min / 60) / th * 100 for m in t.maquinas.values()]
    bars = ax3.bar(maqs_n, utils, color=ACCENT, alpha=0.8)
    ax3.set_ylim(0, 100)
    for bar in bars:
        height = bar.get_height()
        ax3.text(bar.get_x() + bar.get_width()/2., height + 1, f'{height:.0f}%', ha='center', color=FG, fontsize=9)

    # 4. Gantt de máquinas
    ax4 = fig.add_subplot(gs[1, 1])
    _style_ax(ax4, "Cronograma de Rectificado")
    for i, (m_nombre, m) in enumerate(t.maquinas.items()):
        for h in m.historial_trabajo:
            ax4.broken_barh([((h["inicio"] - ti[0]).total_seconds() / 3600,
                              (h["fin"] - h["inicio"]).total_seconds() / 3600)],
                            (i - 0.3, 0.6), facecolors=TIPO_RECT_COLORS.get(h["tipo"], "#999"),
                            alpha=0.8, edgecolors="white", linewidths=0.2)
    ax4.set_yticks(range(len(maqs_n)))
    ax4.set_yticklabels(maqs_n, color=FG, fontsize=9)
    ax4.set_xlabel("Horas desde inicio", color=FG2, fontsize=8)

    return fig
