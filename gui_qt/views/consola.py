"""Pestaña Consola: log de la simulación + alertas."""
from __future__ import annotations

from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget

from .. import theme as T
from ..widgets import label, marco


class VistaConsola(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        out = QVBoxLayout(self)
        out.setContentsMargins(0, 0, 0, 0)
        self.box = marco(QFrame(), bg="#0c0f13", border=T.BORDER, radius=12)
        self.lay = QVBoxLayout(self.box)
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(3)
        self.lay.addStretch()
        out.addWidget(self.box)

    def _linea(self, texto: str):
        lb = label(texto, color="#9fb0bd", size=12.5, family=T.FONT_MONO)
        lb.setWordWrap(True)
        self.lay.insertWidget(self.lay.count() - 1, lb)

    def append(self, texto: str):
        self._linea(texto)

    def set_taller(self, taller):
        # Limpiar
        while self.lay.count() > 1:
            item = self.lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._linea("[06:00] Simulador de Cilindros Pro v4")
        for aviso in taller.avisos_carga:
            self._linea(aviso)
        for linea in taller.log_simulacion:
            self._linea(linea)
        for a in taller.alertas:
            hh = a.tiempo.strftime("%H:%M")
            self._linea(f"[{hh}] {a.tipo}: {a.mensaje}")
