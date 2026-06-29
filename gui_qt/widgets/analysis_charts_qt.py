"""Widgets QPainter para la pestaña Análisis (1 a 1 con html_ref)."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from config import tema
from gui_qt.analysis_data import AnalysisData, EMPTY_ANALYSIS_DATA, HistogramBin
from gui_qt.widgets.dashboard_charts_qt import _fmt_fecha, _qc, _t_frac


class CylinderMapChart(QWidget):
    """Mapa de cilindros: estado (carril Y) vs diámetro (X)."""

    _LEFT = 94
    _RIGHT = 6
    _TOP = 8
    _BOTTOM = 26
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(230)
        self._data = EMPTY_ANALYSIS_DATA
        self._snapshot_index = -1

    def set_data(self, data: AnalysisData) -> None:
        self._data = data
        self._snapshot_index = -1
        self.update()

    def set_snapshot_index(self, idx: int) -> None:
        self._snapshot_index = max(-1, idx)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(
            self._LEFT,
            self._TOP,
            max(1.0, self.width() - self._LEFT - self._RIGHT),
            max(1.0, self.height() - self._TOP - self._BOTTOM),
        )

        estados = list(self._data.estados)
        if not estados:
            p.end()
            return

        lo = min(self._data.diametro_minimo, self._data.dist_min)
        hi = max(self._data.diametro_maximo, self._data.dist_max)
        if hi <= lo:
            hi = lo + 1.0
        # Margen para que los puntos no queden pegados en extremos del eje.
        span = hi - lo
        lo -= span * tema.ANALYSIS_MAP_X_MARGIN_RATIO
        hi += span * tema.ANALYSIS_MAP_X_MARGIN_RATIO

        def x_of(diam: float) -> float:
            return r.left() + ((diam - lo) / (hi - lo)) * r.width()

        n = len(estados)
        lane_h = r.height() / n
        y_by_state: Dict[str, float] = {}
        for i, estado in enumerate(estados):
            cy = r.top() + (i + 0.5) * lane_h
            y_by_state[estado] = cy
            p.setPen(QPen(_qc("#232A33"), 1))
            p.drawLine(QPointF(r.left(), cy), QPointF(r.right(), cy))
            p.setPen(QPen(_qc(tema.COLORES_ESTADO_DASH.get(estado, tema.DASH_TICK_TEXT))))
            p.setFont(QFont(tema.FONT_FAMILY, 9))
            p.drawText(QRectF(0, cy - 7, self._LEFT - 8, 14), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, estado)

        if self._data.mapa_puntos_por_snapshot and self._snapshot_index >= 0:
            i = min(self._snapshot_index, len(self._data.mapa_puntos_por_snapshot) - 1)
            puntos = self._data.mapa_puntos_por_snapshot[i]
        else:
            puntos = self._data.mapa_puntos

        puntos_por_estado: Dict[str, List[float]] = {estado: [] for estado in estados}
        for diam, estado in puntos:
            if estado in puntos_por_estado:
                puntos_por_estado[estado].append(x_of(diam))

        for estado in estados:
            base_y = y_by_state.get(estado)
            if base_y is None:
                continue
            xs = sorted(puntos_por_estado.get(estado, []))
            if not xs:
                continue

            # Fallback visual para densidad extrema en BAJA: banda de densidad por bins.
            if estado == "Baja" and len(xs) >= tema.ANALYSIS_MAP_BAJA_DENSITY_THRESHOLD:
                bins: Dict[int, int] = {}
                for cx in xs:
                    b = int((cx - r.left()) / tema.ANALYSIS_MAP_COLLISION_BIN_PX)
                    bins[b] = bins.get(b, 0) + 1
                max_count = max(bins.values()) if bins else 1
                for b, count in bins.items():
                    x0 = r.left() + b * tema.ANALYSIS_MAP_COLLISION_BIN_PX
                    w = max(2.0, tema.ANALYSIS_MAP_COLLISION_BIN_PX - 1.0)
                    h = 2.0 + min(10.0, (count / max_count) * 10.0)
                    alpha = 90 + int((count / max_count) * 140)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(_qc(tema.COLORES_ESTADO_DASH.get(estado, "#999999"), alpha)))
                    p.drawRoundedRect(QRectF(x0, base_y - h / 2.0, w, h), 1.6, 1.6)
                continue

            # Evita solapes apilando verticalmente puntos que caen en el mismo bin X.
            bins: Dict[int, int] = {}
            dense_state = len(xs) >= tema.ANALYSIS_MAP_DENSE_STATE_THRESHOLD
            for cx in xs:
                b = int((cx - r.left()) / tema.ANALYSIS_MAP_COLLISION_BIN_PX)
                idx = bins.get(b, 0)
                bins[b] = idx + 1
                if idx == 0:
                    rank = 0
                else:
                    k = (idx + 1) // 2
                    rank = k if idx % 2 == 1 else -k
                cy = base_y + rank * tema.ANALYSIS_MAP_STACK_STEP_PX
                cy = max(r.top() + 3.5, min(r.bottom() - 3.5, cy))

                p.setPen(QPen(_qc("#12161B"), 0.7 if dense_state else 0.9))
                alpha = tema.ANALYSIS_MAP_DENSE_POINT_ALPHA if dense_state else tema.ANALYSIS_MAP_POINT_ALPHA
                p.setBrush(QBrush(_qc(tema.COLORES_ESTADO_DASH.get(estado, "#999999"), alpha)))
                rx = tema.ANALYSIS_MAP_DENSE_POINT_RX if dense_state else tema.ANALYSIS_MAP_POINT_RX
                ry = tema.ANALYSIS_MAP_DENSE_POINT_RY if dense_state else tema.ANALYSIS_MAP_POINT_RY
                p.drawEllipse(QRectF(cx - rx, cy - ry, rx * 2.0, ry * 2.0))

        ticks = 5
        p.setFont(QFont(tema.FONT_MONO, 8))
        p.setPen(QPen(_qc(tema.DASH_TICK_TEXT)))
        for i in range(ticks):
            frac = i / max(1, ticks - 1)
            x = r.left() + frac * r.width()
            label = f"{lo + frac * (hi - lo):.0f}"
            p.drawText(QRectF(x - 20, r.bottom() + 4, 40, 16), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, label)

        p.end()


class DiameterDistributionChart(QWidget):
    """Distribución de diámetros activos con zonas de SubStock."""

    _TOP = 18
    _BOTTOM = 28
    _PAD_X = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(190)
        self._data = EMPTY_ANALYSIS_DATA

    def set_data(self, data: AnalysisData) -> None:
        self._data = data
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(
            self._PAD_X,
            self._TOP,
            max(1.0, self.width() - 2 * self._PAD_X),
            max(1.0, self.height() - self._TOP - self._BOTTOM),
        )

        bins = self._data.dist_bins
        lo = min(self._data.diametro_minimo, self._data.dist_min)
        hi = max(self._data.diametro_maximo, self._data.dist_max)
        if hi <= lo:
            hi = lo + 1.0

        def x_of(diam: float) -> float:
            return r.left() + ((diam - lo) / (hi - lo)) * r.width()

        for label, hasta, desde, color in self._data.zonas_substock:
            x0 = x_of(hasta)
            x1 = x_of(desde)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_qc(color, 26)))
            p.drawRect(QRectF(min(x0, x1), r.top(), abs(x1 - x0), r.height()))

            top_rect = QRectF(min(x0, x1), max(0.0, r.top() - 14.0), abs(x1 - x0), 14)
            p.setBrush(QBrush(_qc(color, 160)))
            p.drawRoundedRect(top_rect, 2, 2)
            p.setPen(QPen(_qc("#0B0F14")))
            p.setFont(QFont(tema.FONT_FAMILY, 7))
            p.drawText(top_rect, Qt.AlignmentFlag.AlignCenter, label)

        max_count = max((b.count for b in bins), default=1)
        for b in bins:
            if b.right <= b.left:
                continue
            x0 = x_of(b.left)
            x1 = x_of(b.right)
            h = (b.count / max_count) * r.height()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_qc(tema.ACCENT, 220)))
            p.drawRoundedRect(QRectF(x0 + 1, r.bottom() - h, max(1.0, x1 - x0 - 2), h), 3, 3)

        p.setPen(QPen(_qc(tema.DASH_PARADA_BAND), 2, Qt.PenStyle.DashLine))
        x_min = x_of(self._data.diametro_minimo)
        p.drawLine(QPointF(x_min, r.top()), QPointF(x_min, r.bottom()))

        p.setPen(QPen(_qc(tema.DASH_GREEN), 2, Qt.PenStyle.DashLine))
        x_max = x_of(self._data.diametro_maximo)
        p.drawLine(QPointF(x_max, r.top()), QPointF(x_max, r.bottom()))

        p.setFont(QFont(tema.FONT_MONO, 8))
        p.setPen(QPen(_qc(tema.DASH_PARADA_BAND)))
        p.drawText(QRectF(r.left(), r.bottom() + 3, 120, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, f"min {self._data.diametro_minimo:.0f}")
        p.setPen(QPen(_qc(tema.DASH_GREEN)))
        p.drawText(QRectF(r.right() - 120, r.bottom() + 3, 120, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, f"max {self._data.diametro_maximo:.0f}")

        p.end()


class SubstockEvolutionChart(QWidget):
    """Evolución temporal de disponibles por SubStock."""

    _AXIS_H = 22
    _TOP = 6
    _PAD_X = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(190)
        self._data = EMPTY_ANALYSIS_DATA
        self._cursor_frac: float | None = None

    def set_data(self, data: AnalysisData) -> None:
        self._data = data
        self.update()

    def set_cursor_frac(self, frac: float | None) -> None:
        self._cursor_frac = frac
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(
            self._PAD_X,
            self._TOP,
            max(1.0, self.width() - 2 * self._PAD_X),
            max(1.0, self.height() - self._TOP - self._AXIS_H),
        )

        tiempos = self._data.tiempos
        if len(tiempos) < 2:
            p.setPen(QPen(_qc(tema.DASH_AXIS), 1.5))
            p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))
            p.end()
            return

        t0, t1 = tiempos[0], tiempos[-1]

        def x_of(t: datetime) -> float:
            return r.left() + _t_frac(t, t0, t1) * r.width()

        all_vals = [v for serie in self._data.evol_substock.values() for v in serie]
        ymax = max(all_vals) if all_vals else 1
        ymax = max(1, ymax)

        def y_of(v: float) -> float:
            return r.bottom() - (v / ymax) * r.height()

        for ini, fin in self._data.paradas:
            x0 = x_of(ini)
            x1 = x_of(fin)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_qc(tema.DASH_PARADA_BAND, 30)))
            p.drawRect(QRectF(min(x0, x1), r.top(), abs(x1 - x0), r.height()))

        for nombre, serie in self._data.evol_substock.items():
            if not serie:
                continue
            pen = QPen(_qc(self._data.colores_substock.get(nombre, "#999999")), 2.4)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            prev_x = x_of(tiempos[0])
            prev_y = y_of(serie[0])
            for i in range(1, min(len(tiempos), len(serie))):
                cx = x_of(tiempos[i])
                cy = y_of(serie[i])
                p.drawLine(QPointF(prev_x, prev_y), QPointF(cx, prev_y))
                p.drawLine(QPointF(cx, prev_y), QPointF(cx, cy))
                prev_x, prev_y = cx, cy

        axis_y = r.bottom()
        p.setPen(QPen(_qc(tema.DASH_AXIS), 1.5))
        p.drawLine(QPointF(r.left(), axis_y), QPointF(r.right(), axis_y))

        span_days = (t1 - t0).total_seconds() / 86400.0
        p.setFont(QFont(tema.FONT_MONO, 8))
        fm = p.fontMetrics()
        n = 6
        for i in range(n):
            frac = i / (n - 1)
            x = r.left() + frac * r.width()
            p.setPen(QPen(_qc(tema.DASH_TICK), 1))
            p.drawLine(QPointF(x, axis_y), QPointF(x, axis_y + 6))
            label = _fmt_fecha(t0 + (t1 - t0) * frac, span_days)
            tw = fm.horizontalAdvance(label)
            tx = x if i == 0 else (x - tw if i == n - 1 else x - tw / 2)
            p.setPen(QPen(_qc(tema.DASH_TICK_TEXT)))
            p.drawText(QPointF(tx, axis_y + 8 + fm.ascent()), label)

        if self._cursor_frac is not None:
            cx = r.left() + self._cursor_frac * r.width()
            p.setPen(QPen(_qc(tema.DASH_CURSOR, 210), 2))
            p.drawLine(QPointF(cx, r.top()), QPointF(cx, r.bottom()))

        p.end()
