"""Paleta de colores."""
BG="#07111D"; BG2="#101826"; BG3="#162133"; BG_CARD="#1A2435"; BG_HOVER="#24324A"
FG="#F5F7FA"; FG2="#8EA0B8"; FG_DIM="#66758A"
ACCENT="#5AA9FF"; ACCENT_SOFT="#7DB8FF"; GREEN="#31C48D"; ORANGE="#F59E0B"; RED="#F87171"; RED_DARK="#7F1D1D"
PURPLE="#A78BFA"; PINK="#F472B6"; CYAN="#22D3EE"; YELLOW="#FBBF24"
COLORES_ESTADO={"Trabajando":"#388BFD","CRC":"#F59E0B","Disponible":"#31C48D",
    "Enfriando":"#22D3EE","A rectificar":"#F87171","Rectificando":"#A78BFA","Baja":"#66758A"}
SS_COLORS=["#5AA9FF","#F59E0B","#31C48D","#F472B6"]
JAULA_COLORS=["#5AA9FF","#F59E0B","#31C48D","#F472B6"]
TIPO_RECT_COLORS={"produccion":"#31C48D","desbaste":"#F59E0B"}
FONT_FAMILY="Segoe UI"; FONT_MONO="Cascadia Code"
FONT_SIZE_SM=9; FONT_SIZE=10; FONT_SIZE_MD=11; FONT_SIZE_LG=13; FONT_SIZE_XL=15; FONT_SIZE_KPI=28
TAB_BG="#162133"; TAB_FG="#C7D2FE"; TAB_SEL_BG="#5AA9FF"; TAB_SEL_FG="#FFFFFF"; TAB_PADDING=[14,8]
BTN_BG="#1F8F5F"; BTN_BG_HOVER="#2BB46B"; BTN_BLUE="#2563EB"; BTN_BLUE_HOVER="#3B82F6"
TABLE_ROW_COLORS={"Trabajando":"#11253D","CRC":"#2A1E07","Disponible":"#11291D",
    "Enfriando":"#0A2E33","A_rectificar":"#2A0D0D","Rectificando":"#241336","Baja":"#151A22"}

# ── Paleta del Dashboard (1 a 1 con html_ref.html) ───────────────────────────
# El mockup de referencia usa tonos propios, ligeramente distintos de los de
# arriba; se centralizan acá para que los widgets del dashboard no hardcodeen hex.
DASH_CARD_BG="#1A1F26"; DASH_CARD_BORDER="#2B333D"; DASH_TITLE="#E8A13A"
DASH_TRACK="#11151A"; DASH_AXIS="#2B333D"; DASH_TICK="#59616B"; DASH_TICK_TEXT="#8B939D"
DASH_CURSOR="#E8A13A"; DASH_LEGEND_TEXT="#CFD5DC"; DASH_GRID="#FFFFFF"
DASH_GREEN="#35C98A"; DASH_DISP="#66BB6A"; DASH_ORANGE="#F0A32E"; DASH_PURPLE="#B08CF5"
DASH_PARADA="#7F1D1D"; DASH_PARADA_BAND="#F56B6B"
# Colores por estado para el área apilada (matchean el mockup; ver Vista Real).
COLORES_ESTADO_DASH={"Trabajando":"#4A9EFF","CRC":"#F0A32E","Disponible":"#35C98A",
    "Enfriando":"#34D3E0","A rectificar":"#F56B6B","Rectificando":"#B08CF5","Baja":"#66758A"}
# Tipo de rectificado en el Gantt del dashboard.
TIPO_RECT_COLORS_DASH={"produccion":"#35C98A","desbaste":"#F0A32E"}
