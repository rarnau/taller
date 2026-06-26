"""Gráficos vectoriales con QPainter — reproducen el look plano del SVG del HTML.

Un único widget genérico ``VectorChart`` pinta polígonos, paths, rectángulos,
líneas guía y puntos en coordenadas **normalizadas** [0,1] (x izq→der,
y abajo(0)→arriba(1)). Las vistas calculan las series y se las pasan; así el
Dashboard y Análisis comparten el mismo motor de dibujo.
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from . import theme as T


def _c(hexc: str, opacity: float = 1.0) -> QColor:
    col = QColor(hexc)
    col.setAlphaF(max(0.0, min(1.0, opacity)))
    return col


class VectorChart(QWidget):
    def __init__(self, height: int = 210, pad: Tuple[int, int, int, int] = (2, 2, 2, 2)):
        super().__init__()
        self.setMinimumHeight(height)
        self.setStyleSheet("background:transparent;")
        self._pad = pad  # left, top, right, bottom (px)
        self.polygons: List[dict] = []
        self.paths: List[dict] = []
        self.rects: List[dict] = []
        self.vlines: List[dict] = []
        self.hlines: List[dict] = []
        self.points: List[dict] = []

    def set_series(self, *, polygons=None, paths=None, rects=None,
                   vlines=None, hlines=None, points=None):
        self.polygons = polygons or []
        self.paths = paths or []
        self.rects = rects or []
        self.vlines = vlines or []
        self.hlines = hlines or []
        self.points = points or []
        self.update()

    # ── Coordenadas ───────────────────────────────────────────────────────────
    def _area(self):
        l, t, r, b = self._pad
        w = self.width() - l - r
        h = self.height() - t - b
        return l, t, w, h

    def _px(self, x: float, y: float):
        l, t, w, h = self._area()
        return QPointF(l + x * w, t + (1 - y) * h)

    # ── Pintado ───────────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        for poly in self.polygons:
            qp = QPolygonF([self._px(x, y) for x, y in poly["pts"]])
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_c(poly["color"], poly.get("opacity", 0.88))))
            p.drawPolygon(qp)

        for hl in self.hlines:
            pen = QPen(_c(hl.get("color", T.TRACK), hl.get("opacity", 1.0)))
            pen.setWidthF(hl.get("width", 1))
            p.setPen(pen)
            y = self._px(0, hl["y"]).y()
            l, t, w, h = self._area()
            p.drawLine(QPointF(l, y), QPointF(l + w, y))

        for r in self.rects:
            l, t, w, h = self._area()
            rx = l + r["x"] * w
            rw = max(0.0, r["w"] * w)
            # y es el borde inferior, altura hacia arriba
            ry_bottom = self._px(0, r["y"]).y()
            rh = r["h"] * h
            rect = QRectF(rx, ry_bottom - rh, rw, rh)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(_c(r["color"], r.get("opacity", 1.0))))
            rad = r.get("radius", 0)
            if rad:
                p.drawRoundedRect(rect, rad, rad)
            else:
                p.drawRect(rect)

        for pa in self.paths:
            path = QPainterPath()
            pts = pa["pts"]
            if not pts:
                continue
            path.moveTo(self._px(*pts[0]))
            for x, y in pts[1:]:
                path.lineTo(self._px(x, y))
            if pa.get("fill_color"):
                fp = QPainterPath(path)
                l, t, w, h = self._area()
                fp.lineTo(self._px(pts[-1][0], 0))
                fp.lineTo(self._px(pts[0][0], 0))
                fp.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(_c(pa["fill_color"], pa.get("fill_opacity", 0.14))))
                p.drawPath(fp)
            pen = QPen(_c(pa["color"], pa.get("opacity", 1.0)))
            pen.setWidthF(pa.get("width", 2))
            if pa.get("dash"):
                pen.setDashPattern([4, 3])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

        for vl in self.vlines:
            pen = QPen(_c(vl.get("color", T.RED), vl.get("opacity", 1.0)))
            pen.setWidthF(vl.get("width", 2))
            if vl.get("dash"):
                pen.setDashPattern([4, 3])
            p.setPen(pen)
            x = self._px(vl["x"], 0).x()
            l, t, w, h = self._area()
            p.drawLine(QPointF(x, t), QPointF(x, t + h))

        for pt in self.points:
            p.setPen(QPen(_c(T.BG), 0.8))
            p.setBrush(QBrush(_c(pt["color"], pt.get("opacity", 0.78))))
            c = self._px(pt["x"], pt["y"])
            r = pt.get("r", 5)
            p.drawEllipse(c, r, r)

        p.end()
