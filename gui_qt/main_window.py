"""Ventana principal (fase 1) de la nueva GUI Qt."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from config.persistencia import (
    cargar_config,
    obtener_config_global,
    obtener_estrategia_seleccion,
    obtener_maquinas,
)

from gui_qt.analysis_qt import AnalysisPanel
from gui_qt.config_qt import ConfigPanel
from gui_qt.console_qt import ConsolePanel
from gui_qt.dashboard_qt import DashboardPanel
from gui_qt.generation_qt import GenerationPanel
from gui_qt.inventory_qt import InventoryPanel
from gui_qt.playback_slider_qt import PlaybackTimelineSlider
from gui_qt.sidebar_qt import build_sidebar
from gui_qt.services import SimulationRequest, SimulationService
from gui_qt.tab_kpis_qt import KpisPanel
from gui_qt.vista_realtime import RealTimeView
from gui_qt.widgets import FlowCard, SectionCard, StatusBarWidget, TabsCornerInfoWidget


@dataclass
class PlaybackState:
    """Estado minimo de reproduccion para la shell inicial."""

    current_index: int = 0
    total_snapshots: int = 0
    speed: int = 1


class MainWindow(QMainWindow):
    """Shell visual inicial para migracion incremental de la GUI."""

    TAB_NAMES = [
        "Vista Real",
        "Dashboard",
        "Analisis",
        "Inventario",
        "KPIs",
        "Generacion",
        "Configuracion",
        "Consola",
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Simulador de Cilindros Pro v5 (Qt Preview)")
        self.resize(1460, 860)

        self.playback = PlaybackState()
        self.user_cfg = cargar_config()
        self.estrategia = obtener_estrategia_seleccion(self.user_cfg)
        self.stock_df: "pd.DataFrame | None" = None
        self.cambios_df: "pd.DataFrame | None" = None
        self.taller = None

        self.sim_service = SimulationService()
        self.sim_future = None
        # Estado persistente del flujo — None = no cambiado, True/False = on/off
        self._flow_state = {"inventario": False, "generacion": False, "simulacion": False}

        # Widgets creados por build_sidebar(...)
        self.btn_run: QPushButton
        self.btn_prev: QPushButton
        self.btn_play: QPushButton
        self.btn_stop: QPushButton
        self.btn_next: QPushButton
        self.slider: PlaybackTimelineSlider
        self.snapshot_label: QLabel
        self.lbl_export: QLabel
        self.dot_flow_inv: QLabel
        self.dot_flow_gen: QLabel
        self.dot_flow_sim: QLabel
        self.lbl_flow_inv: QLabel
        self.lbl_flow_gen: QLabel
        self.lbl_flow_sim: QLabel
        self.lbl_flow_inv_count: QLabel
        self.lbl_flow_gen_count: QLabel
        self.lbl_flow_sim_count: QLabel
        self.flow_card: FlowCard
        self.status_widget: StatusBarWidget
        self.tabs_corner_widget: TabsCornerInfoWidget

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(120)
        self.poll_timer.timeout.connect(self._poll_simulation)

        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._play_tick)

        root = QWidget(self)
        self.setCentralWidget(root)

        frame = QGridLayout(root)
        frame.setContentsMargins(0, 0, 0, 0)
        frame.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = self._build_sidebar()
        body.addWidget(self.sidebar, 0)

        self.content = self._build_content_area()
        body.addWidget(self.content, 1)

        frame.addLayout(body, 0, 0)
        self.status_bar = self._build_status_bar()
        frame.addWidget(self.status_bar, 1, 0)

        self._update_run_button_state()
        self._update_playback_button_state()
        self._sync_preview_from_config()

    def _build_sidebar(self) -> QFrame:
        return build_sidebar(self, PlaybackTimelineSlider)

    def _build_content_area(self) -> QWidget:
        """Construye el panel principal con acciones superiores y tabs."""
        container = QWidget(self)
        col = QVBoxLayout(container)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.tabs = self._build_tabs()

        self.tabs_corner_widget = TabsCornerInfoWidget(self)
        self.top_state = self.tabs_corner_widget.top_state
        self.top_clock = self.tabs_corner_widget.top_clock
        self.tabs.setCornerWidget(self.tabs_corner_widget, Qt.Corner.TopRightCorner)
        col.addWidget(self.tabs, 1)

        return container

    def _build_tabs(self) -> QTabWidget:
        """Construye tabs y paneles funcionales de la migracion Qt."""
        tabs = QTabWidget(self)
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        tabs.setTabPosition(QTabWidget.TabPosition.North)

        self.realtime_view = RealTimeView(self)
        self.realtime_view.set_strategy(self.estrategia)
        self.realtime_view.set_placeholder(
            "VISTA REAL - Cargue un Excel con Stock_Inicial y Programa_Cambios"
        )

        self.kpis_panel = KpisPanel(self)
        self.dashboard_panel = DashboardPanel(self)
        self.analysis_panel = AnalysisPanel(self)
        self.inventory_panel = InventoryPanel(self)
        self.inventory_panel.set_load_callback(self._load_excel)
        self.generation_panel = GenerationPanel(
            self.user_cfg,
            on_cfg_saved=self._on_cfg_saved,
            on_cambios_generated=self._on_changes_generated,
            on_go_to_snapshot=self._go_to_snapshot,
            parent=self,
        )
        self.console_panel = ConsolePanel(self)
        self.config_panel = ConfigPanel(self.user_cfg, on_saved=self._on_cfg_saved, parent=self)

        for name in self.TAB_NAMES:
            page = QWidget()
            page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            page_col = QVBoxLayout(page)
            page_col.setContentsMargins(14, 14, 14, 14)

            card = SectionCard(
                self,
                object_name="Card",
                margins=(14, 12, 14, 12),
                spacing=8,
            )
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            card_col = card.content_layout()
            if name == "Vista Real":
                card_col.addWidget(self.realtime_view)
            elif name == "Dashboard":
                title = QLabel(name)
                title.setObjectName("BoardHeader")
                card_col.addWidget(title)
                card_col.addWidget(self.dashboard_panel)
            elif name == "Analisis":
                title = QLabel(name)
                title.setObjectName("BoardHeader")
                card_col.addWidget(title)
                card_col.addWidget(self.analysis_panel)
            elif name == "Inventario":
                card_col.addWidget(self.inventory_panel, 1)
            elif name == "KPIs":
                title = QLabel(name)
                title.setObjectName("BoardHeader")
                card_col.addWidget(title)
                card_col.addWidget(self.kpis_panel)
            elif name == "Generacion":
                title = QLabel(name)
                title.setObjectName("BoardHeader")
                card_col.addWidget(title)
                card_col.addWidget(self.generation_panel)
            elif name == "Consola":
                title = QLabel(name)
                title.setObjectName("BoardHeader")
                card_col.addWidget(title)
                card_col.addWidget(self.console_panel)
            elif name == "Configuracion":
                title = QLabel(name)
                title.setObjectName("BoardHeader")
                card_col.addWidget(title)
                card_col.addWidget(self.config_panel)
            else:
                title = QLabel(name)
                title.setObjectName("BoardHeader")
                card_col.addWidget(title)
                hint = QLabel("Vista preliminar en construccion para la migracion a Qt.")
                hint.setObjectName("Muted")
                card_col.addWidget(hint)

            page_col.addWidget(card, 1)
            tabs.addTab(page, name)

        return tabs

    def _build_status_bar(self) -> QFrame:
        self.status_widget = StatusBarWidget(self)
        self.status_main_label = self.status_widget.status_main_label
        self.status_clock = self.status_widget.status_clock
        self.status_snap = self.status_widget.status_snap
        self.progress_sim = self.status_widget.progress_sim
        self.status_strategy = self.status_widget.status_strategy
        return self.status_widget

    def _set_speed(self, value: int) -> None:
        self.playback.speed = value
        if self.play_timer.isActive():
            self.play_timer.start(self._play_interval_ms())

    def _load_excel(self) -> None:
        """Carga stock+cambios desde un Excel y habilita la simulacion."""
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Excel de simulacion",
            str(Path.cwd()),
            "Archivos Excel (*.xlsx *.xlsm)",
        )
        if not selected:
            return

        try:
            self.stock_df = pd.read_excel(selected, sheet_name="Stock_Inicial")
            self.cambios_df = pd.read_excel(selected, sheet_name="Programa_Cambios")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el Excel:\n{exc}")
            return

        self.status_main_label.setText(f"Excel cargado: {Path(selected).name}")
        self.top_state.setText("● excel cargado")
        # Cargar un nuevo Excel invalida overlays de PARADA previos.
        self.flow_card.set_counts(inventario=len(self.stock_df) if self.stock_df is not None else 0)
        self._set_flow_status(inventario=True)
        self.generation_panel.set_simulation_snapshots([])
        self.inventory_panel.refresh(taller=self.taller, stock_df=self.stock_df)
        self._update_run_button_state()

    def _run_simulation(self) -> None:
        """Lanza la simulacion usando el servicio en proceso separado."""
        if self.stock_df is None or self.cambios_df is None:
            QMessageBox.warning(
                self,
                "Atencion",
                "Primero cargue un Excel con Stock_Inicial y Programa_Cambios.",
            )
            return

        if self.sim_future is not None:
            return

        estrategia = obtener_estrategia_seleccion(self.user_cfg)
        self.estrategia = estrategia
        self.realtime_view.set_strategy(estrategia)
        request = SimulationRequest(
            cfg=self.user_cfg,
            stock_df=self.stock_df,
            cambios_df=self.cambios_df,
            estrategia=estrategia,
        )
        self.sim_future = self.sim_service.submit(request)
        self.status_main_label.setText("Simulando...")
        self.top_state.setText("● simulando")
        self.progress_sim.setVisible(True)
        self._update_run_button_state()
        self._stop_play()
        self.poll_timer.start()

    def _poll_simulation(self) -> None:
        """Sondea el future de simulacion sin bloquear la UI."""
        if self.sim_future is None:
            self.poll_timer.stop()
            return
        if not self.sim_future.done():
            return

        self.poll_timer.stop()
        fut = self.sim_future
        self.sim_future = None
        try:
            self.taller = fut.result()
        except Exception as exc:
            self.status_main_label.setText("Error en simulacion")
            self.progress_sim.setVisible(False)
            self._update_run_button_state()
            QMessageBox.critical(self, "Error", f"No se pudo ejecutar la simulacion:\n{exc}")
            return

        self.playback.current_index = 0
        self.playback.total_snapshots = len(self.taller.snapshots)
        self.slider.setMaximum(max(0, self.playback.total_snapshots - 1))
        self.slider.setValue(0)
        self.realtime_view.set_jaula_count(self.taller.cantidad_jaulas)
        self.realtime_view.set_machine_names(list(self.taller.machines.keys()))
        mapa = {}
        for i in range(1, self.taller.cantidad_jaulas + 1):
            ss = self.taller.obtener_substock_por_jaula(i)
            if ss is not None:
                mapa[i] = ss.nombre
        escala = max(
            (v for sn in self.taller.snapshots for v in sn.disponibles_por_substock.values()),
            default=0,
        )
        self.realtime_view.configure_disponibilidad(mapa, escala)
        alertas_crit = sum(1 for a in getattr(self.taller, "alertas", []) if getattr(a, "tipo", "") == "CRITICO")
        self.realtime_view.set_alertas_criticas(alertas_crit)
        # Sincroniza paneles con el resultado final de la corrida.
        self._render_snapshot_summary()
        self.dashboard_panel.render(self.taller)
        self.analysis_panel.render(self.taller)
        self.kpis_panel.render(self.taller)
        self.inventory_panel.refresh(taller=self.taller, stock_df=self.stock_df)
        # Entrega snapshots a Generacion para overlays/marcadores de PARADA.
        self.generation_panel.set_simulation_snapshots(self.taller.snapshots)
        self.flow_card.set_counts(
            generacion=len(self.cambios_df) if self.cambios_df is not None else 0,
            simulacion=self.playback.total_snapshots,
        )
        self._set_flow_status(inventario=True, generacion=True, simulacion=True)

        lineas = []
        lineas.extend(getattr(self.taller, "avisos_carga", []))
        lineas.extend(getattr(self.taller, "log_simulacion", []))
        self.console_panel.set_lines(lineas)
        self.status_main_label.setText(
            f"Simulacion completada. Snapshots: {self.playback.total_snapshots}"
        )
        self.top_state.setText("● simulacion completa")
        self.progress_sim.setVisible(False)
        self._update_run_button_state()
        self._update_playback_button_state()

    def _on_seek(self, value: int) -> None:
        """Actualiza el resumen de Vista Real al mover el slider."""
        if self.taller is None or not self.taller.snapshots:
            return
        self.playback.current_index = max(0, min(value, len(self.taller.snapshots) - 1))
        self.status_snap.setText(f"Snapshot {self.playback.current_index + 1}/{len(self.taller.snapshots)}")
        self._render_snapshot_summary()

    def _render_snapshot_summary(self) -> None:
        """Actualiza etiquetas globales y la Vista Real del snapshot activo."""
        if self.taller is None or not self.taller.snapshots:
            self.snapshot_label.setText("snapshot 0 / 0")
            self.slider.set_markers([], 0)
            self.realtime_view.set_placeholder(
                "VISTA REAL - Cargue un Excel con Stock_Inicial y Programa_Cambios"
            )
            return

        idx = self.playback.current_index
        total = len(self.taller.snapshots)
        snap = self.taller.snapshots[idx]

        self.snapshot_label.setText(f"snapshot {idx + 1} / {total}")
        self.status_snap.setText(f"Snapshot {idx + 1}/{total}")
        now_txt = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.status_clock.setText(now_txt)
        self.top_clock.setText(now_txt)
        self.status_strategy.setText(f"estrategia: {self.estrategia}")
        self._update_playback_markers()
        self.realtime_view.update_from_snapshot(snap)

    def _update_playback_markers(self) -> None:
        """Calcula inicios de PARADA y pinta marcadores sobre el slider."""
        if self.taller is None or not self.taller.snapshots:
            self.slider.set_markers([], 0)
            return
        inicios: list[int] = []
        prev_parada = False
        for i, snap in enumerate(self.taller.snapshots):
            curr_parada = bool(getattr(snap, "jaulas_paradas", []))
            if curr_parada and not prev_parada:
                inicios.append(i)
            prev_parada = curr_parada
        self.slider.set_markers(inicios, len(self.taller.snapshots))

    def _update_run_button_state(self) -> None:
        """Habilita/deshabilita acciones segun estado de datos/simulacion."""
        running = self.sim_future is not None
        ready = self.stock_df is not None and self.cambios_df is not None
        self.btn_run.setEnabled(ready and not running)

    def _update_playback_button_state(self) -> None:
        """Actualiza la disponibilidad de controles de reproduccion."""
        has_snaps = self.taller is not None and bool(self.taller.snapshots)
        self.btn_prev.setEnabled(has_snaps)
        self.btn_play.setEnabled(has_snaps)
        self.btn_stop.setEnabled(has_snaps)
        self.btn_next.setEnabled(has_snaps)
        self.slider.setEnabled(has_snaps)

    def _toggle_play(self) -> None:
        """Alterna reproduccion automatica de snapshots."""
        if self.taller is None or not self.taller.snapshots:
            self.btn_play.setChecked(False)
            return
        if self.btn_play.isChecked():
            self.btn_play.setText("❚❚ Pausa")
            self.play_timer.start(self._play_interval_ms())
        else:
            self.btn_play.setText("▶ Play")
            self.play_timer.stop()

    def _stop_play(self) -> None:
        """Detiene la reproduccion y vuelve al primer snapshot."""
        self.play_timer.stop()
        self.btn_play.setChecked(False)
        self.btn_play.setText("▶ Play")
        if self.taller is None or not self.taller.snapshots:
            return
        self.playback.current_index = 0
        self.slider.blockSignals(True)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self._render_snapshot_summary()

    def _step(self, delta: int) -> None:
        """Avanza o retrocede un snapshot en modo manual."""
        if self.taller is None or not self.taller.snapshots:
            return
        self.play_timer.stop()
        self.btn_play.setChecked(False)
        self.btn_play.setText("▶ Play")

        total = len(self.taller.snapshots)
        new_idx = max(0, min(total - 1, self.playback.current_index + delta))
        self.playback.current_index = new_idx
        self.slider.blockSignals(True)
        self.slider.setValue(new_idx)
        self.slider.blockSignals(False)
        self._render_snapshot_summary()

    def _play_tick(self) -> None:
        """Tick de reproduccion automatica."""
        if self.taller is None or not self.taller.snapshots:
            self._stop_play()
            return

        total = len(self.taller.snapshots)
        if self.playback.current_index >= total - 1:
            self.play_timer.stop()
            self.btn_play.setChecked(False)
            self.btn_play.setText("▶ Play")
            return

        self.playback.current_index += 1
        self.slider.blockSignals(True)
        self.slider.setValue(self.playback.current_index)
        self.slider.blockSignals(False)
        self._render_snapshot_summary()

    def _play_interval_ms(self) -> int:
        """Intervalo de reproduccion segun velocidad seleccionada."""
        speed = max(1, int(self.playback.speed))
        return max(40, int(1000 / speed))

    def _set_flow_status(
        self,
        inventario: bool | None = None,
        generacion: bool | None = None,
        simulacion: bool | None = None,
    ) -> None:
        """Actualiza los indicadores del bloque FLUJO en sidebar.

        Pasar ``None`` (defecto) preserva el estado actual del paso.
        Pasar ``True``/``False`` actualiza ese paso en concreto.
        """
        if inventario is not None:
            self._flow_state["inventario"] = inventario
        if generacion is not None:
            self._flow_state["generacion"] = generacion
        if simulacion is not None:
            self._flow_state["simulacion"] = simulacion

        inv = self._flow_state["inventario"]
        gen = self._flow_state["generacion"]
        sim = self._flow_state["simulacion"]

        self.flow_card.apply_state(inv, gen, sim)

    def _on_cfg_saved(self, cfg: dict) -> None:
        """Aplica en runtime la configuracion recien guardada."""
        self.user_cfg = cfg
        self.config_panel.set_cfg(self.user_cfg)
        self.generation_panel.set_cfg(self.user_cfg)
        self.estrategia = obtener_estrategia_seleccion(self.user_cfg)
        self.realtime_view.set_strategy(self.estrategia)
        self._sync_preview_from_config()
        self.status_main_label.setText("Configuracion guardada")
        self.top_state.setText("● configuracion guardada")

    def _on_changes_generated(self, cambios_df: pd.DataFrame) -> None:
        """Recibe Programa_Cambios generado y lo aplica al flujo de simulacion."""
        self.cambios_df = cambios_df
        self._set_flow_status(inventario=self.stock_df is not None, generacion=True)
        self.flow_card.set_counts(generacion=len(cambios_df))
        self.status_main_label.setText(f"Cambios generados: {len(cambios_df)} filas")
        self.top_state.setText("● cambios generados")
        self._update_run_button_state()

    def _go_to_snapshot(self, idx: int) -> None:
        """Navega al snapshot indicado y cambia a la pestaña Vista Real."""
        if self.taller is None or not self.taller.snapshots:
            return
        # Clamp defensivo por si llega un índice fuera de rango desde timeline.
        i = max(0, min(int(idx), len(self.taller.snapshots) - 1))
        self.playback.current_index = i
        self.slider.blockSignals(True)
        self.slider.setValue(i)
        self.slider.blockSignals(False)
        self._render_snapshot_summary()
        self.tabs.setCurrentIndex(0)

    def closeEvent(self, event) -> None:  # noqa: N802
        """Limpia recursos de procesos al cerrar la ventana."""
        self.poll_timer.stop()
        self.play_timer.stop()
        self.progress_sim.setVisible(False)
        self.sim_service.shutdown()
        super().closeEvent(event)

    def _sync_preview_from_config(self) -> None:
        """Previsualiza jaulas y rectificadoras desde la configuracion activa."""
        cfg = self.user_cfg or {}
        cg = obtener_config_global(cfg)
        n_jaulas = int(cg.get("cantidad_jaulas", 4))
        names = [str(m.get("nombre", "")).strip() for m in obtener_maquinas(cfg)]
        names = [n for n in names if n]

        self.realtime_view.set_jaula_count(max(1, n_jaulas))
        self.realtime_view.set_machine_names(names or ["RECT-01", "RECT-02", "DESB-01"])

        # Mientras no hay simulacion, dejamos stock/operativa en estado base.
        for card in self.realtime_view.stock_cards.values():
            card.set_value(0, 1)
        for card in self.realtime_view.machine_cards.values():
            card.set_state(None, operativa=True)
