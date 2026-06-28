"""Timeline nativa Qt para la pestaña Generación."""

from __future__ import annotations

from datetime import datetime
from typing import List, Tuple

import pandas as pd
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from config import tema


class GenerationTimelineChart(QWidget):
    """Timeline de cambios: líneas por evento + marcadores de PARADA."""

    snapshotSelected = Signal(int)

    _TOP = 12
    _BOTTOM = 22
    _PAD_X = 2
    _SAME_TIME_GAP_PX = 3.5

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(100)
        self._rows: list[tuple[datetime, int]] = []
        self._t_min: datetime | None = None
        self._t_max: datetime | None = None
        self._msg: str | None = "Sin cambios"
        self._parada_marks: list[tuple[datetime, int]] = []

    def set_data(
        self,
        rows: list[tuple[datetime, int]],
        t_min: datetime | None,
        t_max: datetime | None,
        parada_marks: list[tuple[datetime, int]] | None = None,
        msg: str | None = None,
    ) -> None:
        self._rows = rows
        self._t_min = t_min
        self._t_max = t_max
        self._parada_marks = list(parada_marks or [])
        self._msg = msg
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self._PAD_X,
            self._TOP,
            max(1.0, self.width() - 2 * self._PAD_X),
            max(1.0, self.height() - self._TOP - self._BOTTOM),
        )

    def _x_of(self, t: datetime, r: QRectF) -> float:
        if self._t_min is None or self._t_max is None:
            return r.left() + r.width() / 2
        span = (self._t_max - self._t_min).total_seconds()
        if span <= 0:
            return r.left() + r.width() / 2
        frac = max(0.0, min(1.0, (t - self._t_min).total_seconds() / span))
        return r.left() + frac * r.width()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot_rect()

        # Fondo del área de timeline.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1a1f26"))
        p.drawRoundedRect(r, 4, 4)

        if not self._rows or self._t_min is None or self._t_max is None:
            p.setPen(QPen(QColor("#9aa3b2")))
            p.setFont(QFont(tema.FONT_FAMILY, 9))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._msg or "Sin cambios")
            p.end()
            return

        # Barras verticales por cambio. Si hay varios cambios en el mismo instante,
        # se separan en píxeles para que no se solapen visualmente.
        grouped: dict[datetime, list[int]] = {}
        for t, jaula in self._rows:
            grouped.setdefault(t, []).append(jaula)

        for t, jaulas in grouped.items():
            x0 = self._x_of(t, r)
            n = len(jaulas)
            for i, jaula in enumerate(jaulas):
                offset_px = (i - (n - 1) / 2.0) * self._SAME_TIME_GAP_PX
                x = x0 + offset_px
                color = QColor(tema.JAULA_COLORS[(max(1, int(jaula)) - 1) % len(tema.JAULA_COLORS)])
                pen = QPen(color, 1.6)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

        # Marcadores de inicio de PARADA (triángulos arriba).
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(tema.DASH_PARADA_BAND))
        for t, _idx in self._parada_marks:
            x = self._x_of(t, r)
            tri = QPolygonF([
                QPointF(x, r.top() - 2),
                QPointF(x - 4, r.top() - 8),
                QPointF(x + 4, r.top() - 8),
            ])
            p.drawPolygon(tri)

        # Ticks de tiempo abajo.
        p.setFont(QFont(tema.FONT_MONO, 7))
        p.setPen(QPen(QColor("#3a4250"), 1))
        n = 6
        for i in range(n):
            frac = i / (n - 1)
            x = r.left() + frac * r.width()
            p.drawLine(QPointF(x, r.bottom()), QPointF(x, r.bottom() + 4))
            t = self._t_min + (self._t_max - self._t_min) * frac
            lbl = t.strftime("%d/%m %H:%M")
            p.setPen(QPen(QColor("#9aa3b2")))
            p.drawText(QRectF(x - 34, r.bottom() + 5, 68, 14), Qt.AlignmentFlag.AlignHCenter, lbl)
            p.setPen(QPen(QColor("#3a4250"), 1))

        p.end()

    def mousePressEvent(self, event) -> None:
        if self._t_min is None or self._t_max is None or not self._parada_marks:
            return super().mousePressEvent(event)
        r = self._plot_rect()
        x_click = float(event.position().x())
        y_click = float(event.position().y())
        if y_click > r.top() + 4:
            return super().mousePressEvent(event)
        for t, idx in self._parada_marks:
            x = self._x_of(t, r)
            if abs(x_click - x) <= 6:
                self.snapshotSelected.emit(int(idx))
                return
        super().mousePressEvent(event)
