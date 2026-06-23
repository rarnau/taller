"""Dashboard principal adaptado."""
from datetime import timedelta

import numpy as np
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.dates import DateFormatter, date2num
from matplotlib.patches import Patch
from config.tema import (BG, BG2, BG3, FG, FG2, ACCENT, GREEN, ORANGE, RED, RED_DARK,
                          PURPLE, COLORES_ESTADO, SS_COLORS, TIPO_RECT_COLORS)
from modelos.kpis import calcular_kpis


MSG_SIN_DATOS = "Se mostrarán datos una vez corrida la simulación"


def banner_sin_datos(fig):
    """Texto centrado para los dashboards cuando todavía no se simuló."""
    fig.text(0.5, 0.5, MSG_SIN_DATOS, ha="center", va="center",
             color=FG2, fontsize=18, fontweight="bold", zorder=10)


def formatter_tiempo(t0, t1):
    """DateFormatter para un eje temporal: sin hora si el span supera 7 días.

    Con ventanas largas las etiquetas ``%d/%m %H:%M`` se solapan; a partir de una
    semana se muestra sólo el día (``%d/%m``).
    """
    try:
        dias = (t1 - t0).total_seconds() / 86400.0
    except (TypeError, AttributeError):
        dias = 0
    return DateFormatter("%d/%m" if dias > 7 else "%d/%m %H:%M")


def _tramos_parada_maquina(m, t0, t1):
    """Tramos (inicio, fin) en [t0, t1) donde la máquina NO está operativa (turno cerrado).

    Devuelve [] para máquinas 24/7 (``grilla_operativa is None``).
    """
    if getattr(m, "grilla_operativa", None) is None:
        return []
    tramos = []
    t = t0.replace(minute=0, second=0, microsecond=0)
    ini = None
    while t < t1:
        if not m.esta_operativa(t):
            if ini is None:
                ini = max(t, t0)
        elif ini is not None:
            tramos.append((ini, t))
            ini = None
        t += timedelta(hours=1)
    if ini is not None:
        tramos.append((ini, t1))
    return tramos


