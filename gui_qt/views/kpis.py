"""Pestaña KPIs: 9 tarjetas + utilización disponible/neta por máquina."""
from __future__ import annotations

from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QVBoxLayout,
                               QWidget)

from modelos.kpis import calcular_kpis

from .. import theme as T
from ..widgets import label, titulo_seccion


def _card(lbl: str, val: str, color: str) -> QFrame:
    f = QFrame()
    f.setStyleSheet(f"QFrame{{background:{T.PANEL}; border:1px solid {T.BORDER}; border-radius:12px;}}")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 18, 16, 18)
    lay.setSpacing(8)
    l1 = label(lbl, color=T.TEXT_MUTE, size=11, weight=700, ls=0.6)
    l1.setWordWrap(True)
    lay.addWidget(l1, 0)
    l2 = label(val, color=color, size=30, weight=700, family=T.FONT_DISPLAY)
    lay.addWidget(l2)
    return f


def _util_card(name: str, pct: float) -> QFrame:
    color = T.color_util(pct)
    f = QFrame()
    f.setStyleSheet(f"QFrame{{background:{T.PANEL}; border:2px solid {color}; border-radius:12px;}}")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(8)
    top = QHBoxLayout()
    top.addWidget(label(name, color=T.TEXT_MUTE, size=12, family=T.FONT_MONO))
    top.addStretch()
    top.addWidget(label(f"{round(pct)}%", color=color, size=22, weight=700, family=T.FONT_DISPLAY))
    lay.addLayout(top)
    bar_bg = QFrame()
    bar_bg.setFixedHeight(6)
    bar_bg.setStyleSheet(f"background:{T.TRACK}; border-radius:3px;")
    bl = QHBoxLayout(bar_bg)
    bl.setContentsMargins(0, 0, 0, 0)
    fill = QFrame()
    fill.setStyleSheet(f"background:{color}; border-radius:3px;")
    bl.addWidget(fill, max(1, int(pct)))
    bl.addStretch(max(1, 100 - int(pct)))
    lay.addWidget(bar_bg)
    return f


class VistaKpis(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self._placeholder()

    def _placeholder(self):
        self._limpiar()
        self.lay.addWidget(label("Se mostrarán datos una vez corrida la simulación",
                                 color=T.TEXT_MUTE, size=13))
        self.lay.addStretch()

    def _limpiar(self):
        while self.lay.count():
            item = self.lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def set_taller(self, taller):
        self._limpiar()
        k = calcular_kpis(taller)
        cards = [
            ("Cilindros Totales", str(k["cilindros_totales"]), T.TEXT),
            ("Activos", str(k["activos"]), T.GREEN),
            ("Bajas", str(k["bajas"]), T.RED if k["bajas"] else T.GREEN),
            ("Alertas Críticas", str(k["alertas_criticas"]), T.RED if k["alertas_criticas"] else T.GREEN),
            ("Cambios Programados", str(k["cambios_programados"]), T.ORANGE_2),
            ("Rectificados Realizados", str(k["rectificados_realizados"]), T.PURPLE),
            ("Horizonte Simulación (h)", f"{k['horizonte_simulacion_h']:.1f}", T.CYAN),
            ("Diámetro Promedio", f"{k['diametro_promedio_mm']:.1f} mm", T.YELLOW),
            ("Desgaste Medio", f"{k['desgaste_medio_mm']:.2f} mm", T.ORANGE_HOT),
        ]
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (lbl, val, color) in enumerate(cards):
            grid.addWidget(_card(lbl, val, color), i // 3, i % 3)
        self.lay.addLayout(grid)

        self.lay.addSpacing(22)
        self.lay.addWidget(titulo_seccion("UTILIZACIÓN DISPONIBLE", T.ORANGE))
        self.lay.addSpacing(10)
        self.lay.addLayout(self._util_grid(k["utilizacion_maquinas_pct"]))

        self.lay.addSpacing(22)
        self.lay.addWidget(titulo_seccion("UTILIZACIÓN NETA", T.ORANGE))
        self.lay.addSpacing(10)
        self.lay.addLayout(self._util_grid(k["utilizacion_neta_pct"]))
        self.lay.addStretch()

    def _util_grid(self, datos: dict) -> QGridLayout:
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (name, pct) in enumerate(datos.items()):
            grid.addWidget(_util_card(name, pct), i // 3, i % 3)
        return grid
