"""Barra lateral: logo, botón de simulación, FLUJO y controles de reproducción."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QVBoxLayout, QWidget)

from . import theme as T
from .widgets import label


class _MarcasParada(QWidget):
    """Cinta fina sobre el slider con un ▼ por cada inicio de PARADA."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(9)
        self._marks: List[float] = []  # porcentajes 0..100

    def set_marks(self, pcts: List[float]):
        self._marks = pcts
        self.update()

    def paintEvent(self, _e):
        if not self._marks:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(T.RED))
        p.setPen(Qt.NoPen)
        w = self.width()
        for pct in self._marks:
            x = pct / 100 * w
            tri = QPolygonF([QPointF(x - 4, 0), QPointF(x + 4, 0), QPointF(x, 6)])
            p.drawPolygon(tri)
        p.end()


class Sidebar(QFrame):
    ejecutar = Signal()
    toggle_play = Signal()
    stop = Signal()
    step = Signal(int)
    set_speed = Signal(int)
    seek = Signal(int)
    exportar = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedWidth(230)
        self.setStyleSheet(
            f"QFrame{{background:{T.SIDEBAR}; border-right:1px solid {T.BORDER_SOFT};}}")
        self._speed_btns: dict[int, QPushButton] = {}
        self._build()

    # ── Construcción ──────────────────────────────────────────────────────────
    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 18, 16, 18)
        lay.setSpacing(0)

        # Logo
        logo_row = QHBoxLayout()
        logo_row.setSpacing(10)
        ico = QLabel("▦")
        ico.setFixedSize(32, 32)
        ico.setAlignment(Qt.AlignCenter)
        ico.setStyleSheet(
            f"background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {T.ORANGE},stop:1 {T.ORANGE_DK});"
            f"border-radius:8px; color:#1a1206; font-family:{T.FONT_DISPLAY}; font-weight:700; font-size:18px;")
        logo_row.addWidget(ico)
        title = QLabel("SIMULADOR<br><span style='color:#8b939d; font-weight:500; font-size:12px;'>cilindros · v4</span>")
        title.setStyleSheet(
            f"color:{T.TEXT}; font-family:{T.FONT_DISPLAY}; font-weight:700; font-size:14px; background:transparent;")
        logo_row.addWidget(title)
        logo_row.addStretch()
        lay.addLayout(logo_row)
        lay.addSpacing(20)

        # Botón ejecutar
        self.btn_run = QPushButton("▶  Ejecutar Simulación")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setStyleSheet(
            f"QPushButton{{border:none; background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {T.GREEN_3},stop:1 {T.GREEN_2});"
            f" color:#062014; font-weight:700; font-size:13px; padding:11px; border-radius:9px;}}"
            f"QPushButton:hover{{background:{T.GREEN_3};}}"
            f"QPushButton:disabled{{background:{T.TRACK}; color:{T.TEXT_DIM};}}")
        self.btn_run.clicked.connect(self.ejecutar.emit)
        lay.addWidget(self.btn_run)
        lay.addSpacing(18)

        # FLUJO
        lay.addWidget(label("FLUJO", color=T.TEXT_DIM, size=11, weight=600, ls=0.9))
        lay.addSpacing(10)
        self.flujo_box = QVBoxLayout()
        self.flujo_box.setSpacing(7)
        self._flujo_rows = {}
        for key, name in (("inv", "Inventario"), ("gen", "Generación"), ("sim", "Simulación")):
            row = self._flujo_row(name)
            self._flujo_rows[key] = row
            self.flujo_box.addWidget(row["w"])
        lay.addLayout(self.flujo_box)
        lay.addSpacing(18)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{T.BORDER_SOFT};")
        lay.addWidget(sep)
        lay.addSpacing(18)

        # REPRODUCCIÓN
        lay.addWidget(label("REPRODUCCIÓN", color=T.TEXT_DIM, size=11, weight=600, ls=0.9))
        lay.addSpacing(10)
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        self.btn_back = self._ctrl_btn("⏮", 1)
        self.btn_play = self._ctrl_btn("▶ Play", 1.7, primary=True)
        self.btn_stop = self._ctrl_btn("⏹", 1)
        self.btn_fwd = self._ctrl_btn("⏭", 1)
        self.btn_back.clicked.connect(lambda: self.step.emit(-1))
        self.btn_play.clicked.connect(self.toggle_play.emit)
        self.btn_stop.clicked.connect(self.stop.emit)
        self.btn_fwd.clicked.connect(lambda: self.step.emit(1))
        for b in (self.btn_back, self.btn_play, self.btn_stop, self.btn_fwd):
            ctrl.addWidget(b)
        lay.addLayout(ctrl)
        lay.addSpacing(9)

        # Velocidad
        sp_row = QHBoxLayout()
        sp_row.setSpacing(6)
        sp_row.addWidget(label("Veloc.", color=T.TEXT_DIM, size=11))
        for v in (1, 2, 5, 10):
            b = QPushButton(f"{v}×")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, vv=v: self.set_speed.emit(vv))
            self._speed_btns[v] = b
            sp_row.addWidget(b)
        lay.addLayout(sp_row)
        self.set_speed_active(2)
        lay.addSpacing(14)

        # Marcas de parada + slider
        self.marcas = _MarcasParada()
        lay.addWidget(self.marcas)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.setStyleSheet(self._slider_qss())
        self.slider.valueChanged.connect(self._on_slider)
        self._slider_silencioso = False
        lay.addWidget(self.slider)
        lay.addSpacing(6)
        self.lbl_snap = label("snapshot 0 / 0", color=T.TEXT_DIM, size=10.5, family=T.FONT_MONO)
        self.lbl_snap.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.lbl_snap)

        lay.addStretch()
        exp = label("Exportar resultados ↓", color=T.TEXT_DIM, size=11)
        exp.setCursor(Qt.PointingHandCursor)
        exp.mousePressEvent = lambda _e: self.exportar.emit()
        lay.addWidget(exp)

    def _flujo_row(self, name: str) -> dict:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(9)
        dot = QLabel("○")
        dot.setFixedSize(19, 19)
        dot.setAlignment(Qt.AlignCenter)
        dot.setStyleSheet(
            f"background:{T.TRACK}; color:{T.TEXT_DIM}; border-radius:9px; font-size:11px; font-weight:700;")
        name_lb = label(name, size=13)
        count_lb = label("", color=T.TEXT_DIM, size=11)
        row.addWidget(dot)
        row.addWidget(name_lb)
        row.addStretch()
        row.addWidget(count_lb)
        return {"w": w, "dot": dot, "count": count_lb}

    def _ctrl_btn(self, text: str, stretch: float, primary: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        if primary:
            b.setStyleSheet(
                f"QPushButton{{background:{T.ORANGE}; border:none; color:#1a1206; border-radius:7px;"
                f" padding:7px 0; font-weight:700; font-size:12px;}} QPushButton:hover{{background:{T.ORANGE_2};}}")
        else:
            b.setStyleSheet(
                f"QPushButton{{background:{T.TRACK}; border:1px solid {T.BORDER_IN}; color:{T.TEXT_2};"
                f" border-radius:7px; padding:7px 0; font-size:12px;}} QPushButton:hover{{border-color:{T.ORANGE};}}")
        from PySide6.QtWidgets import QSizePolicy
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        b.setProperty("stretch", stretch)
        return b

    def _slider_qss(self) -> str:
        return (
            f"QSlider::groove:horizontal{{height:6px; background:{T.TRACK}; border-radius:3px;}}"
            f"QSlider::handle:horizontal{{width:13px; height:13px; margin:-4px 0; border-radius:6px;"
            f" background:#fff;}}"
            f"QSlider::sub-page:horizontal{{background:{T.ORANGE}; border-radius:3px;}}")

    # ── API pública ───────────────────────────────────────────────────────────
    def _on_slider(self, val: int):
        if self._slider_silencioso:
            return
        self.seek.emit(val)

    def set_play_label(self, playing: bool):
        self.btn_play.setText("⏸ Pausa" if playing else "▶ Play")

    def set_speed_active(self, v: int):
        for vv, b in self._speed_btns.items():
            activo = vv == v
            col = T.ORANGE if activo else T.TEXT_MUTE
            bg = T.tint(T.ORANGE, "22") if activo else "transparent"
            bd = T.ORANGE if activo else T.BORDER_IN
            b.setStyleSheet(
                f"QPushButton{{border-radius:6px; padding:4px 6px; font-size:11px; font-weight:700;"
                f" background:{bg}; border:1px solid {bd}; color:{col};}}")

    def set_snapshot(self, idx: int, total: int):
        self._slider_silencioso = True
        self.slider.setMaximum(max(0, total - 1))
        self.slider.setValue(idx)
        self._slider_silencioso = False
        self.lbl_snap.setText(f"snapshot {idx + 1 if total else 0} / {total}")

    def set_parada_marks(self, pcts: List[float]):
        self.marcas.set_marks(pcts)

    def set_flujo(self, inv: int, gen: int, sim_done: bool):
        for key, val, done in (("inv", inv, inv > 0), ("gen", gen, gen > 0),
                               ("sim", None, sim_done)):
            row = self._flujo_rows[key]
            row["dot"].setText("✓" if done else "○")
            row["dot"].setStyleSheet(
                f"background:{T.GREEN_2 if done else T.TRACK}; color:{'#062014' if done else T.TEXT_DIM};"
                f" border-radius:9px; font-size:11px; font-weight:700;")
            if val is not None:
                row["count"].setText(str(val) if val else "")

    def set_run_enabled(self, en: bool):
        self.btn_run.setEnabled(en)
