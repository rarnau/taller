"""Widgets de gráficos del Dashboard (QPainter), fieles a ``html_ref.html``.

Replican con dibujo nativo lo que el mockup hace con SVG/divs:

- :class:`StackedAreaChart` — evolución temporal de estados (área apilada).
- :class:`BufferChart` — buffer de seguridad global (área + líneas).
- :class:`GroupedBarChart` — utilización Disponible vs Neta por máquina.
- :class:`GanttChart` — cronograma de rectificado + paradas de turno.

Las tarjetas/títulos/leyendas las pone :mod:`gui_qt.widgets.dashboard_card_qt`;
estos widgets sólo dibujan el área de datos. Los colores salen de
``config.tema`` (bloque ``DASH_*``), sin hardcodear hex acá.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Sequence, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from config import tema


def _qc(hex_str: str, alpha: int = 255) -> QColor:
    c = QColor(hex_str)
    c.setAlpha(alpha)
    return c


def _fmt_fecha(dt: datetime, span_days: float) -> str:
    """Etiqueta de eje temporal según el largo de la ventana (igual que el dashboard MPL)."""
    if span_days > 365:
        return dt.strftime("%d/%m/%y")
    if span_days > 7:
        return dt.strftime("%d/%m")
    return dt.strftime("%d/%m %H:%M")


def _t_frac(t: datetime, t0: datetime, t1: datetime) -> float:
    span = (t1 - t0).total_seconds()
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, (t - t0).total_seconds() / span))


# ── Gráficos con eje temporal ────────────────────────────────────────────────
class _TimeChart(QWidget):
    """Base para gráficos con eje X de tiempo: ejes, ticks y cursor de snapshot."""

    _AXIS_H = 22
    _TOP = 8
    _PAD_X = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(210)
        self._tiempos: List[datetime] = []
        self._cursor_frac: float | None = None

    def set_tiempos(self, tiempos: Sequence[datetime]) -> None:
        self._tiempos = list(tiempos)

    def set_cursor_frac(self, frac: float | None) -> None:
        self._cursor_frac = frac
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(
            self._PAD_X, self._TOP,
            max(1.0, self.width() - 2 * self._PAD_X),
            max(1.0, self.height() - self._TOP - self._AXIS_H),
        )

    def _x(self, frac: float, r: QRectF) -> float:
        return r.left() + frac * r.width()

    def _draw_axis(self, p: QPainter, r: QRectF, t0: datetime, t1: datetime) -> None:
        y = r.bottom()
        p.setPen(QPen(_qc(tema.DASH_AXIS), 1.5))
        p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        span_days = (t1 - t0).total_seconds() / 86400.0
        p.setFont(QFont(tema.FONT_MONO, 8))
        fm = p.fontMetrics()
        n = 6
        for i in range(n):
            frac = i / (n - 1)
            x = self._x(frac, r)
            p.setPen(QPen(_qc(tema.DASH_TICK), 1))
            p.drawLine(QPointF(x, y), QPointF(x, y + 6))
            label = _fmt_fecha(t0 + (t1 - t0) * frac, span_days)
            tw = fm.horizontalAdvance(label)
            tx = x if i == 0 else (x - tw if i == n - 1 else x - tw / 2)
            p.setPen(QPen(_qc(tema.DASH_TICK_TEXT)))
            p.drawText(QPointF(tx, y + 8 + fm.ascent()), label)

    def _draw_cursor(self, p: QPainter, r: QRectF) -> None:
        if self._cursor_frac is None:
            return
        x = self._x(self._cursor_frac, r)
        p.setPen(QPen(_qc(tema.DASH_CURSOR, 210), 2))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))


class StackedAreaChart(_TimeChart):
    """Área apilada del conteo de cilindros por estado a lo largo del tiempo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._estados: List[str] = []
        self._series: Dict[str, List[int]] = {}
        self._colores: Dict[str, str] = {}

    def set_data(self, tiempos, estados, series, colores) -> None:
        self.set_tiempos(tiempos)
        self._estados = list(estados)
        self._series = series
        self._colores = colores
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot_rect()
        n = len(self._tiempos)
        if n < 2:
            p.end()
            return
        t0, t1 = self._tiempos[0], self._tiempos[-1]
        xs = [self._x(_t_frac(t, t0, t1), r) for t in self._tiempos]
        totals = [sum(self._series[e][i] for e in self._estados) for i in range(n)]
        maxtot = max(totals) or 1

        def yv(val: float) -> float:
            return r.bottom() - (val / maxtot) * r.height()

        cumulative = [0.0] * n
        for estado in self._estados:
            vals = self._series.get(estado, [0] * n)
            upper = [cumulative[i] + vals[i] for i in range(n)]
            poly = QPolygonF()
            for i in range(n):
                poly.append(QPointF(xs[i], yv(upper[i])))
            for i in range(n - 1, -1, -1):
                poly.append(QPointF(xs[i], yv(cumulative[i])))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_qc(self._colores.get(estado, "#999999"), 224)))
            p.drawPolygon(poly)
            cumulative = upper

        self._draw_axis(p, r, t0, t1)
        self._draw_cursor(p, r)
        p.end()


