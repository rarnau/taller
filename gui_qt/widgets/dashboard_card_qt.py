"""Tarjeta del Dashboard: marco + título naranja + contenido + leyenda.

Replica el contenedor de cada panel del mockup (``html_ref.html``): fondo
``#1A1F26``, borde ``#2B333D``, radio 12, título Space Grotesk naranja y una
fila de leyenda con swatches. El estilo vive en el QSS global (``theme.py``).
"""
from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from config import tema


class _LegendSwatch(QFrame):
    """Cuadradito de color para la leyenda."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self.setStyleSheet(
            f"background-color: {color}; border-radius: 2px;"
        )


def build_legend(items: List[Tuple[str, str]]) -> QWidget:
    """Fila de leyenda a partir de ``[(color_hex, etiqueta), ...]``."""
    row = QWidget()
    row.setObjectName("DashboardLegendRow")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(14)
    for color, label in items:
        item = QWidget()
        item.setObjectName("DashboardLegendItem")
        item_lay = QHBoxLayout(item)
        item_lay.setContentsMargins(0, 0, 0, 0)
        item_lay.setSpacing(5)
        item_lay.addWidget(_LegendSwatch(color))
        lbl = QLabel(label)
        lbl.setObjectName("DashboardLegend")
        item_lay.addWidget(lbl)
        lay.addWidget(item)
    lay.addStretch(1)
    return row


class DashboardCard(QFrame):
    """Card con título naranja, área de contenido y leyenda opcional."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashboardCard")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(14, 14, 14, 14)
        self._root.setSpacing(10)

        # Header: título a la izquierda + zona de acciones a la derecha (para
        # botones opcionales como "Ocultar bajas" en el mockup).
        self._header = QHBoxLayout()
        self._header.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("DashboardCardTitle")
        self._header.addWidget(self.title_label)
        self._header.addStretch(1)
        self._root.addLayout(self._header)

        self._legend: QWidget | None = None

    def add_header_action(self, widget: QWidget) -> None:
        """Agrega un control (p. ej. un toggle) a la derecha del título."""
        self._header.addWidget(widget)

    def add_content(self, widget: QWidget, stretch: int = 1) -> None:
        self._root.addWidget(widget, stretch)

    def set_legend(self, items: List[Tuple[str, str]]) -> None:
        if self._legend is not None:
            self._root.removeWidget(self._legend)
            self._legend.deleteLater()
        self._legend = build_legend(items)
        self._root.addWidget(self._legend)
