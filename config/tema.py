"""Paleta de colores."""

# Base: fondos y texto.
BG = "#07111D"
BG2 = "#101826"
BG3 = "#162133"
BG_CARD = "#1A2435"

FG = "#F5F7FA"
FG2 = "#8EA0B8"
FG_DIM = "#66758A"

# Base: acentos.
ACCENT = "#5AA9FF"
GREEN = "#31C48D"
ORANGE = "#F59E0B"
RED = "#F87171"
RED_DARK = "#7F1D1D"
PURPLE = "#A78BFA"
PINK = "#F472B6"
CYAN = "#22D3EE"
YELLOW = "#FBBF24"

# Tipografia.
FONT_FAMILY = "Segoe UI"
FONT_MONO = "Cascadia Code"
FONT_SIZE_SM = 9
FONT_SIZE_MD = 11
FONT_SIZE_LG = 13
FONT_SIZE_XL = 15

# Estado (vista general).
ESTADO_TRABAJANDO = "#388BFD"
ESTADO_CRC = ORANGE
ESTADO_DISPONIBLE = GREEN
ESTADO_ENFRIANDO = CYAN
ESTADO_A_RECTIFICAR = RED
ESTADO_RECTIFICANDO = PURPLE
ESTADO_BAJA = FG_DIM

COLORES_ESTADO = {
    "Trabajando": ESTADO_TRABAJANDO,
    "CRC": ESTADO_CRC,
    "Disponible": ESTADO_DISPONIBLE,
    "Enfriando": ESTADO_ENFRIANDO,
    "A rectificar": ESTADO_A_RECTIFICAR,
    "Rectificando": ESTADO_RECTIFICANDO,
    "Baja": ESTADO_BAJA,
}

SS_COLORS = [ACCENT, ORANGE, GREEN, PINK]
JAULA_COLORS = [ACCENT, ORANGE, GREEN, PINK]
TIPO_RECT_COLORS = {"produccion": GREEN, "desbaste": ORANGE}

# Filas de tabla por estado.
ROW_TRABAJANDO = "#11253D"
ROW_CRC = "#2A1E07"
ROW_DISPONIBLE = "#11291D"
ROW_ENFRIANDO = "#0A2E33"
ROW_A_RECTIFICAR = "#2A0D0D"
ROW_RECTIFICANDO = "#241336"
ROW_BAJA = "#151A22"

# Dashboard (1 a 1 con html_ref.html).
DASH_CARD_BG = "#1A1F26"
DASH_CARD_BORDER = "#2B333D"
DASH_TITLE = "#E8A13A"

DASH_AXIS = DASH_CARD_BORDER
DASH_CURSOR = DASH_TITLE
DASH_TRACK = "#11151A"
DASH_TICK = "#59616B"
DASH_TICK_TEXT = "#8B939D"
DASH_LEGEND_TEXT = "#CFD5DC"
DASH_GRID = "#FFFFFF"

# Alias por uso compartido (uso -> valor base).
DASH_GREEN = GREEN
DASH_PURPLE = PURPLE
DASH_PARADA = RED_DARK
DASH_PARADA_BAND = RED
# Falla de máquina: rojo MENOS oscuro que la parada de turno (DASH_PARADA = #7F1D1D),
# usado de forma consistente en el Gantt y en Vista Real para marcar las demoras/fallas.
DASH_FALLA = "#FF6B6B"

# Tonos propios del dashboard.
DASH_DISP = "#66BB6A"
DASH_ORANGE = "#F0A32E"

DASH_ESTADO_TRABAJANDO = "#4A9EFF"
DASH_ESTADO_CRC = DASH_ORANGE
DASH_ESTADO_DISPONIBLE = "#35C98A"
DASH_ESTADO_ENFRIANDO = "#34D3E0"
DASH_ESTADO_A_RECTIFICAR = "#F56B6B"
DASH_ESTADO_RECTIFICANDO = "#B08CF5"
DASH_ESTADO_BAJA = FG_DIM

COLORES_ESTADO_DASH = {
    "Trabajando": DASH_ESTADO_TRABAJANDO,
    "CRC": DASH_ESTADO_CRC,
    "Disponible": DASH_ESTADO_DISPONIBLE,
    "Enfriando": DASH_ESTADO_ENFRIANDO,
    "A rectificar": DASH_ESTADO_A_RECTIFICAR,
    "Rectificando": DASH_ESTADO_RECTIFICANDO,
    "Baja": DASH_ESTADO_BAJA,
}

TIPO_RECT_COLORS_DASH = {
    "produccion": DASH_ESTADO_DISPONIBLE,
    "desbaste": DASH_ORANGE,
}

# KPIs (fuente única para modelo + GUI).
KPI_CARD_BG = DASH_CARD_BG
KPI_CARD_BORDER = DASH_CARD_BORDER
KPI_TEXT_MUTED = DASH_TICK_TEXT
KPI_TEXT_DEFAULT = "#E9ECEF"
KPI_SECTION_TITLE = DASH_TITLE
KPI_BAR_TRACK = "#232A33"

KPI_COLOR_OK = DASH_GREEN
KPI_COLOR_ALERT = DASH_PARADA_BAND
KPI_COLOR_CAMBIOS = DASH_ORANGE
KPI_COLOR_RECTIFICADOS = DASH_PURPLE
KPI_COLOR_HORIZONTE = DASH_ESTADO_ENFRIANDO
KPI_COLOR_DIAMETRO = YELLOW
KPI_COLOR_DESGASTE = "#F97316"

KPI_META_BASE = {
    "cilindros_totales": {"label": "Cilindros Totales", "color": KPI_TEXT_DEFAULT},
    "activos": {"label": "Activos", "color": KPI_COLOR_OK},
    "bajas": {"label": "Bajas", "color": KPI_COLOR_ALERT},
    "alertas_criticas": {"label": "Alertas Críticas", "color": KPI_COLOR_ALERT},
    "cambios_programados": {"label": "Cambios Programados", "color": KPI_COLOR_CAMBIOS},
    "rectificados_realizados": {"label": "Rectificados Realizados", "color": KPI_COLOR_RECTIFICADOS},
    "horizonte_simulacion_h": {"label": "Horizonte Simulación", "color": KPI_COLOR_HORIZONTE},
    "diametro_promedio_mm": {"label": "Diámetro Promedio", "color": KPI_COLOR_DIAMETRO},
    "desgaste_medio_mm": {"label": "Desgaste Medio", "color": KPI_COLOR_DESGASTE},
    "reposicion_entregados": {"label": "Repuestos (entregados)", "color": KPI_COLOR_OK},
    "reposicion_pendientes": {"label": "Reposición Pendiente", "color": KPI_COLOR_ALERT},
}

# Ajustes del mapa de cilindros (Análisis).
ANALYSIS_MAP_X_MARGIN_RATIO = 0.02
ANALYSIS_MAP_COLLISION_BIN_PX = 8.0
ANALYSIS_MAP_STACK_STEP_PX = 3.0
ANALYSIS_MAP_DENSE_STATE_THRESHOLD = 40
ANALYSIS_MAP_BAJA_DENSITY_THRESHOLD = 60
ANALYSIS_MAP_POINT_RX = 5.6
ANALYSIS_MAP_POINT_RY = 4.2
ANALYSIS_MAP_DENSE_POINT_RX = 4.6
ANALYSIS_MAP_DENSE_POINT_RY = 3.6
ANALYSIS_MAP_POINT_ALPHA = 200
ANALYSIS_MAP_DENSE_POINT_ALPHA = 165
