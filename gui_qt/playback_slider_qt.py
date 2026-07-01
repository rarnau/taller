"""Slider de reproducción con marcadores clickeables de PARADA."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygon
from PySide6.QtWidgets import QSlider, QStyle, QStyleOptionSlider, QWidget


class PlaybackTimelineSlider(QSlider):
    """Slider de reproducción con marcadores de PARADA dibujados sobre la barra."""

    marker_clicked = Signal(int)
    _CLICK_RADIUS_PX = 14
    _HOVER_RADIUS_PX = 14

    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._indices: list[int] = []
        self._ratios: list[float] = []
        self.setMouseTracking(True)

    def set_markers(self, indices: list[int], total: int) -> None:
        if total <= 1 or not indices:
            self._indices = []
            self._ratios = []
        else:
            self._indices = list(indices)
            self._ratios = [max(0.0, min(1.0, idx / (total - 1))) for idx in indices]
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._ratios and self._indices:
            nearest, min_dist = self._nearest_marker(event.position().x())
            # Zona magnética alrededor del marcador para facilitar el click.
            if nearest >= 0 and min_dist <= self._CLICK_RADIUS_PX:
                self.marker_clicked.emit(self._indices[nearest])
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        nearest, min_dist = self._nearest_marker(event.position().x())
        if nearest >= 0 and min_dist <= self._HOVER_RADIUS_PX:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.unsetCursor()
        super().leaveEvent(event)

    def _nearest_marker(self, x_pos: float) -> tuple[int, int]:
        if not self._indices:
            return -1, 10_000

        nearest = -1
        min_dist = 10_000
        for i, idx in enumerate(self._indices):
            x = self._x_for_value(idx)
            if x < 0:
                continue
            d = abs(int(round(x_pos)) - x)
            if d < min_dist:
                min_dist = d
                nearest = i
        return nearest, min_dist

    def _x_for_value(self, value: int) -> int:
        """Devuelve la X del centro del handle para un valor dado del slider."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        opt.sliderPosition = int(value)
        opt.sliderValue = int(value)
        handle = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )
        if not handle.isValid():
            return -1
        return handle.center().x()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if not self._indices:
            return

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        groove = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )
        if groove.width() <= 1:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#F56B6B"))
        y_top = max(0, groove.top() - 8)
        y_tip = max(0, groove.top() - 2)
        for idx in self._indices:
            x = self._x_for_value(idx)
            if x < 0:
                continue
            tri = QPolygon(
                [
                    QPoint(x - 4, y_top),
                    QPoint(x + 4, y_top),
                    QPoint(x, y_tip),
                ]
            )
            p.drawPolygon(tri)
