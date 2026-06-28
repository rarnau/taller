"""Cards reutilizables de KPIs para la GUI Qt."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from config import tema as tk_theme


class SummaryCard(QFrame):
    """Card de KPI general: label arriba + valor grande centrado."""

    def __init__(self, title: str, value: str, color: str) -> None:
        super().__init__()
        self.setObjectName("KpiSummaryCard")
        self.setStyleSheet(
            "QFrame#KpiSummaryCard {"
            f"background:{tk_theme.KPI_CARD_BG}; border:1px solid {tk_theme.KPI_CARD_BORDER}; border-radius:12px;"
            "}"
        )
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 18, 16, 18)
        col.setSpacing(8)

        t = QLabel(title)
        t.setStyleSheet(
            f"background:transparent; color:{tk_theme.KPI_TEXT_MUTED}; font-size:11px; "
            "font-weight:700; letter-spacing:0.06em;"
        )
        t.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        v = QLabel(value)
        v.setStyleSheet(
            f"background:transparent; color:{color}; font-family:'Space Grotesk'; "
            "font-size:30px; font-weight:700;"
        )
        v.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        col.addWidget(t)
        col.addWidget(v)


class UtilCard(QFrame):
    """Card de utilización por máquina: nombre + % + barra."""

    def __init__(self, name: str, pct: float | None, color: str | None) -> None:
        super().__init__()
        border_color = color or tk_theme.KPI_CARD_BORDER
        self.setObjectName("KpiUtilCard")
        self.setStyleSheet(
            "QFrame#KpiUtilCard {"
            f"background:{tk_theme.KPI_CARD_BG}; border:2px solid {border_color}; border-radius:12px;"
            "}"
        )
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(8)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(
            f"background:transparent; color:{tk_theme.KPI_TEXT_MUTED}; "
            "font-family:'IBM Plex Mono'; font-size:12px;"
        )
        pct_text = "" if pct is None else f"{pct:.0f}%"
        pct_lbl = QLabel(pct_text)
        pct_lbl.setStyleSheet(
            f"background:transparent; color:{border_color}; font-family:'Space Grotesk'; "
            "font-size:22px; font-weight:700;"
        )

        row.addWidget(name_lbl)
        row.addStretch(1)
        row.addWidget(pct_lbl)
        col.addLayout(row)

        # Barra: track gris con relleno proporcional.
        track = QFrame()
        track.setObjectName("KpiUtilTrack")
        track.setStyleSheet(
            f"QFrame#KpiUtilTrack {{ background:{tk_theme.KPI_BAR_TRACK}; border:none; border-radius:3px; }}"
        )
        track.setFixedHeight(6)
        track_row = QHBoxLayout(track)
        track_row.setContentsMargins(0, 0, 0, 0)
        track_row.setSpacing(0)

        fill = QFrame()
        fill.setObjectName("KpiUtilFill")
        fill.setStyleSheet(
            f"QFrame#KpiUtilFill {{ background:{border_color}; border:none; border-radius:3px; }}"
        )
        fill.setFixedHeight(6)

        if pct is None:
            fill.setVisible(False)
            track_row.addStretch(1)
        else:
            w_pct = int(round(max(0.0, min(100.0, pct))))
            if w_pct > 0:
                track_row.addWidget(fill, w_pct)
            else:
                fill.setVisible(False)
            if w_pct < 100:
                track_row.addStretch(100 - w_pct)

        col.addWidget(track)
