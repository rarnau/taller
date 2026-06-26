"""Pestaña Dashboard: evolución de estados, buffer, utilización y cronograma."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from modelos.enums import TipoRectificado
from modelos.kpis import calcular_kpis

from .. import theme as T
from ..charts import VectorChart
from ..widgets import label, leyenda, panel, titulo_seccion

STATES = ["Trabajando", "CRC", "Disponible", "Enfriando", "A rectificar", "Rectificando", "Baja"]


def _leyenda(items):
    return leyenda(items)


class VistaDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        self.vm = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self._placeholder()

    def _placeholder(self):
        self._limpiar()
        p = panel()
        p.layout().addWidget(label("Se mostrarán datos una vez corrida la simulación",
                                   color=T.TEXT_MUTE, size=13))
        self.grid.addWidget(p, 0, 0, 1, 2)

    def _limpiar(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

    def set_vm(self, vm):
        self.vm = vm
        self._limpiar()
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)
        self.grid.addWidget(self._panel_estados(), 0, 0)
        self.grid.addWidget(self._panel_buffer(), 0, 1)
        self.grid.addWidget(self._panel_util(), 1, 0)
        self.grid.addWidget(self._panel_gantt(), 1, 1)

    # ── Paneles ────────────────────────────────────────────────────────────────
    def _panel_estados(self):
        p = panel()
        p.layout().addWidget(titulo_seccion("Evolución temporal de estados", T.ORANGE))
        chart = VectorChart(210)
        snaps = self.vm.snaps
        N = max(1, len(snaps) - 1)
        total = max(1, self.vm.total_cil())
        polys = []
        lower = [0.0] * len(snaps)
        for st in STATES:
            upper = [lower[i] + snaps[i].conteo_por_estado.get(st, 0) for i in range(len(snaps))]
            pts = [(i / N, upper[i] / total) for i in range(len(snaps))]
            pts += [(i / N, lower[i] / total) for i in range(len(snaps) - 1, -1, -1)]
            polys.append({"pts": pts, "color": T.COL_ESTADO[st], "opacity": 0.88})
            lower = upper
        chart.set_series(polygons=polys)
        p.layout().addWidget(chart)
        p.layout().addWidget(_leyenda([(s, T.COL_ESTADO[s]) for s in STATES]))
        return p

    def _panel_buffer(self):
        p = panel()
        p.layout().addWidget(titulo_seccion("Buffer de seguridad global", T.ORANGE))
        chart = VectorChart(210)
        snaps = self.vm.snaps
        N = max(1, len(snaps) - 1)
        disp = [sum(s.disponibles_por_substock.values()) for s in snaps]
        crc = [s.cantidad_crc_total for s in snaps]
        buf = [disp[i] + crc[i] for i in range(len(snaps))]
        maxb = max(buf + [1])
        xb = lambda arr: [(i / N, arr[i] / maxb) for i in range(len(snaps))]
        chart.set_series(paths=[
            {"pts": xb(buf), "color": T.GREEN, "width": 3, "fill_color": T.GREEN, "fill_opacity": 0.14},
            {"pts": xb(disp), "color": T.GREEN_LT, "width": 2, "dash": True},
            {"pts": xb(crc), "color": T.ORANGE_2, "width": 2, "dash": True},
        ])
        p.layout().addWidget(chart)
        p.layout().addWidget(_leyenda([("Disp + CRC", T.GREEN), ("Disponible", T.GREEN_LT), ("CRC", T.ORANGE_2)]))
        return p

    def _panel_util(self):
        p = panel()
        p.layout().addWidget(titulo_seccion("Utilización de máquinas · Disponible vs Neta", T.ORANGE))
        k = calcular_kpis(self.vm.taller)
        disp = k["utilizacion_maquinas_pct"]
        neta = k["utilizacion_neta_pct"]
        nombres = list(disp.keys())
        chart = VectorChart(170)
        rects = []
        n = max(1, len(nombres))
        slot = 1.0 / n
        bw = slot * 0.18
        for i, name in enumerate(nombres):
            cx = (i + 0.5) * slot
            d = disp.get(name, 0) / 100
            ne = neta.get(name, 0) / 100
            rects.append({"x": cx - bw - 0.01, "y": 0, "w": bw, "h": d,
                          "color": T.color_util(disp.get(name, 0)), "radius": 3})
            rects.append({"x": cx + 0.01, "y": 0, "w": bw, "h": ne,
                          "color": T.PURPLE, "radius": 3})
        chart.set_series(rects=rects)
        p.layout().addWidget(chart)
        # Etiquetas de máquina
        labels_row = QHBoxLayout()
        for name in nombres:
            lb = label(name, color=T.TEXT_2, size=11, family=T.FONT_MONO)
            lb.setAlignment(Qt.AlignCenter)
            labels_row.addWidget(lb, 1)
        p.layout().addLayout(labels_row)
        p.layout().addWidget(_leyenda([("Disponible", T.GREEN), ("Neta", T.PURPLE)]))
        return p

    def _panel_gantt(self):
        p = panel()
        p.layout().addWidget(titulo_seccion("Cronograma de rectificado", T.ORANGE))
        snaps = self.vm.snaps
        N = max(1, len(snaps) - 1)
        box = QVBoxLayout()
        box.setSpacing(12)
        for name in self.vm.maq_nombres:
            mq = self.vm.taller.maquinas[name]
            color = T.ORANGE_2 if mq.prioridad_defecto == TipoRectificado.DESBASTE else T.GREEN
            chart = VectorChart(24, pad=(0, 0, 0, 0))
            chart.setMinimumHeight(24)
            chart.setMaximumHeight(24)
            rects = [{"x": 0, "y": 0, "w": 1, "h": 1, "color": T.HOLE}]
            rs = None
            ps = None
            for i, s in enumerate(snaps):
                op = s.detalle_maquinas_operativa.get(name, True)
                if op:
                    if rs is None:
                        rs = i
                    if ps is not None:
                        rects.append({"x": ps / N, "y": 0, "w": (i - ps) / N, "h": 1, "color": T.PARADA_DK})
                        ps = None
                else:
                    if ps is None:
                        ps = i
                    if rs is not None:
                        rects.append({"x": rs / N, "y": 0, "w": (i - rs) / N, "h": 1, "color": color})
                        rs = None
            if rs is not None:
                rects.append({"x": rs / N, "y": 0, "w": (N - rs) / N, "h": 1, "color": color})
            if ps is not None:
                rects.append({"x": ps / N, "y": 0, "w": (N - ps) / N, "h": 1, "color": T.PARADA_DK})
            chart.set_series(rects=rects)
            row = QHBoxLayout()
            row.setSpacing(10)
            nm = label(name, color=T.TEXT_2, size=11, family=T.FONT_MONO)
            nm.setFixedWidth(62)
            row.addWidget(nm)
            row.addWidget(chart, 1)
            w = QWidget()
            w.setStyleSheet("background:transparent;")
            w.setLayout(row)
            box.addWidget(w)
        p.layout().addLayout(box)
        p.layout().addWidget(_leyenda([("Producción", T.GREEN), ("Desbaste", T.ORANGE_2), ("Parada (turno)", T.PARADA_DK)]))
        return p
