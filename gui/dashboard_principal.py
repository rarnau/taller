"""Dashboard principal - SubStocks como 4 paneles individuales."""
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

def crear_dashboard_principal(t):
    fig = Figure(figsize=(18, 24), facecolor=BG)
    # Layout: 4 filas
    #   Row 0: Evolucion temporal (full width)
    #   Row 1: SS1 | SS2  (stacked area individuales)
    #   Row 2: SS3 | SS4  (stacked area individuales)
    #   Row 3: Buffer global | Gantt maquinas
    gs = GridSpec(4, 2, figure=fig, hspace=0.38, wspace=0.25,
                  left=0.06, right=0.96, top=0.97, bottom=0.03,
                  height_ratios=[0.8, 1, 1, 0.8])
    ti = [s.t for s in t.snaps]
    EN = t.ESTADOS_NAMES

    # ── 1. Evolucion temporal global (stackplot) ──
    ax = fig.add_subplot(gs[0, :])
    _style_ax(ax, "Evoluci\u00f3n Temporal de Estados")
    ds = {e: [s.por_estado.get(e, 0) for s in t.snaps] for e in EN}
    ax.stackplot(ti, np.array([ds[e] for e in EN]),
                 labels=EN, colors=[COLORES_ESTADO[e] for e in EN], alpha=0.85)
    ax.legend(loc="upper right", fontsize=7, ncol=3, facecolor=BG3, edgecolor=BG3, labelcolor=FG)
    ax.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M"))
    for a in t.alertas:
        if a.tipo == "CRITICO":
            ax.axvline(x=a.t, color="#F85149", ls="--", alpha=0.8, lw=1.5)

    # ── 2-3. SubStocks individuales (2x2 stacked area) ──
    estados_stack = ["Disponible", "CRC", "Trabajando", "A rectificar", "Rectificando"]
    colores_stack = [COLORES_ESTADO[e] for e in estados_stack]

    for idx, ss in enumerate(t.ss_list):
        row_gs = 1 + idx // 2
        col_gs = idx % 2
        ax_ss = fig.add_subplot(gs[row_gs, col_gs])

        # Titulo con color del SS
        ax_ss.set_facecolor(BG2)
        ax_ss.set_title(f"J{ss.jaula_asignada} - {ss.nombre}",
                        color=SS_COLORS[idx], fontsize=12, fontweight="bold", pad=8)
        ax_ss.tick_params(colors=FG, labelsize=7)
        ax_ss.grid(True, alpha=0.10, color="white", linestyle="--")
        for sp in ax_ss.spines.values():
            sp.set_color(SS_COLORS[idx]); sp.set_linewidth(1.0)

        # Extraer series por estado
        series = []
        for est in estados_stack:
            v = [s.por_ss.get(ss.nombre, {}).get(est, 0) for s in t.snaps]
            series.append(v)

        # Stacked area
        arr = np.array(series)
        ax_ss.stackplot(ti, arr, labels=estados_stack,
                        colors=colores_stack, alpha=0.80)

        # Linea de total en blanco semi-transparente
        total_v = arr.sum(axis=0)
        ax_ss.plot(ti, total_v, color="white", lw=1.2, alpha=0.4, ls="--")

        # Anotacion: valor final de disponible + CRC
        if len(ti) > 1:
            disp_final = series[0][-1]
            crc_final = series[1][-1]
            buf = disp_final + crc_final
            ax_ss.annotate(f"Buffer: {buf}",
                           xy=(ti[-1], buf), xytext=(-60, 12),
                           textcoords="offset points",
                           color=SS_COLORS[idx], fontsize=9, fontweight="bold",
                           arrowprops=dict(arrowstyle="->", color=SS_COLORS[idx], lw=1.2))

        ax_ss.set_ylabel("Cilindros", color=FG2, fontsize=8)
        ax_ss.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M"))

        # Leyenda solo en el primer panel
        if idx == 0:
            ax_ss.legend(fontsize=6.5, facecolor=BG3, edgecolor=BG3,
                         labelcolor=FG, ncol=3, loc="upper right")

    # ── 4. Buffer de seguridad global ──
    ax2 = fig.add_subplot(gs[3, 0])
    _style_ax(ax2, "Buffer de Seguridad Global")
    dv = [s.disp for s in t.snaps]; cv = [s.crc_total for s in t.snaps]
    bv = [d + c for d, c in zip(dv, cv)]
    ax2.fill_between(ti, bv, alpha=0.15, color=GREEN)
    ax2.plot(ti, bv, color=GREEN, lw=2.5, label="Disp + CRC")
    ax2.plot(ti, dv, color="#66BB6A", lw=1.5, label="Disponible", ls="--")
    ax2.plot(ti, cv, color=ORANGE, lw=1.5, label="CRC", ls="--")
    ax2.legend(fontsize=7, facecolor=BG3, edgecolor=BG3, labelcolor=FG)
    ax2.xaxis.set_major_formatter(DateFormatter("%d/%m %H:%M"))

    # ── 5. Gantt de maquinas ──
    ax5 = fig.add_subplot(gs[3, 1])
    _style_ax(ax5, "Gantt de M\u00e1quinas")
    mn = list(t.maqs.keys()); tr = t.snaps[0].t
    for i2, m in enumerate(mn):
        for h in t.maqs[m].hist:
            ax5.broken_barh([((h["ini"] - tr).total_seconds() / 3600,
                              (h["fin"] - h["ini"]).total_seconds() / 3600)],
                            (i2 - 0.3, 0.6), facecolors=TIPO_RECT_COLORS.get(h["tipo"], "#999"),
                            alpha=0.85, edgecolors="white", linewidths=0.3)
    ax5.set_yticks(range(len(mn))); ax5.set_yticklabels(mn, color=FG, fontweight="bold")
    ax5.set_xlabel("Horas", color=FG2, fontsize=9)
    ax5.grid(True, alpha=0.12, color="white", axis="x")
    ax5.legend(handles=[Patch(facecolor=TIPO_RECT_COLORS["produccion"], label="Producci\u00f3n"),
                        Patch(facecolor=TIPO_RECT_COLORS["desbaste"], label="Desbaste")],
               fontsize=7, facecolor=BG3, edgecolor=BG3, labelcolor=FG, loc="lower right")

    return fig
