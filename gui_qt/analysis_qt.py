"""Panel de Analisis para la GUI Qt."""

from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QVBoxLayout, QWidget

from config import tema as tk_theme
from gui.dashboard_detalle import crear_dashboard_detalle


class AnalysisPanel(QWidget):
    """Contenedor Qt para el dashboard de analisis (detalle)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._fig: Figure | None = None
        self._canvas: FigureCanvasQTAgg | None = None

        # Evita colisionar con QWidget.layout() y mantiene tipado correcto.
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.render(None)

    def render(self, taller) -> None:
        """Renderiza el analisis para el taller actual."""
        self._clear_canvas()

        if taller is None:
            fig = Figure(figsize=(12, 8), facecolor=tk_theme.BG2)
            fig.text(
                0.5,
                0.5,
                "Se mostraran datos una vez corrida la simulacion",
                ha="center",
                va="center",
                color=tk_theme.FG2,
                fontsize=16,
                fontweight="bold",
            )
            self._fig = fig
        else:
            self._fig = crear_dashboard_detalle(taller)

        self._canvas = FigureCanvasQTAgg(self._fig)
        self.main_layout.addWidget(self._canvas)
        self._canvas.draw_idle()

    def _clear_canvas(self) -> None:
        """Elimina canvas/figura previa para evitar fugas entre rerenders."""
        if self._canvas is not None:
            self.main_layout.removeWidget(self._canvas)
            self._canvas.setParent(None)
            self._canvas.deleteLater()
            self._canvas = None
        if self._fig is not None:
            self._fig.clear()
            self._fig = None
