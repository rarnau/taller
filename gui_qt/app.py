"""Ventana principal de la GUI Qt — clon funcional del rediseño web.

Cablea la UI (sidebar + pestañas + status bar) al motor real vía ``cli.py`` y
``config/``, sin modificar ``modelos/``. Posee el estado de reproducción y el
runner de simulación.
"""
from __future__ import annotations

import os

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QScrollArea,
                               QStackedWidget, QVBoxLayout, QWidget)

import cli  # noqa: F401 - asegura que los símbolos del worker existan en el módulo
from config.persistencia import (cargar_config, obtener_estrategia_seleccion)
from modelos import generador_cambios as gencambios
from modelos.estrategias import ESTRATEGIAS_SELECCION

from . import theme as T
from .runner import SimRunner
from .sidebar import Sidebar
from .viewmodel import TallerVM
from .widgets import label
from .views.vista_real import VistaReal
from .views.kpis import VistaKpis
from .views.consola import VistaConsola
from .views.inventario import VistaInventario
from .views.dashboard import VistaDashboard
from .views.analisis import VistaAnalisis
from .views.generacion import VistaGeneracion
from .views.config import VistaConfig

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXCEL_DEMO = os.path.join(_RAIZ, "datos", "simulacion_140cils_1semana.xlsx")

TABS = [
    ("vista", "Vista Real"), ("dashboard", "Dashboard"), ("analisis", "Análisis"),
    ("inventario", "Inventario"), ("kpis", "KPIs"), ("generacion", "Generación"),
    ("config", "Configuración"), ("consola", "Consola"),
]


