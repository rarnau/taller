"""KPIs adaptados."""
import customtkinter as ctk

from config.tema import *
from modelos.kpis import calcular_kpis


def _mezclar(c1, c2, t):
    """Interpola linealmente dos colores hex (#rrggbb); ``t`` en [0, 1]."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02X%02X%02X" % tuple(round(a[j] + (b[j] - a[j]) * t) for j in range(3))


def _color_util(pct):
    """Gradiente de utilización: 0% rojo oscuro, 50% amarillo, 100% verde."""
    t = max(0.0, min(1.0, pct / 100.0))
    if t < 0.5:
        return _mezclar(RED, YELLOW, t / 0.5)
    return _mezclar(YELLOW, GREEN, (t - 0.5) / 0.5)


def _ct(p, l, v, co, r, c):
    f = ctk.CTkFrame(p, border_width=1, border_color=co)
    f.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")

    ctk.CTkLabel(f, text=l.upper(), font=ctk.CTkFont(size=11, weight="bold"), text_color=FG2).pack(pady=(15, 5))
    ctk.CTkLabel(f, text=v, font=ctk.CTkFont(size=24, weight="bold"), text_color=co).pack(pady=(0, 15))


def _card_util(p, nombre, pct, r, c):
    """Tarjeta de utilización: recuadro y porcentaje coloreados por el gradiente.

    El borde y el texto usan el color del gradiente; el relleno es ese mismo
    color atenuado contra el fondo (más oscuro a 0%, "rojo oscuro").
    """
    col = _color_util(pct)
    f = ctk.CTkFrame(p, border_width=2, border_color=col, fg_color=_mezclar(col, BG2, 0.82))
    f.grid(row=r, column=c, padx=10, pady=10, sticky="nsew")

    ctk.CTkLabel(f, text=nombre.upper(), font=ctk.CTkFont(size=11, weight="bold"),
                 text_color=FG2).pack(pady=(15, 5))
    ctk.CTkLabel(f, text=f"{pct:.0f}%", font=ctk.CTkFont(size=24, weight="bold"),
                 text_color=col).pack(pady=(0, 15))


def _seccion_util(container, titulo, datos, nombres, cols=3):
    """Sección titulada con una tarjeta de utilización por máquina (orden dado)."""
    ctk.CTkLabel(container, text=titulo, font=ctk.CTkFont(size=14, weight="bold"),
                 text_color=ACCENT, anchor="w").pack(fill="x", padx=10, pady=(18, 2))
    grid = ctk.CTkFrame(container, fg_color="transparent")
    grid.pack(fill="x")
    for i, mn in enumerate(nombres):
        r, c = divmod(i, cols)
        _card_util(grid, mn, datos.get(mn, 0.0), r, c)
    for i in range(cols):
        grid.columnconfigure(i, weight=1)


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

    cols = 3
    grid_gen = ctk.CTkFrame(container, fg_color="transparent")
    grid_gen.pack(fill="x")
    for i, (lbl, val, co) in enumerate(kpis):
        r, c2 = divmod(i, cols)
        _ct(grid_gen, lbl, val, co, r, c2)
    for i in range(cols):
        grid_gen.columnconfigure(i, weight=1)

    # Secciones de utilización: mismo orden de máquinas en ambas.
    nombres = list(k["utilizacion_maquinas_pct"])
    _seccion_util(container, "UTILIZACIÓN DISPONIBLE", k["utilizacion_maquinas_pct"], nombres, cols)
    _seccion_util(container, "UTILIZACIÓN NETA", k["utilizacion_neta_pct"], nombres, cols)
