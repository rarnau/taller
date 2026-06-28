"""Detail dashboard (Matplotlib renderer, no Tk)."""
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Rectangle
from models.enums import CylinderState
from config.tema import (BG, BG2, BG3, FG, FG2, ACCENT, RED, GREEN,
                         COLORES_ESTADO, JAULA_COLORS)
from gui.dashboard_principal import formatter_tiempo, rellenar_preview_vacio, _marcar_paradas

def _style_ax(ax, title):
    ax.set_facecolor("#222")
    ax.set_title(title, color=ACCENT, fontsize=12, fontweight="bold", pad=10)
    ax.tick_params(colors=FG, labelsize=8)
    ax.set_axisbelow(True)
    ax.grid(True, alpha=0.1, color="white", linestyle="--")
    for sp in ax.spines.values():
        sp.set_color("#444")
        sp.set_linewidth(0.5)


def _pintar_zonas_substock(ax, substocks, ymax):
    """Paint each SubStock as its diameter zone ``[lower, upper]``.

    Two layers: (1) a faint full-height fill tinting the zone over the histogram
    bars; (2) labeled stripes (``J{n}``) stacked in **lanes** above the histogram.
    Since the SubStocks **may overlap**, they are assigned by *lane packing*: the
    non-overlapping ones share a lane and the overlapping ones fall into different
    lanes, leaving the overlap visible without covering it. Returns the new top of
    the Y axis (including the stripe band).
    """
    if not substocks:
        return ymax
    bandas = sorted(substocks, key=lambda s: (s.lower, s.upper))
    topes = []          # max 'upper' already placed in each lane
    asignacion = []     # (substock, lane index)
    for ss in bandas:
        col = None
        for i, tope in enumerate(topes):
            if ss.lower >= tope:        # does not overlap what is in that lane
                col, topes[i] = i, ss.upper
                break
        if col is None:                 # overlaps with all: new lane
            topes.append(ss.upper)
            col = len(topes) - 1
        asignacion.append((ss, col))

    base = ymax * 1.04
    lane_h = max(ymax * 0.045, 0.32)
    barra_h = lane_h * 0.55          # thin bar inside the lane
    for ss, col in asignacion:
        color = JAULA_COLORS[(ss.assigned_stand - 1) % len(JAULA_COLORS)]
        # Faint full-height fill (overlaps darken as they superimpose).
        ax.axvspan(ss.lower, ss.upper, color=color, alpha=0.07, lw=0, zorder=0)
        # Thin labeled stripe in its lane, above the histogram.
        y0 = base + col * lane_h
        ax.add_patch(Rectangle((ss.lower, y0), ss.upper - ss.lower, barra_h,
                               facecolor=color, edgecolor=color, alpha=0.6,
                               lw=0.8, zorder=2, clip_on=False))
        ax.text((ss.lower + ss.upper) / 2, y0 + barra_h / 2, f"J{ss.assigned_stand}",
                ha="center", va="center", color=BG, fontsize=7, fontweight="bold",
                zorder=3, clip_on=False)
    return base + len(topes) * lane_h

def crear_dashboard_detalle(t):
    fig = Figure(figsize=(18, 12), facecolor="#1A1A1A")
    gs = GridSpec(2, 2, figure=fig, hspace=0.3, wspace=0.2, left=0.06, right=0.96, top=0.94, bottom=0.06)

    if not t.snapshots:
        return rellenar_preview_vacio(fig, [
            (gs[0, :], "Mapa de Cilindros: Estado vs Diámetro"),
            (gs[1, 0], "Distribución de Diámetros (Activos)"),
            (gs[1, 1], "Evolución de SubStock (disponibles)")], _style_ax)

    # 1. Cylinder map (State x Diameter)
    ax1 = fig.add_subplot(gs[0, :])
    _style_ax(ax1, "Mapa de Cilindros: Estado vs Diámetro")
    # Y position by state, derived from the enum (top-to-bottom definition order)
    # to avoid duplicating the list: the first state goes up, the last down.
    estados = [e.value for e in CylinderState]
    ey = {nombre: len(estados) - 1 - i for i, nombre in enumerate(estados)}
    for en, yv in ey.items():
        cls = [c for c in t.cylinders.values() if c.state.value == en]
        if cls:
            ax1.scatter([c.diameter for c in cls], [yv]*len(cls),
                        c=COLORES_ESTADO.get(en, "#999"), s=80, alpha=0.7,
                        edgecolors="white", linewidths=0.5, zorder=3, label=en)
    ax1.set_yticks(list(ey.values()))
    ax1.set_yticklabels(list(ey.keys()), color=FG, fontsize=9)
    ax1.set_xlim(t.min_diameter - 5, t.max_diameter + 5)
    ax1.legend(fontsize=8, facecolor="#333", edgecolor="#333", labelcolor=FG, ncol=7, loc="upper center")

    # 2. Diameter distribution + each SubStock zone (may overlap)
    ax2 = fig.add_subplot(gs[1, 0])
    _style_ax(ax2, "Distribución de Diámetros (Activos)")
    diams = [c.diameter for c in t.cylinders.values() if c.state != CylinderState.SCRAPPED]
    if diams:
        n, _bins, _patches = ax2.hist(diams, bins=15, color=ACCENT, alpha=0.7,
                                      edgecolor="white", lw=0.5, zorder=1)
        ymax = float(max(n)) or 1.0
    else:
        ymax = 1.0
    nuevo_tope = _pintar_zonas_substock(ax2, t.substocks, ymax)
    ax2.axvline(x=t.min_diameter, color=RED, lw=2, ls="--", zorder=4,
                label=f"Mín {t.min_diameter}")
    ax2.axvline(x=t.max_diameter, color=GREEN, lw=2, ls="--", zorder=4,
                label=f"Máx {t.max_diameter}")
    # x covering the bands and the limits; y leaving the stripe band visible.
    lo = min([t.min_diameter] + [ss.lower for ss in t.substocks])
    hi = max([t.max_diameter] + [ss.upper for ss in t.substocks])
    ax2.set_xlim(lo - 3, hi + 3)
    ax2.set_ylim(0, nuevo_tope + ymax * 0.03)
    ax2.legend(fontsize=8, facecolor="#333", edgecolor="#333", labelcolor=FG, loc="lower right")

    # 3. SubStock evolution: available cylinders per band over time. One stepped
    #    line per SubStock (the count changes at events), colored by its stand;
    #    the STOPPAGEs are shaded to read when the stock ran out.
    ax3 = fig.add_subplot(gs[1, 1])
    _style_ax(ax3, "Evolución de SubStock (disponibles)")
    ti = [s.tiempo for s in t.snapshots]
    ymax = 1
    for ss in t.substocks:
        serie = [s.disponibles_por_substock.get(ss.name, 0) for s in t.snapshots]
        color = JAULA_COLORS[(ss.assigned_stand - 1) % len(JAULA_COLORS)]
        ax3.plot(ti, serie, drawstyle="steps-post", color=color, lw=1.8,
                 alpha=0.9, label=f"J{ss.assigned_stand} · {ss.name}")
        if serie:
            ymax = max(ymax, max(serie))
    _marcar_paradas(ax3, ti, t.snapshots)
    if ti:
        ax3.xaxis.set_major_formatter(formatter_tiempo(ti[0], ti[-1]))
    ax3.set_ylim(0, ymax + 1)
    ax3.set_ylabel("Disponibles", color=FG2, fontsize=9)
    ax3.legend(fontsize=7, ncol=2, facecolor="#333", edgecolor="#333", labelcolor=FG)

    return fig
