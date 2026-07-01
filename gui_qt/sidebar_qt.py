"""Construccion del sidebar Qt de la ventana principal."""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect

from gui_qt.ui_constants_qt import SIDEBAR_MARGIN, SIDEBAR_SPACING, SIDEBAR_WIDTH
from gui_qt.widgets.flow_card_qt import FlowCard


def build_sidebar(window: Any, slider_cls: type[QSlider]) -> QFrame:
    """Construye el sidebar y asigna sus controles a ``window``."""
    sidebar = QFrame(window)
    sidebar.setObjectName("Sidebar")
    sidebar.setFixedWidth(SIDEBAR_WIDTH)

    col = QVBoxLayout(sidebar)
    col.setContentsMargins(SIDEBAR_MARGIN, SIDEBAR_MARGIN, SIDEBAR_MARGIN, SIDEBAR_MARGIN)
    col.setSpacing(SIDEBAR_SPACING)

    brand_row = QHBoxLayout()
    brand_row.setContentsMargins(0, 2, 0, 2)
    brand_row.setSpacing(10)

    logo = QLabel("◎")
    logo.setObjectName("BrandMark")
    logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
    logo.setFixedSize(32, 32)
    brand_row.addWidget(logo, 0)

    brand_col = QVBoxLayout()
    brand_col.setContentsMargins(0, 0, 0, 0)
    brand_col.setSpacing(0)
    brand = QLabel("SIMULADOR")
    brand.setObjectName("BrandTitle")
    sub = QLabel("cilindros · v4")
    sub.setObjectName("BrandSubtitle")
    brand_col.addWidget(brand)
    brand_col.addWidget(sub)
    brand_row.addLayout(brand_col, 1)
    brand_row.addStretch(1)
    col.addLayout(brand_row)

    window.btn_run = QPushButton("▶ Ejecutar Simulación")
    window.btn_run.setObjectName("PrimaryAction")
    shadow = QGraphicsDropShadowEffect(window.btn_run)
    shadow.setBlurRadius(14)
    shadow.setOffset(0, 2)
    shadow.setColor(QColor(43, 181, 121, 95))
    window.btn_run.setGraphicsEffect(shadow)
    window.btn_run.clicked.connect(window._run_simulation)
    col.addWidget(window.btn_run)

    window.flow_card = FlowCard(window)
    window.dot_flow_inv = window.flow_card.dot_flow_inv
    window.dot_flow_gen = window.flow_card.dot_flow_gen
    window.dot_flow_sim = window.flow_card.dot_flow_sim
    window.lbl_flow_inv = window.flow_card.lbl_flow_inv
    window.lbl_flow_gen = window.flow_card.lbl_flow_gen
    window.lbl_flow_sim = window.flow_card.lbl_flow_sim
    window.lbl_flow_inv_count = window.flow_card.lbl_flow_inv_count
    window.lbl_flow_gen_count = window.flow_card.lbl_flow_gen_count
    window.lbl_flow_sim_count = window.flow_card.lbl_flow_sim_count
    col.addWidget(window.flow_card)

    section = QLabel("REPRODUCCIÓN")
    section.setObjectName("BoardHeader")
    section.setProperty("muted", "true")
    col.addWidget(section)

    transport = QHBoxLayout()
    transport.setContentsMargins(0, 0, 0, 0)
    transport.setSpacing(5)
    window.btn_prev = QPushButton("⏮")
    window.btn_prev.setObjectName("PlaybackButton")
    window.btn_prev.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.btn_prev.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    window.btn_prev.clicked.connect(lambda: window._step(-1))
    transport.addWidget(window.btn_prev, 1)

    window.btn_play = QPushButton("▶ Play")
    window.btn_play.setObjectName("PlaybackPlayButton")
    window.btn_play.setCheckable(True)
    window.btn_play.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.btn_play.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    window.btn_play.clicked.connect(window._toggle_play)
    transport.addWidget(window.btn_play, 2)

    window.btn_stop = QPushButton("⏹")
    window.btn_stop.setObjectName("PlaybackButton")
    window.btn_stop.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.btn_stop.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    window.btn_stop.clicked.connect(window._stop_play)
    transport.addWidget(window.btn_stop, 1)

    window.btn_next = QPushButton("⏭")
    window.btn_next.setObjectName("PlaybackButton")
    window.btn_next.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.btn_next.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    window.btn_next.clicked.connect(lambda: window._step(1))
    transport.addWidget(window.btn_next, 1)
    col.addLayout(transport)

    speeds = QHBoxLayout()
    speeds.setContentsMargins(0, 0, 0, 0)
    speeds.setSpacing(5)
    speeds_title = QLabel("Veloc.")
    speeds_title.setObjectName("Muted")
    speeds_title.setProperty("small", "true")
    speeds.addWidget(speeds_title)
    speed_group = QButtonGroup(window)
    speed_group.setExclusive(True)
    for value in (1, 2, 5, 10):
        b = QPushButton(f"{value}×")
        b.setObjectName("PlaybackSpeedButton")
        b.setCheckable(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        if value == 2:
            b.setChecked(True)
        b.clicked.connect(lambda _checked, v=value: window._set_speed(v))
        speed_group.addButton(b)
        speeds.addWidget(b, 1)
    col.addLayout(speeds)

    window.slider = slider_cls(Qt.Orientation.Horizontal, window)
    window.slider.setObjectName("PlaybackSlider")
    window.slider.setMinimum(0)
    window.slider.setMaximum(0)
    window.slider.setValue(0)
    window.slider.setFixedHeight(13)
    window.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    window.slider.valueChanged.connect(window._on_seek)
    marker_sig = getattr(window.slider, "marker_clicked", None)
    if marker_sig is not None:
        cast(Any, marker_sig).connect(window._go_to_snapshot)
    col.addWidget(window.slider)

    window.snapshot_label = QLabel("snapshot 0 / 0")
    window.snapshot_label.setObjectName("Muted")
    window.snapshot_label.setProperty("mono", "true")
    window.snapshot_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    col.addWidget(window.snapshot_label, 0, Qt.AlignmentFlag.AlignHCenter)

    col.addStretch(1)

    window.lbl_export = QLabel("Exportar resultados →")
    window.lbl_export.setObjectName("Muted")
    window.lbl_export.setProperty("small", "true")
    col.addWidget(window.lbl_export)

    return sidebar
