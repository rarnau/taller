"""Widget reutilizable para la barra de estado inferior."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar

from gui_qt.ui_constants_qt import (
    STATUS_BAR_HEIGHT,
    STATUS_BAR_MARGIN_H,
    STATUS_BAR_MARGIN_V,
    STATUS_BAR_SPACING,
    STATUS_PROGRESS_WIDTH,
)


class StatusBarWidget(QFrame):
    """Barra de estado de la app con reloj, snapshot, progreso y estrategia."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedHeight(STATUS_BAR_HEIGHT)

        row = QHBoxLayout(self)
        row.setContentsMargins(STATUS_BAR_MARGIN_H, STATUS_BAR_MARGIN_V, STATUS_BAR_MARGIN_H, STATUS_BAR_MARGIN_V)
        row.setSpacing(STATUS_BAR_SPACING)

        self.status_main_label = QLabel("● Listo")
        self.status_main_label.setObjectName("Muted")
        self.status_main_label.setProperty("ok", "true")
        row.addWidget(self.status_main_label)

        self.status_clock = QLabel(datetime.now().strftime("%Y-%m-%d %H:%M"))
        self.status_clock.setObjectName("Muted")
        self.status_clock.setProperty("mono", "true")
        row.addWidget(self.status_clock)

        self.status_snap = QLabel("Snapshot 0/0")
        self.status_snap.setObjectName("Muted")
        row.addWidget(self.status_snap)

        row.addStretch(1)

        self.progress_sim = QProgressBar()
        self.progress_sim.setRange(0, 0)
        self.progress_sim.setFixedWidth(STATUS_PROGRESS_WIDTH)
        self.progress_sim.setVisible(False)
        row.addWidget(self.progress_sim)

        self.status_strategy = QLabel("Simulador de Cilindros Pro v4")
        self.status_strategy.setObjectName("Muted")
        self.status_strategy.setProperty("mono", "true")
        row.addWidget(self.status_strategy)
