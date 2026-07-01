"""Widget reusable para el corner superior derecho de tabs."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class TabsCornerInfoWidget(QWidget):
    """Muestra estado y reloj en la esquina del QTabWidget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabsCorner")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        self.top_state = QLabel("")
        self.top_state.setObjectName("TopState")
        self.top_state.setVisible(False)
        row.addWidget(self.top_state)

        row.addStretch(1)

        self.top_clock = QLabel(datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.top_clock.setObjectName("TopClock")
        self.top_clock.setProperty("mono", "true")
        self.top_clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.top_clock)
