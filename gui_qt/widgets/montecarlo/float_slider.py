"""Slider de float con paso fijo y etiqueta (usado en los rangos Monte Carlo)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


class FloatSlider(QWidget):
    """Slider horizontal para un float en ``[0, maximo]`` con paso fijo + valor.

    Qt maneja sliders enteros, así que internamente trabaja en *ticks*
    (``valor / step``) y expone ``value()``/``setValue()`` en float, igual
    interfaz que un ``QDoubleSpinBox`` (así el resto del panel no cambia).
    """

    def __init__(self, maximo: float, step: float, decimals: int, color: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._step = step
        self._dec = decimals
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("McRangeSlider")
        self._slider.setRange(0, max(1, int(round(maximo / step))))
        self._slider.setSingleStep(1)
        self._lbl = QLabel("0")
        self._lbl.setMinimumWidth(48)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl.setStyleSheet(f"color:{color}; font-family:monospace; font-size:11px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._lbl, 0)
        self._slider.valueChanged.connect(self._refrescar_label)
        self._refrescar_label()

    def value(self) -> float:
        return self._slider.value() * self._step

    def setValue(self, v: float) -> None:  # noqa: N802 (interfaz tipo QSpinBox)
        # Bloquea señales: la carga programática no debe disparar el acople
        # Mín≤Máx (que clamparía antes de fijar ambos sliders).
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(float(v) / self._step)))
        self._slider.blockSignals(False)
        self._refrescar_label()

    def _refrescar_label(self) -> None:
        self._lbl.setText(f"{self.value():.{self._dec}f}")

    @property
    def slider(self) -> QSlider:
        return self._slider