class BufferChart(_TimeChart):
    """Buffer de seguridad global: área Disp+CRC + líneas Disponible/CRC."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._disp: List[int] = []
        self._crc: List[int] = []
        self._buffer: List[int] = []

    def set_data(self, tiempos, disponibles, crc, buffer) -> None:
        self.set_tiempos(tiempos)
        self._disp = disponibles
        self._crc = crc
        self._buffer = buffer
        self.update()

    def _polyline(self, p, xs, vals, yv, color, width, dashed) -> None:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if dashed:
            pen.setDashPattern([3.5, 3.0])
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(pen)
        line = QPolygonF()
        for i in range(len(xs)):
            line.append(QPointF(xs[i], yv(vals[i])))
        p.drawPolyline(line)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._plot_rect()
        n = len(self._tiempos)
        if n < 2:
            p.end()
            return
        t0, t1 = self._tiempos[0], self._tiempos[-1]
        xs = [self._x(_t_frac(t, t0, t1), r) for t in self._tiempos]
        maxv = max(self._buffer) or 1

        def yv(val: float) -> float:
            return r.bottom() - (val / maxv) * r.height()

        area = QPolygonF()
        area.append(QPointF(xs[0], r.bottom()))
        for i in range(n):
            area.append(QPointF(xs[i], yv(self._buffer[i])))
        area.append(QPointF(xs[-1], r.bottom()))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_qc(tema.DASH_GREEN, 36)))
        p.drawPolygon(area)

        self._polyline(p, xs, self._buffer, yv, _qc(tema.DASH_GREEN), 3, False)
        self._polyline(p, xs, self._disp, yv, _qc(tema.DASH_DISP), 2, True)
        self._polyline(p, xs, self._crc, yv, _qc(tema.DASH_ORANGE), 2, True)

        self._draw_axis(p, r, t0, t1)
        self._draw_cursor(p, r)
        p.end()


# ── Gráficos sin eje temporal ────────────────────────────────────────────────
class GroupedBarChart(QWidget):
    """Barras agrupadas por máquina: Disponible (verde) vs Neta (púrpura), 0-100%."""

    _BAR_W = 30
    _BAR_GAP = 8
    _GROUP_GAP = 26
    _BARS_H = 150
    _VAL_H = 16
    _NAME_H = 22

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(self._VAL_H + self._BARS_H + self._NAME_H + 8)
        self._maquinas: List[str] = []
        self._disp: Dict[str, float] = {}
        self._neta: Dict[str, float] = {}

    def set_data(self, maquinas, util_disp, util_neta) -> None:
        self._maquinas = list(maquinas)
        self._disp = util_disp
        self._neta = util_neta
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._maquinas:
            p.end()
            return
        n = len(self._maquinas)
        group_w = 2 * self._BAR_W + self._BAR_GAP
        total_w = n * group_w + (n - 1) * self._GROUP_GAP
        start_x = max(0.0, (self.width() - total_w) / 2.0)
        baseline = self._VAL_H + self._BARS_H

        for gi, maq in enumerate(self._maquinas):
            gx = start_x + gi * (group_w + self._GROUP_GAP)
            pares = (
                (float(self._disp.get(maq, 0.0)), tema.DASH_GREEN),
                (float(self._neta.get(maq, 0.0)), tema.DASH_PURPLE),
            )
            for bi, (pct, color) in enumerate(pares):
                bx = gx + bi * (self._BAR_W + self._BAR_GAP)
                bh = max(0.0, min(100.0, pct)) / 100.0 * self._BARS_H
                rect = QRectF(bx, baseline - bh, self._BAR_W, bh)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(_qc(color)))
                p.drawRoundedRect(rect, 4, 4)
                p.setFont(QFont(tema.FONT_FAMILY, 8))
                p.setPen(QPen(_qc(tema.DASH_TICK_TEXT)))
                p.drawText(
                    QRectF(bx - 6, baseline - bh - self._VAL_H, self._BAR_W + 12, self._VAL_H),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                    f"{pct:.0f}%",
                )
            p.setFont(QFont(tema.FONT_MONO, 9))
            p.setPen(QPen(_qc(tema.DASH_LEGEND_TEXT)))
            p.drawText(
                QRectF(gx - 10, baseline + 4, group_w + 20, self._NAME_H),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                maq,
            )
        p.end()


class GanttChart(QWidget):
    """Cronograma por máquina: segmentos de rectificado + paradas de turno + eje."""

    _ROW_H = 24
    _ROW_GAP = 12
    _LABEL_W = 62
    _GAP_LABEL = 10
    _AXIS_H = 22
    _TOP = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._maquinas: List[str] = []
        self._gantt: Dict[str, List[Tuple[datetime, datetime, str]]] = {}
        self._paradas: Dict[str, List[Tuple[datetime, datetime]]] = {}
        self._colores: Dict[str, str] = {}
        self._t0: datetime | None = None
        self._t1: datetime | None = None
        self._cursor_frac: float | None = None
        self.setMinimumHeight(120)

    def set_data(self, maquinas, gantt, paradas, t0, t1, colores_tipo) -> None:
        self._maquinas = list(maquinas)
        self._gantt = gantt
        self._paradas = paradas
        self._colores = colores_tipo
        self._t0, self._t1 = t0, t1
        n = max(1, len(self._maquinas))
        self.setMinimumHeight(self._TOP + n * (self._ROW_H + self._ROW_GAP) + self._AXIS_H)
        self.update()

    def set_cursor_frac(self, frac: float | None) -> None:
        self._cursor_frac = frac
        self.update()

    def _track_geom(self) -> Tuple[float, float]:
        left = self._LABEL_W + self._GAP_LABEL
        return left, max(1.0, self.width() - left - 2)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._maquinas or self._t0 is None or self._t1 is None:
            p.end()
            return
        track_left, track_w = self._track_geom()
        t0, t1 = self._t0, self._t1

        def x_of(t: datetime) -> float:
            return track_left + _t_frac(t, t0, t1) * track_w

        for i, maq in enumerate(self._maquinas):
            row_y = self._TOP + i * (self._ROW_H + self._ROW_GAP)
            # Etiqueta de máquina.
            p.setFont(QFont(tema.FONT_MONO, 9))
            p.setPen(QPen(_qc(tema.DASH_LEGEND_TEXT)))
            p.drawText(
                QRectF(0, row_y, self._LABEL_W, self._ROW_H),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                maq,
            )
            # Pista.
            track = QRectF(track_left, row_y, track_w, self._ROW_H)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_qc(tema.DASH_TRACK)))
            p.drawRoundedRect(track, 5, 5)
            p.save()
            p.setClipRect(track)
            # Segmentos de rectificado.
            for ini, fin, tipo in self._gantt.get(maq, []):
                x0, x1 = x_of(ini), x_of(fin)
                p.setBrush(QBrush(_qc(self._colores.get(tipo, "#999999"))))
                p.drawRect(QRectF(x0, row_y + 3, max(1.0, x1 - x0), self._ROW_H - 6))
            # Paradas de turno (encima, rojo oscuro).
            for ini, fin in self._paradas.get(maq, []):
                x0, x1 = x_of(ini), x_of(fin)
                p.setBrush(QBrush(_qc(tema.DASH_PARADA)))
                p.drawRect(QRectF(x0, row_y, max(1.0, x1 - x0), self._ROW_H))
            # Gridlines verticales (ticks).
            for k in range(6):
                gx = track_left + (k / 5) * track_w
                p.setPen(QPen(_qc(tema.DASH_GRID, 38), 1))
                p.drawLine(QPointF(gx, row_y), QPointF(gx, row_y + self._ROW_H))
            # Cursor.
            if self._cursor_frac is not None:
                cx = track_left + self._cursor_frac * track_w
                p.setPen(QPen(_qc(tema.DASH_CURSOR, 230), 2))
                p.drawLine(QPointF(cx, row_y), QPointF(cx, row_y + self._ROW_H))
            p.restore()

        # Eje inferior alineado a la pista.
        axis_y = self._TOP + len(self._maquinas) * (self._ROW_H + self._ROW_GAP)
        p.setPen(QPen(_qc(tema.DASH_AXIS), 1.5))
        p.drawLine(QPointF(track_left, axis_y), QPointF(track_left + track_w, axis_y))
        span_days = (t1 - t0).total_seconds() / 86400.0
        p.setFont(QFont(tema.FONT_MONO, 8))
        fm = p.fontMetrics()
        for k in range(6):
            frac = k / 5
            x = track_left + frac * track_w
            p.setPen(QPen(_qc(tema.DASH_TICK), 1))
            p.drawLine(QPointF(x, axis_y), QPointF(x, axis_y + 6))
            label = _fmt_fecha(t0 + (t1 - t0) * frac, span_days)
            tw = fm.horizontalAdvance(label)
            tx = x if k == 0 else (x - tw if k == 5 else x - tw / 2)
            p.setPen(QPen(_qc(tema.DASH_TICK_TEXT)))
            p.drawText(QPointF(tx, axis_y + 8 + fm.ascent()), label)
        p.end()
