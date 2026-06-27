"""Widget reusable para el corner superior derecho de tabs."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class TabsCornerInfoWidget(QWidget):
    """Muestra estado y reloj en la esquina del QTabWidget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TabsCorner")

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.top_state = QLabel("● en espera")
        self.top_state.setObjectName("TopState")
        row.addWidget(self.top_state)

        self.top_clock = QLabel(datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.top_clock.setObjectName("TopClock")
        row.addWidget(self.top_clock)
