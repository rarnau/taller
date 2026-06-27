"""Rows reutilizables de etiqueta + control para formularios Qt."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class LabeledFieldRow(QWidget):
    """Fila horizontal simple de etiqueta + widget de entrada."""

    def __init__(
        self,
        label_text: str,
        field_widget: QWidget,
        parent: QWidget | None = None,
        *,
        label_object_name: str | None = None,
        spacing: int = 8,
        stretch_field: bool = False,
    ) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(spacing)

        self.label = QLabel(label_text)
        if label_object_name:
            self.label.setObjectName(label_object_name)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.label)

        self.field_widget = field_widget
        row.addWidget(self.field_widget, 1 if stretch_field else 0)

        if not stretch_field:
            row.addStretch(1)
