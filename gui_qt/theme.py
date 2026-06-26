"""Paleta, tipografías y hoja de estilo global — extraídas del rediseño web.

Todas las constantes de color provienen del HTML de referencia
(``simulador_web.html``). No hardcodear colores en las vistas: importarlos de aquí.
"""
from __future__ import annotations

# ── Fondos / superficies ──────────────────────────────────────────────────────
BG          = "#12161b"   # fondo de la app
PANEL       = "#1a1f26"   # tarjetas / paneles
PANEL_2     = "#161b22"   # cabecera de tabla
HOLE        = "#11151a"   # huecos (inputs, fondos de barra)
SIDEBAR     = "#1a1f26"
TRACK       = "#232a33"   # pista de slider / barras de progreso
TRACK_2     = "#2b333d"   # scrollbar thumb

# ── Bordes ────────────────────────────────────────────────────────────────────
BORDER      = "#2b333d"
BORDER_SOFT = "#262d36"
BORDER_IN   = "#313a45"   # bordes de inputs
ROW_LINE    = "#20262e"

# ── Texto ─────────────────────────────────────────────────────────────────────
TEXT        = "#e9ecef"
TEXT_2      = "#cfd5dc"
TEXT_MUTE   = "#8b939d"
TEXT_DIM    = "#59616b"

# ── Acentos ───────────────────────────────────────────────────────────────────
ORANGE      = "#e8a13a"
ORANGE_2    = "#f0a32e"
ORANGE_DK   = "#c47a1d"
GREEN       = "#35c98a"
GREEN_2     = "#2bb579"
GREEN_3     = "#39d18f"
GREEN_LT    = "#66BB6A"
BLUE        = "#4a9eff"
BLUE_2      = "#5AA9FF"
BLUE_BTN    = "#2563EB"
RED         = "#f56b6b"
PURPLE      = "#b08cf5"
CYAN        = "#34d3e0"
YELLOW      = "#fbbf24"
ORANGE_HOT  = "#f97316"
PINK        = "#F472B6"
PARADA_DK   = "#7f1d1d"   # banda de parada (gantt)

# ── Colores por estado de cilindro (chips) ────────────────────────────────────
COL_ESTADO = {
    "Trabajando":   "#4a9eff",
    "CRC":          "#f0a32e",
    "Disponible":   "#35c98a",
    "Enfriando":    "#34d3e0",
    "A rectificar": "#f56b6b",
    "Rectificando": "#b08cf5",
    "Baja":         "#6b7480",
}
TXT_ESTADO = {
    "Trabajando":   "#06121f",
    "CRC":          "#231603",
    "Disponible":   "#062014",
    "Enfriando":    "#062227",
    "A rectificar": "#2a0808",
    "Rectificando": "#1b0f33",
    "Baja":         "#ffffff",
}

# Colores por jaula (para zonas de SubStock, evol, etc.)
JAULA_COLORS = ["#5AA9FF", "#f0a32e", "#35c98a", "#F472B6", "#b08cf5",
                "#34d3e0", "#fbbf24", "#66BB6A"]

# ── Tipografías (con fallback si las web-fonts no están instaladas) ────────────
FONT_UI      = "'Hanken Grotesk', 'Segoe UI', 'DejaVu Sans', sans-serif"
FONT_DISPLAY = "'Space Grotesk', 'Hanken Grotesk', 'DejaVu Sans', sans-serif"
FONT_MONO    = "'IBM Plex Mono', 'DejaVu Sans Mono', 'Courier New', monospace"


def mezclar(a: str, b: str, t: float) -> str:
    """Interpola dos colores ``#rrggbb`` (t en [0,1]). Espejo de ``_mix`` del HTML."""
    t = max(0.0, min(1.0, t))
    pa = [int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)]
    pb = [int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)]
    return "#" + "".join(f"{round(v + (pb[i] - v) * t):02x}" for i, v in enumerate(pa))


def color_util(pct: float) -> str:
    """Gradiente rojo→amarillo→verde según porcentaje (espejo de ``_utilColor``)."""
    t = max(0.0, min(1.0, pct / 100))
    if t < 0.5:
        return mezclar(RED, YELLOW, t / 0.5)
    return mezclar(YELLOW, GREEN, (t - 0.5) / 0.5)


def tint(color: str, alpha: str = "1a") -> str:
    """Devuelve el color con un sufijo de alpha hex (tinte translúcido)."""
    return color + alpha


# ── Hoja de estilo global (QSS) ───────────────────────────────────────────────
# Reproduce los detalles del HTML: scrollbars finas, fondo, tipografía base.
def hoja_estilo() -> str:
    return f"""
    QWidget {{
        background: {BG};
        color: {TEXT};
        font-family: {FONT_UI};
        font-size: 13px;
    }}
    QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
    QScrollBar::handle {{ background: {TRACK_2}; border-radius: 5px; min-height: 24px; min-width: 24px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QToolTip {{ background: {PANEL}; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}
    """
