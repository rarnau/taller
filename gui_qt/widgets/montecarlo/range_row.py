"""Entrada de rango ``[min, max]``: cabecera + dos sliders acoplados (Mín/Máx)."""

from __future__ import annotations

from typing import Any, Sequence, Tuple

from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from config import tema
from gui_qt.widgets.montecarlo.float_slider import FloatSlider


class RangeRow(QWidget):
    """Cabecera (label + unidad) y dos ``FloatSlider`` acoplados (Mín ≤ Máx).

    Stack vertical (no lado a lado) para que entre en el panel angosto sin
    cortar el control de Máx. Los sliders se acoplan: Mín nunca supera a Máx ni
    viceversa (clamp del que se mueve). Expone ``values()``/``set_values()``.
    """

    def __init__(self, label: str, unit: str, maximo: float, step: float,
                 decimals: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)

        cab = QHBoxLayout()
        lab = QLabel(label)
        u = QLabel(unit)
        u.setMinimumWidth(30)
        u.setObjectName("Muted")
        u.setStyleSheet(f"color:{tema.FG_DIM}; font-family:monospace; font-size:10px;")
        cab.addWidget(lab)
        cab.addStretch(1)
        cab.addWidget(u)
        box.addLayout(cab)

        self._smin = FloatSlider(maximo, step, decimals, tema.RED)
        self._smax = FloatSlider(maximo, step, decimals, tema.GREEN)
        box.addLayout(self._fila_slider("Mín", self._smin))
        box.addLayout(self._fila_slider("Máx", self._smax))

        # Acople Mín ≤ Máx (clamp del slider que se mueve).
        self._smin.slider.valueChanged.connect(
            lambda _=0: self._smin.slider.setValue(
                min(self._smin.slider.value(), self._smax.slider.value())))
        self._smax.slider.valueChanged.connect(
            lambda _=0: self._smax.slider.setValue(
                max(self._smax.slider.value(), self._smin.slider.value())))

    def _fila_slider(self, etiqueta: str, slider: FloatSlider) -> QHBoxLayout:
        fila = QHBoxLayout()
        fila.setSpacing(6)
        cap = QLabel(etiqueta)
        cap.setMinimumWidth(32)
        cap_color = tema.RED if etiqueta == "Mín" else tema.GREEN
        cap.setStyleSheet(f"color:{cap_color}; font-size:9.5px;")
        fila.addWidget(cap, 0)
        fila.addWidget(slider, 1)
        return fila

    def values(self) -> Tuple[float, float]:
        return (self._smin.value(), self._smax.value())

    def set_values(self, par: Sequence[Any] | None) -> None:
        if par:
            self._smin.setValue(float(par[0]))
            self._smax.setValue(float(par[1]))
