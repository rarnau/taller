"""Pestaña Análisis: mapa estado×diámetro, histograma y evolución de SubStock."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QVBoxLayout, QWidget)

from modelos.enums import EstadoCilindro

from .. import theme as T
from ..charts import VectorChart
from ..widgets import label, leyenda, panel, titulo_seccion

STATES = ["Trabajando", "CRC", "Disponible", "Enfriando", "A rectificar", "Rectificando", "Baja"]


class VistaAnalisis(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        self.vm = None
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(14)
        self._placeholder()

    def _placeholder(self):
        self._limpiar()
        p = panel()
        p.layout().addWidget(label("Se mostrarán datos una vez corrida la simulación",
                                   color=T.TEXT_MUTE, size=13))
        self.lay.addWidget(p)
        self.lay.addStretch()

    def _limpiar(self):
        while self.lay.count():
            it = self.lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._del_layout(it.layout())

    def _del_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def set_vm(self, vm):
        self.vm = vm
        self._limpiar()
        self.lay.addWidget(self._panel_mapa())
        grid = QGridLayout()
        grid.setSpacing(14)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self._panel_hist(), 0, 0)
        grid.addWidget(self._panel_evol(), 0, 1)
        self.lay.addLayout(grid)
        self.lay.addStretch()

    # ── Dominio de diámetros ──────────────────────────────────────────────────
    def _dominio(self):
        t = self.vm.taller
        lo = t.diametro_minimo - 2
        hi = t.diametro_maximo + 2
        return lo, hi

    # ── Mapa estado × diámetro ────────────────────────────────────────────────
    def _panel_mapa(self):
        p = panel()
        p.layout().addWidget(titulo_seccion("Mapa de cilindros · estado vs diámetro", T.ORANGE))
        lo, hi = self._dominio()
        rng = max(1e-6, hi - lo)
        n = len(STATES)
        chart = VectorChart(230)
        hlines = [{"y": (n - 1 - i + 0.5) / n, "color": T.TRACK, "width": 1} for i in range(n)]
        points = []
        for c in self.vm.taller.cilindros.values():
            st = c.estado.value
            if st not in STATES:
                continue
            li = STATES.index(st)
            x = (c.diametro - lo) / rng
            y = (n - 1 - li + 0.5) / n
            points.append({"x": max(0, min(1, x)), "y": y, "r": 5, "color": T.COL_ESTADO[st]})
        chart.set_series(hlines=hlines, points=points)

        body = QHBoxLayout()
        body.setSpacing(10)
        lanes = QVBoxLayout()
        lanes.setSpacing(0)
        for st in STATES:
            lb = label(st, color=T.COL_ESTADO[st], size=10.5)
            lanes.addWidget(lb, 1)
        lanes_w = QWidget()
        lanes_w.setFixedWidth(90)
        lanes_w.setStyleSheet("background:transparent;")
        lanes_w.setLayout(lanes)
        body.addWidget(lanes_w)
        right = QVBoxLayout()
        right.setSpacing(5)
        right.addWidget(chart)
        ticks = QHBoxLayout()
        for v in self._ticks(lo, hi, 5):
            lb = label(str(v), color=T.TEXT_MUTE, size=10, family=T.FONT_MONO)
            ticks.addWidget(lb)
            ticks.addStretch()
        right.addLayout(ticks)
        right_w = QWidget()
        right_w.setStyleSheet("background:transparent;")
        right_w.setLayout(right)
        body.addWidget(right_w, 1)
        p.layout().addLayout(body)
        return p

    def _ticks(self, lo, hi, n):
        return [round(lo + (hi - lo) * i / (n - 1)) for i in range(n)]

    # ── Histograma de diámetros activos ───────────────────────────────────────
    def _panel_hist(self):
        p = panel()
        p.layout().addWidget(titulo_seccion("Distribución de diámetros (activos)", T.ORANGE))
        lo, hi = self._dominio()
        rng = max(1e-6, hi - lo)
        diam = [c.diametro for c in self.vm.taller.cilindros.values()
                if c.estado != EstadoCilindro.BAJA]
        bins = 13
        bw = rng / bins
        counts = [0] * bins
        for d in diam:
            b = min(bins - 1, max(0, int((d - lo) / bw)))
            counts[b] += 1
        maxc = max(counts + [1])
        chart = VectorChart(190)
        rects = []
        # Zonas de SubStock (faint)
        for ss in self.vm.taller.lista_substocks:
            jaula = ss.jaula_asignada
            col = T.JAULA_COLORS[(jaula - 1) % len(T.JAULA_COLORS)]
            x0 = max(0, (ss.hasta - lo) / rng)
            x1 = min(1, (ss.desde - lo) / rng)
            rects.append({"x": x0, "y": 0, "w": x1 - x0, "h": 1, "color": col, "opacity": 0.10})
        # Barras
        for i, c in enumerate(counts):
            rects.append({"x": i / bins + 0.01, "y": 0, "w": 1 / bins - 0.02,
                          "h": c / maxc, "color": T.BLUE_2, "opacity": 0.85, "radius": 2})
        vmin = (self.vm.taller.diametro_minimo - lo) / rng
        vmax = (self.vm.taller.diametro_maximo - lo) / rng
        chart.set_series(rects=rects, vlines=[
            {"x": vmin, "color": T.RED, "dash": True},
            {"x": vmax, "color": T.GREEN, "dash": True},
        ])
        p.layout().addWidget(chart)
        row = QHBoxLayout()
        row.addWidget(label(f"Mín {self.vm.taller.diametro_minimo:.0f}", color=T.RED, size=10, family=T.FONT_MONO))
        row.addStretch()
        row.addWidget(label(f"Máx {self.vm.taller.diametro_maximo:.0f}", color=T.GREEN, size=10, family=T.FONT_MONO))
        p.layout().addLayout(row)
        # Leyenda de zonas
        items = [(f"J{ss.jaula_asignada}",
                  T.JAULA_COLORS[(ss.jaula_asignada - 1) % len(T.JAULA_COLORS)])
                 for ss in self.vm.taller.lista_substocks]
        p.layout().addWidget(leyenda(items))
        return p

    # ── Evolución de SubStock disponibles ─────────────────────────────────────
    def _panel_evol(self):
        p = panel()
        p.layout().addWidget(titulo_seccion("Evolución de SubStock (disponibles)", T.ORANGE))
        snaps = self.vm.snaps
        N = max(1, len(snaps) - 1)
        maxv = max(1, self.vm.max_disp)
        chart = VectorChart(190)
        paths = []
        leg_items = []
        for jnum, ssname in self.vm.ss_por_jaula:
            col = T.JAULA_COLORS[(jnum - 1) % len(T.JAULA_COLORS)]
            pts = [(i / N, snaps[i].disponibles_por_substock.get(ssname, 0) / maxv)
                   for i in range(len(snaps))]
            paths.append({"pts": pts, "color": col, "width": 2.4})
            leg_items.append((f"J{jnum} · {ssname.split(' ')[0]}", col))
        # Bandas de parada
        rects = []
        bs = None
        for i, s in enumerate(snaps):
            par = len(s.jaulas_paradas) > 0
            if par and bs is None:
                bs = i
            elif not par and bs is not None:
                rects.append({"x": bs / N, "y": 0, "w": (i - bs) / N, "h": 1, "color": T.RED, "opacity": 0.12})
                bs = None
        if bs is not None:
            rects.append({"x": bs / N, "y": 0, "w": (N - bs) / N, "h": 1, "color": T.RED, "opacity": 0.12})
        chart.set_series(paths=paths, rects=rects)
        p.layout().addWidget(chart)
        p.layout().addWidget(leyenda(leg_items, marca="▬"))
        return p
