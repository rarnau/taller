"""Panel Dashboard para la GUI Qt — nativo (sin Matplotlib), 1 a 1 con html_ref.

Reemplaza el antiguo dashboard de Matplotlib embebido por un grid 2×2 de
:class:`DashboardCard` con widgets dibujados con QPainter
(``gui_qt/widgets/dashboard_charts_qt``). Las cards se muestran **siempre**
(también sin simular: vacías, con su título y leyenda) y ``render(taller)``
sólo les pasa datos. Las series salen de ``gui_qt.dashboard_data`` (que a su vez
usa ``modelos.kpis.calcular_kpis``).
"""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget

from config import tema
from gui_qt.dashboard_data import extraer_datos_dashboard
from gui_qt.widgets.dashboard_card_qt import DashboardCard
from gui_qt.widgets.dashboard_charts_qt import (BufferChart, GanttChart,
                                                GroupedBarChart,
                                                StackedAreaChart)


class DashboardPanel(QWidget):
    """Dashboard nativo: evolución de estados, buffer, utilización y Gantt."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._grid_host = QWidget()
        host_box = QVBoxLayout(self._grid_host)
        host_box.setContentsMargins(2, 2, 2, 2)
        host_box.setSpacing(0)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        host_box.addLayout(self.grid)
        host_box.addStretch(1)  # cards al tope, el sobrante queda debajo (como el HTML).
        self.scroll.setWidget(self._grid_host)
        self._root.addWidget(self.scroll)

        # Gráficos (se crean una vez; render() les pasa datos).
        self.chart_estados = StackedAreaChart()
        self.chart_estados.setMaximumHeight(300)
        self.chart_buffer = BufferChart()
        self.chart_buffer.setMaximumHeight(300)
        self.chart_util = GroupedBarChart()
        self.chart_gantt = GanttChart()

        self._build_cards()
        # Arranca vacío: las cards quedan visibles para anticipar qué se mostrará.

    # ── Construcción de las tarjetas ────────────────────────────────────────
    def _build_cards(self) -> None:
        self.card_estados = DashboardCard("Evolución temporal de estados")
        self.card_estados.add_content(self.chart_estados)

        self.card_buffer = DashboardCard("Buffer de seguridad global")
        self.card_buffer.add_content(self.chart_buffer)
        self.card_buffer.set_legend([
            (tema.DASH_GREEN, "Disp + CRC"),
            (tema.DASH_DISP, "Disponible"),
            (tema.DASH_ORANGE, "CRC"),
        ])

        self.card_util = DashboardCard("Utilización de máquinas — Disponible vs Neta")
        self.card_util.add_content(self.chart_util)
        self.card_util.set_legend([
            (tema.DASH_GREEN, "Disponible"),
            (tema.DASH_PURPLE, "Neta"),
        ])

        self.card_gantt = DashboardCard("Cronograma de rectificado")
        self.card_gantt.add_content(self.chart_gantt)
        self.card_gantt.set_legend([
            (tema.TIPO_RECT_COLORS_DASH["produccion"], "Producción"),
            (tema.TIPO_RECT_COLORS_DASH["desbaste"], "Desbaste"),
            (tema.DASH_PARADA, "Parada (turno)"),
            (tema.DASH_FALLA, "Falla"),
        ])

        self.grid.addWidget(self.card_estados, 0, 0)
        self.grid.addWidget(self.card_buffer, 0, 1)
        self.grid.addWidget(self.card_util, 1, 0)
        self.grid.addWidget(self.card_gantt, 1, 1)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

    # ── API consumida por MainWindow ────────────────────────────────────────
    def render(self, taller) -> None:
        """Reconstruye el dashboard para el taller actual (o lo deja vacío)."""
        if taller is None or not getattr(taller, "snapshots", None):
            self._set_empty()
            return

        data = extraer_datos_dashboard(taller)
        self.chart_estados.set_data(
            data.tiempos, data.estados, data.series_estado, data.colores_estado
        )
        self.chart_buffer.set_data(
            data.tiempos, data.disponibles, data.crc, data.buffer
        )
        self.chart_util.set_data(data.maquinas, data.util_disponible, data.util_neta)
        self.chart_gantt.set_data(
            data.maquinas, data.gantt, data.paradas_turno,
            data.t0, data.t1, tema.TIPO_RECT_COLORS_DASH, data.tramos_falla,
        )
        self.set_cursor(0, len(data.tiempos))

    def _set_empty(self) -> None:
        """Vacía los gráficos dejando las cards (título + leyenda + área vacía)."""
        self.chart_estados.set_data([], [], {}, {})
        self.chart_buffer.set_data([], [], [], [])
        self.chart_util.set_data([], {}, {})
        self.chart_gantt.set_data([], {}, {}, None, None, {})

    def set_cursor(self, idx: int, total: int) -> None:
        """Marca el snapshot actual con el cursor del replay en los gráficos temporales."""
        if total <= 1:
            frac: float | None = 0.0
        else:
            frac = max(0.0, min(1.0, idx / (total - 1)))
        self.chart_estados.set_cursor_frac(frac)
        self.chart_buffer.set_cursor_frac(frac)
        self.chart_gantt.set_cursor_frac(frac)
