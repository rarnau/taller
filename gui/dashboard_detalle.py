"""Dashboard detallado adaptado."""
import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.patches import Rectangle
from modelos.enums import EstadoCilindro
from config.tema import (BG, BG2, BG3, FG, FG2, ACCENT, RED, GREEN, ORANGE,
                         COLORES_ESTADO, JAULA_COLORS)
from gui.dashboard_principal import formatter_tiempo, rellenar_preview_vacio

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
    """Pinta cada SubStock como su zona de diámetros ``[hasta, desde]``.

    Dos capas: (1) un relleno tenue a toda altura que tiñe la zona sobre las
    barras del histograma; (2) franjas etiquetadas (``J{n}``) apiladas en
    **carriles** arriba del histograma. Como los SubStocks **pueden solaparse**,
    se asignan por *lane packing*: los que no se solapan comparten carril y los
    que sí caen en carriles distintos, dejando el solape a la vista sin taparse.
    Devuelve el nuevo tope del eje Y (incluye la banda de franjas).
    """
    if not substocks:
        return ymax
    bandas = sorted(substocks, key=lambda s: (s.hasta, s.desde))
    topes = []          # max 'desde' ya colocado en cada carril
    asignacion = []     # (substock, índice de carril)
    for ss in bandas:
        col = None
        for i, tope in enumerate(topes):
            if ss.hasta >= tope:        # no se solapa con lo puesto en ese carril
                col, topes[i] = i, ss.desde
                break
        if col is None:                 # se solapa con todos: carril nuevo
            topes.append(ss.desde)
            col = len(topes) - 1
        asignacion.append((ss, col))

    base = ymax * 1.04
    lane_h = max(ymax * 0.045, 0.32)
    barra_h = lane_h * 0.55          # barra fina dentro del carril
    for ss, col in asignacion:
        color = JAULA_COLORS[(ss.jaula_asignada - 1) % len(JAULA_COLORS)]
        # Relleno tenue a toda altura (los solapes se oscurecen al superponerse).
        ax.axvspan(ss.hasta, ss.desde, color=color, alpha=0.07, lw=0, zorder=0)
        # Franja fina etiquetada en su carril, por encima del histograma.
        y0 = base + col * lane_h
        ax.add_patch(Rectangle((ss.hasta, y0), ss.desde - ss.hasta, barra_h,
                               facecolor=color, edgecolor=color, alpha=0.6,
                               lw=0.8, zorder=2, clip_on=False))
        ax.text((ss.hasta + ss.desde) / 2, y0 + barra_h / 2, f"J{ss.jaula_asignada}",
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
            (gs[1, 1], "Timeline de Cambios por Jaula")], _style_ax)

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

    # 2. Distribución de Diámetros + zonas de cada SubStock (pueden solaparse)
    ax2 = fig.add_subplot(gs[1, 0])
    _style_ax(ax2, "Distribución de Diámetros (Activos)")
    diams = [c.diametro for c in t.cilindros.values() if c.estado != EstadoCilindro.BAJA]
    if diams:
        n, _bins, _patches = ax2.hist(diams, bins=15, color=ACCENT, alpha=0.7,
                                      edgecolor="white", lw=0.5, zorder=1)
        ymax = float(max(n)) or 1.0
    else:
        ymax = 1.0
    nuevo_tope = _pintar_zonas_substock(ax2, t.lista_substocks, ymax)
    ax2.axvline(x=t.diametro_minimo, color=RED, lw=2, ls="--", zorder=4,
                label=f"Mín {t.diametro_minimo}")
    ax2.axvline(x=t.diametro_maximo, color=GREEN, lw=2, ls="--", zorder=4,
                label=f"Máx {t.diametro_maximo}")
    # x que abarque las bandas y los límites; y que deje ver la banda de franjas.
    lo = min([t.diametro_minimo] + [ss.hasta for ss in t.lista_substocks])
    hi = max([t.diametro_maximo] + [ss.desde for ss in t.lista_substocks])
    ax2.set_xlim(lo - 3, hi + 3)
    ax2.set_ylim(0, nuevo_tope + ymax * 0.03)
    ax2.legend(fontsize=8, facecolor="#333", edgecolor="#333", labelcolor=FG, loc="lower right")

    # 3. Timeline de Cambios
    ax3 = fig.add_subplot(gs[1, 1])
    _style_ax(ax3, "Timeline de Cambios por Jaula")
    tiempos_ev = [e.tiempo for e in t.eventos_programados]
    for tn, ce in [("produccion", GREEN), ("desbaste", ORANGE)]:
        evs = [e for e in t.eventos_programados if e.tipo.value == tn]
        if evs:
            ax3.scatter([e.tiempo for e in evs], [e.jaula for e in evs],
                        c=ce, s=100, zorder=5, edgecolors="white",
                        linewidths=0.5, alpha=0.8, label=tn.capitalize())
    n_jaulas = t.cantidad_jaulas
    ax3.set_yticks(list(range(1, n_jaulas + 1)))
    ax3.set_yticklabels([f"J{i}" for i in range(1, n_jaulas + 1)], color=FG, fontsize=9)
    if tiempos_ev:
        ax3.xaxis.set_major_formatter(formatter_tiempo(min(tiempos_ev), max(tiempos_ev)))
    ax3.set_ylim(0.5, n_jaulas + 0.5)
    ax3.legend(fontsize=8, facecolor="#333", edgecolor="#333", labelcolor=FG)

    return fig