class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Simulador de Cilindros Pro v4 — Qt")
        self.resize(1380, 860)
        self.setStyleSheet(T.hoja_estilo())

        # Estado
        self.cfg = cargar_config()
        self.estrategia = obtener_estrategia_seleccion(self.cfg)
        self.stock_df: pd.DataFrame | None = None
        self.cambios_df: pd.DataFrame | None = None
        self.taller = None
        self.vm: TallerVM | None = None
        self.idx = 0
        self.playing = False
        self.speed = 2

        self.runner = SimRunner(self)
        self.runner.finished.connect(self._sim_finalizada)
        self.runner.error.connect(self._sim_error)

        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._tick)

        self._build()
        self._cargar_demo_inicial()

    # ── Construcción de la UI ─────────────────────────────────────────────────
    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        cuerpo = QHBoxLayout()
        cuerpo.setContentsMargins(0, 0, 0, 0)
        cuerpo.setSpacing(0)
        root.addLayout(cuerpo, 1)

        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.ejecutar.connect(self._ejecutar)
        self.sidebar.toggle_play.connect(self._toggle_play)
        self.sidebar.stop.connect(self._stop)
        self.sidebar.step.connect(self._step)
        self.sidebar.set_speed.connect(self._set_speed)
        self.sidebar.seek.connect(self._seek)
        self.sidebar.exportar.connect(self._exportar)
        cuerpo.addWidget(self.sidebar)

        # Área derecha
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        cuerpo.addWidget(right, 1)

        # Barra de pestañas
        tabbar = QFrame()
        tabbar.setFixedHeight(50)
        tabbar.setObjectName("tabbar")
        tabbar.setStyleSheet(f"QFrame#tabbar{{background:{T.BG}; border-bottom:1px solid {T.BORDER_SOFT};}}")
        tb = QHBoxLayout(tabbar)
        tb.setContentsMargins(14, 0, 14, 0)
        tb.setSpacing(3)
        self._tab_btns = {}
        for key, name in TABS:
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._cambiar_tab(k))
            self._tab_btns[key] = b
            tb.addWidget(b)
        tb.addStretch()
        self.clock = label("--:--", color=T.TEXT_MUTE, size=12, family=T.FONT_MONO)
        tb.addWidget(self.clock)
        right_lay.addWidget(tabbar)

        # Contenido (stack scrollable)
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background:{T.BG};")
        right_lay.addWidget(self.stack, 1)

        self.views = {
            "vista": VistaReal(),
            "dashboard": VistaDashboard(),
            "analisis": VistaAnalisis(),
            "inventario": VistaInventario(self),
            "kpis": VistaKpis(),
            "generacion": VistaGeneracion(self),
            "config": VistaConfig(self),
            "consola": VistaConsola(),
        }
        self._stack_index = {}
        for i, (key, _name) in enumerate(TABS):
            self.stack.addWidget(self._envolver_scroll(self.views[key]))
            self._stack_index[key] = i

        # Status bar
        self.statusbar = self._build_statusbar()
        root.addWidget(self.statusbar)

        # Overlay de carga
        self.overlay = self._build_overlay()

        self._cambiar_tab("vista")
        self.sidebar.set_flujo(0, 0, False)

    def _envolver_scroll(self, w: QWidget) -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        # Sin scroll horizontal: fuerza el contenido al ancho del viewport (evita
        # que las grillas de 2 columnas se desborden y aparezca una barra lateral).
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        cont = QWidget()
        cont.setStyleSheet(f"background:{T.BG};")
        lay = QVBoxLayout(cont)
        lay.setContentsMargins(18, 18, 18, 18)
        lay.addWidget(w)
        sa.setWidget(cont)
        return sa

    def _build_statusbar(self) -> QFrame:
        bar = QFrame()
        bar.setFixedHeight(30)
        bar.setObjectName("statusbar")
        bar.setStyleSheet(f"QFrame#statusbar{{background:{T.PANEL}; border-top:1px solid {T.BORDER_SOFT};}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(18)
        lay.addWidget(label("● Listo", color=T.GREEN, size=11.5))
        self.sb_clock = label("--:--", color=T.TEXT_MUTE, size=11.5, family=T.FONT_MONO)
        lay.addWidget(self.sb_clock)
        self.sb_snap = label("Snapshot 0/0", color=T.TEXT_MUTE, size=11.5)
        lay.addWidget(self.sb_snap)
        lay.addStretch()
        self.sb_estado = label("○ sin servidor", color=T.ORANGE_2, size=11.5, family=T.FONT_MONO)
        lay.addWidget(self.sb_estado)
        et = ESTRATEGIAS_SELECCION.get(self.estrategia)
        self.sb_estr = label(f"v4 · {et.etiqueta if et else self.estrategia}", color=T.TEXT_DIM, size=11.5)
        lay.addWidget(self.sb_estr)
        return bar

    def _build_overlay(self) -> QWidget:
        ov = QWidget(self)
        ov.setStyleSheet("background:rgba(0,0,0,0.65);")
        lay = QVBoxLayout(ov)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)
        self._spinner = QLabel("◜")
        self._spinner.setAlignment(Qt.AlignCenter)
        self._spinner.setStyleSheet(f"color:{T.ORANGE}; font-size:42px; background:transparent;")
        lay.addWidget(self._spinner)
        t1 = label("Ejecutando simulación…", color=T.TEXT, size=15, weight=600, family=T.FONT_DISPLAY)
        t1.setAlignment(Qt.AlignCenter)
        lay.addWidget(t1)
        t2 = label("Puede tomar algunos segundos", color=T.TEXT_MUTE, size=12)
        t2.setAlignment(Qt.AlignCenter)
        lay.addWidget(t2)
        ov.hide()
        self._spin_timer = QTimer(self)
        self._spin_frames = ["◜", "◝", "◞", "◟"]
        self._spin_i = 0
        self._spin_timer.timeout.connect(self._girar_spinner)
        return ov

    def _girar_spinner(self):
        self._spin_i = (self._spin_i + 1) % len(self._spin_frames)
        self._spinner.setText(self._spin_frames[self._spin_i])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "overlay"):
            self.overlay.setGeometry(self.centralWidget().rect())

    # ── Pestañas ──────────────────────────────────────────────────────────────
    def _cambiar_tab(self, key: str):
        self.stack.setCurrentIndex(self._stack_index[key])
        for k, b in self._tab_btns.items():
            activo = k == key
            b.setStyleSheet(
                f"QPushButton{{padding:7px 12px; border-radius:8px; font-weight:600; font-size:13px;"
                f" background:{T.tint(T.ORANGE, '1f') if activo else 'transparent'};"
                f" color:{T.ORANGE if activo else T.TEXT_MUTE}; border:none;}}"
                f"QPushButton:hover{{color:{T.TEXT_2};}}")

    # ── Carga de stock / cambios ──────────────────────────────────────────────
    def _cargar_demo_inicial(self):
        """Carga el dataset de ejemplo y corre una simulación al arrancar.

        Da una UI poblada con datos reales out-of-the-box (look idéntico al HTML),
        degradando con elegancia si el Excel de ejemplo no está disponible.
        """
        if not os.path.exists(_EXCEL_DEMO):
            return
        try:
            self.cargar_stock(_EXCEL_DEMO, simular=True)
        except Exception:
            pass

    def cargar_stock(self, fp: str, *, simular: bool = False):
        """Carga la hoja Stock_Inicial (y Programa_Cambios si existe) de un Excel."""
        stock_df = pd.read_excel(fp, sheet_name="Stock_Inicial")
        try:
            cambios_df = pd.read_excel(fp, sheet_name="Programa_Cambios")
        except Exception:
            cambios_df = None
        self.stock_df = stock_df
        self.cambios_df = cambios_df
        self.views["inventario"].set_stock(stock_df)
        n_cam = 0 if cambios_df is None else len(cambios_df)
        self.sidebar.set_flujo(len(stock_df), n_cam, self.taller is not None)
        if simular:
            self._ejecutar()

    def abrir_stock(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Cargar stock (Excel)", _RAIZ, "Excel (*.xlsx)")
        if fp:
            self.cargar_stock(fp)

    # ── Simulación ────────────────────────────────────────────────────────────
    def _ejecutar(self):
        if self.stock_df is None or self.runner.corriendo:
            return
        self.sidebar.set_run_enabled(False)
        self.overlay.setGeometry(self.centralWidget().rect())
        self.overlay.show()
        self.overlay.raise_()
        self._spin_timer.start(120)
        self.estrategia = obtener_estrategia_seleccion(self.cfg)
        cambios = self.cambios_df
        if cambios is None and self.views["generacion"].cambios_df is not None:
            cambios = self.views["generacion"].cambios_df
        self.runner.lanzar(self.cfg, self.stock_df, cambios, self.estrategia)

    def _sim_error(self, msg: str):
        self._spin_timer.stop()
        self.overlay.hide()
        self.sidebar.set_run_enabled(True)
        self.sb_estado.setText("⚠ error")
        self.sb_estado.setStyleSheet(f"color:{T.RED}; font-size:11.5px; font-family:{T.FONT_MONO}; background:transparent;")
        self.views["consola"].append(f"⚠ Error en la simulación: {msg}")

    def _sim_finalizada(self, taller):
        self._spin_timer.stop()
        self.overlay.hide()
        self.sidebar.set_run_enabled(True)
        self.taller = taller
        et = ESTRATEGIAS_SELECCION.get(self.estrategia)
        self.vm = TallerVM(taller, et.etiqueta if et else self.estrategia)
        self.idx = 0
        self.playing = False
        self.play_timer.stop()

        # Marcas de parada en porcentaje
        marcas = [i / max(1, self.vm.N - 1) * 100 for i in self.vm.parada_marks]
        self.sidebar.set_parada_marks(marcas)
        self.sidebar.set_flujo(self.vm.total_cil(),
                               0 if self.cambios_df is None else len(self.cambios_df), True)
        self.sb_estado.setText(f"● {self.vm.N} snapshots")
        self.sb_estado.setStyleSheet(f"color:{T.GREEN}; font-size:11.5px; font-family:{T.FONT_MONO}; background:transparent;")

        # Refrescos estáticos (una vez por taller)
        self.views["vista"].set_vm(self.vm)
        self.views["kpis"].set_taller(taller)
        self.views["consola"].set_taller(taller)
        self.views["inventario"].set_taller(taller)
        self.views["dashboard"].set_vm(self.vm)
        self.views["analisis"].set_vm(self.vm)
        self.views["generacion"].refrescar_timeline(taller)

        self._aplicar_snapshot()
        self.sidebar.set_play_label(False)

    # ── Reproducción ──────────────────────────────────────────────────────────
    def _aplicar_snapshot(self):
        if self.vm is None or self.vm.N == 0:
            return
        self.idx = max(0, min(self.idx, self.vm.N - 1))
        self.views["vista"].update_snapshot(self.idx)
        reloj = self.vm.reloj(self.idx)
        self.clock.setText(reloj)
        self.sb_clock.setText(reloj)
        self.sb_snap.setText(f"Snapshot {self.idx + 1}/{self.vm.N}")
        self.sidebar.set_snapshot(self.idx, self.vm.N)

    def _tick(self):
        if self.vm is None:
            return
        if self.idx + 1 >= self.vm.N:
            self._stop_play()
            return
        self.idx += 1
        self._aplicar_snapshot()

    def _toggle_play(self):
        if self.vm is None or self.vm.N == 0:
            return
        if self.playing:
            self._stop_play()
        else:
            self.playing = True
            self.sidebar.set_play_label(True)
            self.play_timer.start(round(800 / self.speed))

    def _stop_play(self):
        self.playing = False
        self.play_timer.stop()
        self.sidebar.set_play_label(False)

    def _stop(self):
        self._stop_play()
        self.idx = 0
        self._aplicar_snapshot()

    def _step(self, delta: int):
        if self.vm is None:
            return
        self._stop_play()
        self.idx = max(0, min(self.vm.N - 1, self.idx + delta))
        self._aplicar_snapshot()

    def _set_speed(self, v: int):
        self.speed = v
        self.sidebar.set_speed_active(v)
        if self.playing:
            self.play_timer.start(round(800 / self.speed))

    def _seek(self, val: int):
        if self.vm is None:
            return
        self._stop_play()
        self.idx = val
        self._aplicar_snapshot()

    def ir_a_momento(self, idx: int):
        """Salta a un snapshot y muestra Vista Real (usado por marcadores de parada)."""
        self._seek(idx)
        self._cambiar_tab("vista")

    def _exportar(self):
        if self.taller is None:
            return
        fp, _ = QFileDialog.getSaveFileName(self, "Exportar resultados", _RAIZ, "Excel (*.xlsx)")
        if not fp:
            return
        try:
            filas = [{"ID": c.id, "Diámetro": round(c.diametro, 1),
                      "Original": round(c.diametro_original, 1),
                      "Estado": c.estado.value} for c in self.taller.cilindros.values()]
            pd.DataFrame(filas).to_excel(fp, index=False)
            self.views["consola"].append(f"Resultados exportados a {os.path.basename(fp)}")
        except Exception as e:  # noqa: BLE001
            self.views["consola"].append(f"⚠ No se pudo exportar: {e}")
