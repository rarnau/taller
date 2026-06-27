"""Editores reutilizables para celdas de tablas de configuración."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLineEdit, QWidget


def make_config_cell_input(parent: QWidget, value: str, *, align_center: bool = False) -> QLineEdit:
    editor = QLineEdit(parent)
    editor.setObjectName("ConfigCellInput")
    editor.setText(value)
    editor.setClearButtonEnabled(False)
    editor.setAlignment(
        Qt.AlignmentFlag.AlignCenter if align_center else Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
    )
    return editor


def make_priority_combo(parent: QWidget, value: str) -> QComboBox:
    combo = QComboBox(parent)
    combo.setObjectName("ConfigCellCombo")
    combo.addItem("produccion", "produccion")
    combo.addItem("desbaste", "desbaste")
    combo.setMinimumWidth(130)
    combo.setMaximumHeight(30)
    idx = combo.findData(value.lower())
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    return combo
