"""Contenedor reutilizable tipo card con título y hint opcionales."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class SectionCard(QFrame):
    """Card configurable con layout vertical para contenido."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        object_name: str = "CardSoft",
        title: str | None = None,
        title_object_name: str = "CardTitle",
        hint: str | None = None,
        hint_object_name: str = "Muted",
        margins: tuple[int, int, int, int] = (14, 12, 14, 12),
        spacing: int = 8,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)

        self.layout_main = QVBoxLayout(self)
        self.layout_main.setContentsMargins(*margins)
        self.layout_main.setSpacing(spacing)

        self.title_label: QLabel | None = None
        self.hint_label: QLabel | None = None

        if title:
            self.title_label = QLabel(title)
            self.title_label.setObjectName(title_object_name)
            self.layout_main.addWidget(self.title_label)

        if hint:
            self.hint_label = QLabel(hint)
            self.hint_label.setObjectName(hint_object_name)
            self.hint_label.setWordWrap(True)
            self.layout_main.addWidget(self.hint_label)

    def content_layout(self) -> QVBoxLayout:
        return self.layout_main
