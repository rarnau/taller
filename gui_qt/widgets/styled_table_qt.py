"""Tabla base reutilizable para configuración visual homogénea."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QTableWidget, QWidget


class StyledTableWidget(QTableWidget):
    """QTableWidget con helpers de configuración comunes."""

    def __init__(self, rows: int = 0, columns: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)

    def apply_base_defaults(self) -> None:
        self.verticalHeader().setVisible(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)

    def apply_stretch_columns(self) -> None:
        header = self.horizontalHeader()
        header.setStretchLastSection(True)
        for i in range(self.columnCount()):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
