"""Panel de Análisis para la GUI Qt (nativo, sin Matplotlib)."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget

from config import tema
from gui_qt.analysis_data import EMPTY_ANALYSIS_DATA, extraer_datos_analisis
from gui_qt.widgets.analysis_charts_qt import (
    CylinderMapChart,
    DiameterDistributionChart,
    SubstockEvolutionChart,
)
from gui_qt.widgets.dashboard_card_qt import DashboardCard


class AnalysisPanel(QWidget):
    """Panel Análisis nativo: mapa, distribución y evolución de SubStock."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._grid_host = QWidget()
        host_box = QVBoxLayout(self._grid_host)
        host_box.setContentsMargins(2, 2, 2, 2)
        host_box.setSpacing(0)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        host_box.addLayout(self.grid)
        host_box.addStretch(1)
        self.scroll_area.setWidget(self._grid_host)
        self._root.addWidget(self.scroll_area)

        self.chart_map = CylinderMapChart()
        self.chart_dist = DiameterDistributionChart()
        self.chart_substock = SubstockEvolutionChart()

        self._build_cards()
        self._set_empty()

    def _build_cards(self) -> None:
        self.card_map = DashboardCard("Mapa de cilindros - estado final vs diametro")
        self.card_map.add_content(self.chart_map)

        self.card_dist = DashboardCard("Distribucion de diametros (activos)")
        self.card_dist.add_content(self.chart_dist)

        self.card_substock = DashboardCard("Evolucion de SubStock (disponibles)")
        self.card_substock.add_content(self.chart_substock)
        self.card_substock.set_legend([
            (tema.DASH_PARADA_BAND, "Jaula(s) parada(s)"),
        ])

        self.grid.addWidget(self.card_map, 0, 0, 1, 2)
        self.grid.addWidget(self.card_dist, 1, 0)
        self.grid.addWidget(self.card_substock, 1, 1)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

    def render(self, taller, stock_df=None) -> None:
        """Reconstruye el panel de análisis con el taller actual."""
        if taller is None or not getattr(taller, "snapshots", None):
            self._set_empty()
            return

        data = extraer_datos_analisis(taller, stock_df)
        self.chart_map.set_data(data)
        self.chart_dist.set_data(data)
        self.chart_substock.set_data(data)
        legend = [
            (data.colores_substock[nombre], f"J{ss.jaula_asignada}")
            for ss in taller.lista_substocks
            for nombre in [ss.nombre]
            if nombre in data.colores_substock
        ]
        legend.append((tema.DASH_PARADA_BAND, "Jaula(s) parada(s)"))
        self.card_substock.set_legend(legend)
        self.set_cursor(0, len(data.tiempos))

    def _set_empty(self) -> None:
        self.chart_map.set_data(EMPTY_ANALYSIS_DATA)
        self.chart_dist.set_data(EMPTY_ANALYSIS_DATA)
        self.chart_substock.set_data(EMPTY_ANALYSIS_DATA)
        self.card_substock.set_legend([(tema.DASH_PARADA_BAND, "Jaula(s) parada(s)")])

    def set_cursor(self, idx: int, total: int) -> None:
        if total <= 1:
            frac: float | None = 0.0
        else:
            frac = max(0.0, min(1.0, idx / (total - 1)))
        self.chart_map.set_snapshot_index(idx)
        self.chart_substock.set_cursor_frac(frac)
