"""Pestaña KPIs para la GUI Qt."""

from __future__ import annotations

from typing import Dict

from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from config import tema as tk_theme
from modelos.kpis import calcular_kpis


def _mix(c1: str, c2: str, t: float) -> str:
    """Interpola linealmente dos colores hex para gradientes de tarjetas."""
    a = [int(c1[i : i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i : i + 2], 16) for i in (1, 3, 5)]
    rgb = [round(a[i] + (b[i] - a[i]) * max(0.0, min(1.0, t))) for i in range(3)]
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _color_util(pct: float) -> str:
    """Mapa 0-100% a gradiente rojo->amarillo->verde."""
    t = max(0.0, min(1.0, pct / 100.0))
    if t < 0.5:
        return _mix(tk_theme.RED, tk_theme.YELLOW, t / 0.5)
    return _mix(tk_theme.YELLOW, tk_theme.GREEN, (t - 0.5) / 0.5)


class KpiCard(QFrame):
    """Tarjeta visual reutilizable para KPI numerico o textual."""

    def __init__(self, title: str, value: str, color: str) -> None:
        super().__init__()
        self.setObjectName("KpiCard")
        self.setStyleSheet(
            f"QFrame#KpiCard {{border: 1px solid {color}; border-radius: 10px; "
            f"background-color: {_mix(color, tk_theme.BG_CARD, 0.88)};}}"
        )

        col = QVBoxLayout(self)
        col.setContentsMargins(10, 10, 10, 10)
        col.setSpacing(5)

        t = QLabel(title.upper())
        t.setObjectName("Muted")
        v = QLabel(value)
        v.setStyleSheet(f"color: {color}; font-size: {tk_theme.FONT_SIZE_XL + 4}px; font-weight: 700;")

        col.addWidget(t)
        col.addWidget(v)


class KpisPanel(QWidget):
    """Panel reutilizable de KPIs para incrustar en la tab Qt."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(10)

        self.banner = QLabel("Se mostraran datos una vez corrida la simulacion")
        self.banner.setObjectName("Muted")
        self.root.addWidget(self.banner)

        self.general_grid = QGridLayout()
        self.general_grid.setHorizontalSpacing(10)
        self.general_grid.setVerticalSpacing(10)
        self.root.addLayout(self.general_grid)

        self.util_title = QLabel("UTILIZACION DISPONIBLE / NETA")
        self.util_title.setObjectName("SectionTitle")
        self.root.addWidget(self.util_title)

        self.util_grid = QGridLayout()
        self.util_grid.setHorizontalSpacing(10)
        self.util_grid.setVerticalSpacing(10)
        self.root.addLayout(self.util_grid)

    def render(self, taller) -> None:
        """Renderiza KPIs generales y de utilizacion para el taller actual."""
        # Limpieza completa de widgets previos para un rerender estable.
        for layout in (self.general_grid, self.util_grid):
            while layout.count():
                item = layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        if taller is None or not getattr(taller, "snapshots", None):
            self.banner.setVisible(True)
            return
        self.banner.setVisible(False)

        k = calcular_kpis(taller)

        # Bloque de KPIs globales (estado de inventario y horizonte).
        rows = [
            ("Cilindros Totales", str(k["cilindros_totales"]), tk_theme.ACCENT),
            ("Activos", str(k["activos"]), tk_theme.GREEN),
            ("Bajas", str(k["bajas"]), tk_theme.RED if k["bajas"] else tk_theme.GREEN),
            (
                "Alertas Criticas",
                str(k["alertas_criticas"]),
                tk_theme.RED if k["alertas_criticas"] else tk_theme.GREEN,
            ),
            ("Cambios Programados", str(k["cambios_programados"]), tk_theme.ORANGE),
            ("Rectificados", str(k["rectificados_realizados"]), tk_theme.PURPLE),
            ("Horizonte (h)", f"{k['horizonte_simulacion_h']:.1f}", tk_theme.CYAN),
            ("Diametro Promedio", f"{k['diametro_promedio_mm']:.1f} mm", tk_theme.YELLOW),
            ("Desgaste Medio", f"{k['desgaste_medio_mm']:.2f} mm", "#F97316"),
        ]

        for idx, (title, value, color) in enumerate(rows):
            r, c = divmod(idx, 3)
            self.general_grid.addWidget(KpiCard(title, value, color), r, c)

        # Bloque de utilizacion por maquina (disponible vs neta).
        self._render_utilizacion(
            k.get("utilizacion_maquinas_pct", {}),
            k.get("utilizacion_neta_pct", {}),
        )

    def _render_utilizacion(self, disp: Dict[str, float], neta: Dict[str, float]) -> None:
        """Pinta tarjetas por maquina combinando utilizacion disponible y neta."""
        names = list(disp) or list(neta)
        for idx, name in enumerate(names):
            d = float(disp.get(name, 0.0))
            n = float(neta.get(name, 0.0))
            color = _color_util((d + n) / 2.0)
            label = f"{name}\nDisp: {d:.0f}% | Neta: {n:.0f}%"
            r, c = divmod(idx, 3)
            self.util_grid.addWidget(KpiCard("Maquina", label, color), r, c)