def _marcar_paradas(ax, tiempos, snapshots):
    """Sombrea en rojo los intervalos en los que hay al menos una jaula PARADA."""
    flags = [bool(getattr(s, "jaulas_paradas", [])) for s in snapshots]
    en_parada, ini, etiquetado = False, None, False
    for k, f in enumerate(flags):
        if f and not en_parada:
            en_parada, ini = True, tiempos[k]
        elif not f and en_parada:
            en_parada = False
            ax.axvspan(ini, tiempos[k], color=RED, alpha=0.18,
                       label=None if etiquetado else "Jaula(s) parada(s)")
            etiquetado = True
    if en_parada:
        ax.axvspan(ini, tiempos[-1], color=RED, alpha=0.18,
                   label=None if etiquetado else "Jaula(s) parada(s)")

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
    if not ti:
        # Preview pre-simulación: mismos 4 paneles vacíos + banner.
        for pos, titulo in ((gs[0, 0], "Evolución Temporal de Estados"),
                            (gs[0, 1], "Buffer de Seguridad Global"),
                            (gs[1, 0], "Utilización de Máquinas — Disponible vs Neta (%)"),
                            (gs[1, 1], "Cronograma de Rectificado")):
            axv = fig.add_subplot(pos)
            _style_ax(axv, titulo)
            axv.set_xticks([])
            axv.set_yticks([])
        banner_sin_datos(fig)
        return fig

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
    _marcar_paradas(ax, ti, t.snapshots)
    ax.legend(loc="upper right", fontsize=7, ncol=3, facecolor="#333", edgecolor="#333", labelcolor=FG)
    ax.xaxis.set_major_formatter(formatter_tiempo(ti[0], ti[-1]))

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
    _marcar_paradas(ax2, ti, t.snapshots)
    ax2.legend(fontsize=7, facecolor="#333", edgecolor="#333", labelcolor=FG)
    ax2.xaxis.set_major_formatter(formatter_tiempo(ti[0], ti[-1]))

    # 3. Utilización de Máquinas (Bar chart): disponible vs neta por máquina.
    # Los porcentajes salen de calcular_kpis (fuente única consumida también por
    # la pestaña KPIs y el CLI), para que coincidan exactamente.
    ax3 = fig.add_subplot(gs[1, 0])
    _style_ax(ax3, "Utilización de Máquinas — Disponible vs Neta (%)")
    kpis = calcular_kpis(t)
    disp_d = kpis["utilizacion_maquinas_pct"]
    neta_d = kpis["utilizacion_neta_pct"]
    maqs_n = list(t.maquinas.keys())
    x = np.arange(len(maqs_n))
    ancho = 0.38
    disp = [disp_d.get(m, 0.0) for m in maqs_n]
    neta = [neta_d.get(m, 0.0) for m in maqs_n]
    barras_disp = ax3.bar(x - ancho / 2, disp, ancho, color=ACCENT, alpha=0.85, label="Disponible")
    barras_neta = ax3.bar(x + ancho / 2, neta, ancho, color=PURPLE, alpha=0.85, label="Neta")
    ax3.set_xticks(x)
    ax3.set_xticklabels(maqs_n)
    ax3.set_ylim(0, 100)
    for barras in (barras_disp, barras_neta):
        for bar in barras:
            height = bar.get_height()
            ax3.text(bar.get_x() + bar.get_width() / 2., height + 1, f'{height:.0f}%',
                     ha='center', color=FG, fontsize=8)
    ax3.legend(loc="upper right", fontsize=7, facecolor="#333", edgecolor="#333", labelcolor=FG)

    # 4. Gantt de máquinas. Eje X en fechas (alineado con la evolución temporal y
    # el buffer). Las paradas por turno se dibujan como una barra sólida más —del
    # mismo alto y estilo que la producción— pero en rojo oscuro.
    ax4 = fig.add_subplot(gs[1, 1])
    _style_ax(ax4, "Cronograma de Rectificado")
    hay_parada = False
    for i, (m_nombre, m) in enumerate(t.maquinas.items()):
        # La producción va debajo; las paradas se dibujan ENCIMA y opacas para que
        # "corten" una barra de trabajo a medio hacer (cuyo fin absorbe el hueco
        # del turno), mostrando la parada en el medio igual que en una máquina
        # totalmente parada.
        for h in m.historial_trabajo:
            ax4.broken_barh([(date2num(h["inicio"]), date2num(h["fin"]) - date2num(h["inicio"]))],
                            (i - 0.3, 0.6), facecolors=TIPO_RECT_COLORS.get(h["tipo"], "#999"),
                            alpha=0.8, edgecolors="white", linewidths=0.2, zorder=1)
        for ini, fin in _tramos_parada_maquina(m, ti[0], ti[-1]):
            ax4.broken_barh([(date2num(ini), date2num(fin) - date2num(ini))],
                            (i - 0.3, 0.6), facecolors=RED_DARK,
                            alpha=1.0, edgecolors="white", linewidths=0.2, zorder=2)
            hay_parada = True
    ax4.set_yticks(range(len(maqs_n)))
    ax4.set_yticklabels(maqs_n, color=FG, fontsize=9)
    ax4.set_xlim(ti[0], ti[-1])
    ax4.xaxis_date()
    ax4.xaxis.set_major_formatter(formatter_tiempo(ti[0], ti[-1]))
    handles = [Patch(facecolor=TIPO_RECT_COLORS.get("produccion", "#999"), label="Producción"),
               Patch(facecolor=TIPO_RECT_COLORS.get("desbaste", "#999"), label="Desbaste")]
    if hay_parada:
        handles.append(Patch(facecolor=RED_DARK, label="Máquina parada (turno)"))
    ax4.legend(handles=handles, loc="upper right", fontsize=7,
               facecolor="#333", edgecolor="#333", labelcolor=FG)

    return fig
