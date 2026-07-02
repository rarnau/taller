"""Histograma nativo con líneas P10/P50/P90 (usado en el panel Monte Carlo)."""

from __future__ import annotations

from typing import List

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from config import tema


class HistogramWidget(QWidget):
    """Histograma simple con líneas P10/P50/P90 (pintado nativo)."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._vals: np.ndarray = np.array([], dtype=float)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, valores: List[float]) -> None:
        self._vals = np.array([float(v) for v in valores], dtype=float)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        base = h - 18
        if self._vals.size == 0:
            p.setPen(QColor(tema.FG_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "sin datos")
            return

        lo, hi = float(self._vals.min()), float(self._vals.max())
        nbins = 12
        if hi <= lo:  # todos iguales: una sola barra centrada
            self._barra_unica(p, w, base)
        else:
            counts, edges = np.histogram(self._vals, bins=nbins, range=(lo, hi))
            cmax = max(int(counts.max()), 1)
            bw = w / nbins
            col = QColor(self._color)
            col.setAlpha(205)
            for i, c in enumerate(counts):
                bh = (c / cmax) * (base - 4)
                p.fillRect(int(i * bw) + 1, int(base - bh),
                           max(1, int(bw) - 2), int(bh), col)
            for pct, color in ((10, tema.ACCENT), (50, tema.ACCENT), (90, tema.GREEN)):
                x = (np.percentile(self._vals, pct) - lo) / (hi - lo) * w
                pen = QPen(QColor(color))
                pen.setWidth(2)
                p.setPen(pen)
                p.drawLine(int(x), 0, int(x), int(base))

        # Ejes mínimos y rótulos de extremos.
        p.setPen(QColor(tema.DASH_AXIS))
        p.drawLine(0, int(base), w, int(base))
        p.setPen(QColor(tema.DASH_TICK_TEXT))
        p.drawText(2, h - 4, f"{lo:.1f}")
        p.drawText(w - 48, h - 4, f"{hi:.1f}")

    def _barra_unica(self, p: QPainter, w: int, base: int) -> None:
        col = QColor(self._color)
        col.setAlpha(205)
        p.fillRect(int(w * 0.42), 4, int(w * 0.16), base - 4, col)
