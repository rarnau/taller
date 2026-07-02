"""Pestaña Monte Carlo: barrido de miles de corridas con parámetros sorteados.

Panel izquierdo (``_build_left``): una ``MachineCard`` por máquina (rangos de
rate prod/desb y tasa de falla, prioridad y turnos), rangos globales (enfriado,
traslado CRC), selectores fijos (estrategias, generador, duración, turnos vía
``ChipSelector``), N de corridas y set de resultados.
Panel derecho: ``ResultsView`` (cards de KPIs P10/P50/P90, histogramas y tabla
resumen, con export a CSV).

Este módulo quedó como **orquestador**: los componentes de UI viven aislados en
``gui_qt/widgets/montecarlo/`` y acá se componen y se cablean a la ejecución (el
armado/lectura de la spec, el set de resultados y las llamadas al servicio).

La ejecución corre en un hilo de fondo (``MonteCarloService``) que a su vez usa
el pool de procesos de ``montecarlo.correr_montecarlo``; ``MainWindow`` sondea el
avance con un ``QTimer`` (mismo patrón que la simulación simple).
"""
from __future__ import annotations

import copy
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import tema
from config import generator_model as model_store
from config.persistencia import (
    guardar_config,
    obtener_maquinas,
    obtener_montecarlo,
    set_montecarlo,
)
from modelos.estrategias import (ESTRATEGIAS_ASIGNACION, ESTRATEGIAS_REPOSICION,
                                 ESTRATEGIAS_SELECCION)
from modelos.generador_cambios import GENERADORES_CAMBIOS
from modelos import turnos as turnos_mod
from nucleo.montecarlo import (EspecMonteCarlo, cargar_filas_csv, cargar_spec_sidecar,
                               exportar_resumen_csv)
from gui_qt.services import MonteCarloRequest
from gui_qt.widgets import SectionCard
from gui_qt.widgets.montecarlo import (
    ChipSelector,
    MachineCard,
    RangeRow,
    ResultsView,
)


class MonteCarloPanel(QWidget):
    """Panel de configuración y resultados del estudio de Monte Carlo."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        on_run: Callable[[MonteCarloRequest], None],
        on_cfg_saved: Callable[[Dict[str, Any]], None] | None = None,
        on_pause: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = copy.deepcopy(cfg)
        self._on_run = on_run
        self._on_cfg_saved = on_cfg_saved
        self._on_pause = on_pause
        self._stock_df: Optional[pd.DataFrame] = None
        # Set de resultados: CSV incremental + sidecar <csv>.spec.json con la
        # spec (rangos/fijos/seed). Por defecto un archivo temporal; "cambiar…"
        # permite fijar una ruta durable para pausar hoy y reanudar otro día.
        self._csv_path: str = os.path.join(tempfile.gettempdir(), "montecarlo_resultados.csv")
        self._corriendo = False  # el botón Ejecutar/Pausar alterna según esto

        # Rangos globales (clave -> RangeRow) y una card por máquina.
        self._rangos_global: Dict[str, RangeRow] = {}
        self._maq_cards: Dict[str, MachineCard] = {}
        self._run_preset_buttons: List[Tuple[int, QPushButton]] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_left(), 0)
        self.results = ResultsView()
        self.results.exportCorridas.connect(self._exportar_corridas)
        self.results.exportResumen.connect(self._exportar_resumen)
        root.addWidget(self.results, 1)
        self._reload_widgets_from_cfg()

    # ── Construcción UI ──────────────────────────────────────────────────────

    def _build_left(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Panel más ancho para que el chip de estrategia más largo (p. ej.
        # "Menor mm + jaula stock (desb) / más necesitada (prod)") entre completo
        # sin recortarse contra el borde de la card.
        scroll.setMinimumWidth(355)
        scroll.setMaximumWidth(390)
        # Sin scroll horizontal: el contenido se ajusta al ancho y los valores
        # de los sliders (a la derecha) nunca quedan recortados.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        cont = QWidget()
        col = QVBoxLayout(cont)
        col.setContentsMargins(6, 4, 12, 4)
        col.setSpacing(10)

        # Una card por máquina (rate prod/desb, tasa de falla, prioridad, turnos).
        self._maq_box = QVBoxLayout()
        self._maq_box.setSpacing(10)
        col.addLayout(self._maq_box)

        # Globales.
        card_g = SectionCard(title="GLOBALES", object_name="CardSoft")
        gl = card_g.content_layout()
        rr_enf = RangeRow("Tiempo de enfriamiento", "h", 24.0, 0.5, 1)
        rr_crc = RangeRow("Tiempo traslado CRC", "min", 120.0, 1.0, 0)
        self._rangos_global["tiempo_enfriado"] = rr_enf
        self._rangos_global["tiempo_traslado_crc"] = rr_crc
        gl.addWidget(rr_enf)
        gl.addWidget(rr_crc)
        col.addWidget(card_g)

        # Selectores fijos.
        card_f = SectionCard(title="CONFIGURACIÓN FIJA", object_name="CardSoft")
        fl = card_f.content_layout()
        self.sel_estrategia = ChipSelector(
            "Estrategia de rectificado",
            [(k, v.etiqueta) for k, v in ESTRATEGIAS_SELECCION.items()],
            chip_object_name="McOptionChip")
        self.sel_asignacion = ChipSelector(
            "Estrategia de asignación",
            [(k, v.etiqueta) for k, v in ESTRATEGIAS_ASIGNACION.items()],
            chip_object_name="McOptionChip")
        self.sel_reposicion = ChipSelector(
            "Estrategia de reposición",
            [(k, v.etiqueta) for k, v in ESTRATEGIAS_REPOSICION.items()],
            chip_object_name="McOptionChip")
        self.sel_generador = ChipSelector(
            "Generador de cambios",
            [(k, g.etiqueta) for k, g in GENERADORES_CAMBIOS.items()],
            chip_object_name="McOptionChip")
        self.sel_turnos_lam = ChipSelector(
            "Turnos laminador",
            [(k, turnos_mod.PRESET_LABELS.get(k, k)) for k in turnos_mod.PRESETS],
            chip_object_name="McOptionChip")
        self.sp_duracion = QSpinBox()
        # Sin tope práctico de días: el máximo es el límite del propio QSpinBox
        # (2^31-1), no una restricción del motor. El único freno real de una
        # corrida es max_iteraciones (eventos), no los días.
        self.sp_duracion.setRange(1, 2_000_000_000)
        fl.addWidget(self.sel_estrategia)
        fl.addWidget(self.sel_asignacion)
        fl.addWidget(self.sel_reposicion)
        fl.addWidget(self.sel_generador)
        fl.addLayout(self._fila_widget("Duración de corrida (días)", self.sp_duracion))
        fl.addWidget(self.sel_turnos_lam)
        col.addWidget(card_f)

        # Corridas + seed.
        card_n = SectionCard(title="CORRIDAS", object_name="CardSoft")
        nl = card_n.content_layout()
        self.sp_runs = QSpinBox()
        self.sp_runs.setRange(1, 100000)
        presets = QHBoxLayout()
        presets.setSpacing(6)
        for v in (100, 500, 1000, 2000):
            b = QPushButton(f"{v // 1000}k" if v >= 1000 else str(v))
            b.setObjectName("McPresetChip")
            b.setCheckable(True)
            b.setMinimumWidth(52)
            b.clicked.connect(lambda _=False, n=v: self.sp_runs.setValue(n))
            presets.addWidget(b)
            self._run_preset_buttons.append((v, b))
        nl.addLayout(self._fila_widget("Número de corridas", self.sp_runs))
        nl.addLayout(presets)
        self.sp_runs.valueChanged.connect(self._sync_run_presets)
        self.sp_seed = QSpinBox()
        self.sp_seed.setRange(0, 2_000_000_000)
        self.sp_seed.setSpecialValueText("aleatoria")
        nl.addLayout(self._fila_widget("Master seed (0 = aleatoria)", self.sp_seed))
        self.chk_dump = QCheckBox("Volcar tallers a disco")
        nl.addWidget(self.chk_dump)
        col.addWidget(card_n)

        # Set de resultados: CSV incremental (+ sidecar de spec) donde se
        # acumulan inputs y KPIs de cada corrida. Permite pausar/reanudar y
        # agregar corridas, incluso en otra sesión ("Abrir set…").
        card_s = SectionCard(title="SET DE RESULTADOS", object_name="CardSoft")
        sl = card_s.content_layout()
        fila_set = QHBoxLayout()
        fila_set.setSpacing(6)
        self.lbl_set = QLabel("")
        self.lbl_set.setObjectName("Muted")
        self.lbl_set.setStyleSheet(f"color:{tema.FG2}; font-size:10px; font-family:monospace;")
        fila_set.addWidget(self.lbl_set, 1)
        self.btn_set_path = QPushButton("…")
        self.btn_set_path.setObjectName("PlaybackButton")
        self.btn_set_path.setMaximumWidth(34)
        self.btn_set_path.setToolTip("Elegir el archivo CSV del set (para conservarlo entre sesiones)")
        self.btn_set_path.clicked.connect(self._cambiar_destino_set)
        fila_set.addWidget(self.btn_set_path, 0)
        sl.addLayout(fila_set)
        self.btn_abrir_set = QPushButton("📂 Abrir set (CSV)…")
        self.btn_abrir_set.setObjectName("PlaybackButton")
        self.btn_abrir_set.setToolTip(
            "Carga un set existente: restaura los rangos de input desde su spec "
            "y muestra los resultados acumulados. Después se puede reanudar o "
            "agregar corridas.")
        self.btn_abrir_set.clicked.connect(self._abrir_set)
        sl.addWidget(self.btn_abrir_set)
        col.addWidget(card_s)

        self.btn_run = QPushButton("▶ Ejecutar Monte Carlo")
        self.btn_run.setObjectName("RunButton")
        self.btn_run.clicked.connect(self._toggle_run)
        col.addWidget(self.btn_run)

        self.btn_resume = QPushButton("↻ Reanudar / agregar corridas")
        self.btn_resume.setObjectName("PlaybackButton")
        self.btn_resume.setToolTip(
            "Completa las corridas pendientes del set actual usando los rangos "
            "de su spec (subí «Número de corridas» para agregar más al set).")
        self.btn_resume.setEnabled(False)
        self.btn_resume.clicked.connect(self._reanudar)
        col.addWidget(self.btn_resume)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        col.addWidget(self.progress)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("Muted")
        col.addWidget(self.lbl_progress)

        col.addStretch(1)
        scroll.setWidget(cont)
        self._sync_run_presets(self.sp_runs.value())
        self._refrescar_set_ui()
        return scroll

    # ── Helpers de construcción ──────────────────────────────────────────────

    def _fila_widget(self, label: str, widget: QWidget) -> QVBoxLayout:
        # Apilado (label arriba del control): el ancho de la fila es el del
        # control, no label+control ⇒ las cards entran en el panel angosto.
        box = QVBoxLayout()
        box.setSpacing(2)
        lab = QLabel(label)
        lab.setStyleSheet(f"color:{tema.FG2}; font-size:11px;")
        box.addWidget(lab)
        if isinstance(widget, (QComboBox, QSpinBox)):
            widget.setMinimumHeight(28)
        box.addWidget(widget)
        return box

    def _sync_run_presets(self, value: int) -> None:
        for n, btn in self._run_preset_buttons:
            btn.setChecked(n == value)

    # ── Estado / datos ───────────────────────────────────────────────────────

    def set_stock_df(self, stock_df) -> None:
        self._stock_df = stock_df

    def actualizar_cfg(self, cfg: Dict[str, Any]) -> None:
        """Refresca el cfg base (p. ej. tras guardar en Configuración)."""
        self._cfg = copy.deepcopy(cfg)
        self._rebuild_machine_cards()
        self._reload_widgets_from_cfg()

    def _rebuild_machine_cards(self) -> None:
        # Limpia las cards de máquina previas (cada una encapsula su propio
        # estado: rangos, prioridad y turnos).
        while self._maq_box.count():
            item = self._maq_box.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._maq_cards.clear()

        for m in obtener_maquinas(self._cfg):
            nombre = m["nombre"]
            card = MachineCard(nombre, m.get("prioridad", ""))
            self._maq_cards[nombre] = card
            self._maq_box.addWidget(card)

    def _reload_widgets_from_cfg(self) -> None:
        """Carga los valores de los widgets desde el bloque montecarlo del cfg."""
        if not self._maq_cards:
            self._rebuild_machine_cards()
        self._aplicar_mc_a_widgets(obtener_montecarlo(self._cfg))

    def _aplicar_mc_a_widgets(self, mc: Dict[str, Any]) -> None:
        """Vuelca un dict de spec MC (del cfg o del sidecar de un set) a los widgets.

        Es la operación inversa de ``_mc_desde_widgets``; la usa también «Abrir
        set…» para restaurar los rangos de input con que se generó un CSV.
        """
        self.sp_runs.setValue(int(mc["runs"]))
        self.sp_seed.setValue(int(mc.get("master_seed") or 0))
        fijos = mc.get("fijos", {}) or {}
        self.sel_estrategia.set_current_data(fijos.get("estrategia_seleccion"))
        self.sel_asignacion.set_current_data(fijos.get("estrategia_asignacion"))
        self.sel_reposicion.set_current_data(fijos.get("estrategia_reposicion"))
        self.sel_generador.set_current_data(fijos.get("generador"))
        self.sel_turnos_lam.set_current_data(fijos.get("turnos_laminador_preset"))
        self.sp_duracion.setValue(int(fijos.get("duracion_dias", 7)))

        r = mc.get("rangos", {}) or {}
        self._rangos_global["tiempo_enfriado"].set_values(r.get("tiempo_enfriado"))
        self._rangos_global["tiempo_traslado_crc"].set_values(r.get("tiempo_traslado_crc"))
        for nombre, rr in (r.get("maquinas") or {}).items():
            card = self._maq_cards.get(nombre)
            if card is None:
                continue
            for campo in ("rate_prod", "rate_desb", "tasa_falla"):
                if campo in rr:
                    card.set_rango(campo, rr[campo])

        # Prioridad por máquina (fijo del spec; si falta, queda la de la config).
        prio_por_maq = fijos.get("prioridad_por_maquina") or {}
        for nombre, card in self._maq_cards.items():
            prio = prio_por_maq.get(nombre)
            if prio in ("produccion", "desbaste"):
                card.set_prioridad(prio)

        # Turnos por máquina (preset o grilla compacta personalizada).
        turnos_por_maq = fijos.get("turnos_por_maquina") or {}
        for nombre, card in self._maq_cards.items():
            card.set_turnos(turnos_por_maq.get(nombre, "24x7"))

    def _mc_desde_widgets(self) -> Dict[str, Any]:
        """Arma el dict montecarlo desde los widgets actuales."""
        maquinas = {nombre: card.rangos() for nombre, card in self._maq_cards.items()}
        turnos_por_maquina = {nombre: card.turnos()
                              for nombre, card in self._maq_cards.items()}
        prioridad_por_maquina = {
            nombre: card.prioridad()
            for nombre, card in self._maq_cards.items()
            if card.prioridad() in ("produccion", "desbaste")
        }

        return {
            "runs": self.sp_runs.value(),
            "master_seed": (self.sp_seed.value() or None),
            # Cada chunk refresca progreso Y gráficos parciales ⇒ 10% del total.
            "chunk": max(1, self.sp_runs.value() // 10),
            "fijos": {
                "estrategia_seleccion": self.sel_estrategia.current_data(),
                "estrategia_asignacion": self.sel_asignacion.current_data(),
                "estrategia_reposicion": self.sel_reposicion.current_data(),
                "generador": self.sel_generador.current_data(),
                "duracion_dias": self.sp_duracion.value(),
                "turnos_por_maquina": turnos_por_maquina,
                "prioridad_por_maquina": prioridad_por_maquina,
                "turnos_laminador_preset": self.sel_turnos_lam.current_data(),
            },
            "rangos": {
                "tiempo_enfriado": list(self._rangos_global["tiempo_enfriado"].values()),
                "tiempo_traslado_crc": list(self._rangos_global["tiempo_traslado_crc"].values()),
                "maquinas": maquinas,
            },
        }

    # ── Ejecución / set de resultados ────────────────────────────────────────

    def _validar_prerrequisitos(self) -> Optional[Dict[str, Any]]:
        """Stock + modelo del generador listos; devuelve el modelo o None."""
        if self._stock_df is None:
            QMessageBox.warning(self, "Atención",
                                "Primero cargue un Excel con Stock_Inicial.")
            return None
        modelo = model_store.load_active_model()
        if not modelo:
            QMessageBox.warning(self, "Atención",
                                "No hay modelo del generador. Ajustá uno en la pestaña Generación.")
            return None
        return modelo

    def _pedir_dump_dir(self) -> Optional[str]:
        """Carpeta de dump si el checkbox está activo ('' = canceló el diálogo)."""
        if not self.chk_dump.isChecked():
            return None
        return QFileDialog.getExistingDirectory(self, "Carpeta para volcar tallers") or ""

    def _ejecutar(self) -> None:
        """Lanza un set NUEVO en el CSV destino (pisa un set previo, confirmando)."""
        modelo = self._validar_prerrequisitos()
        if modelo is None:
            return

        if cargar_filas_csv(self._csv_path):
            resp = QMessageBox.question(
                self, "Set existente",
                f"El set {os.path.basename(self._csv_path)} ya tiene corridas.\n"
                "«Ejecutar» empieza un set nuevo y las descarta (usá «Reanudar / "
                "agregar corridas» para conservarlas).\n\n¿Empezar de cero?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if resp != QMessageBox.StandardButton.Yes:
                return

        mc = self._mc_desde_widgets()
        set_montecarlo(self._cfg, mc)
        guardar_config(self._cfg)
        if self._on_cfg_saved:
            self._on_cfg_saved(self._cfg)

        dump_dir = self._pedir_dump_dir()
        if dump_dir == "":
            return

        spec = EspecMonteCarlo.desde_cfg(self._cfg)
        self._lanzar(modelo, spec, resume=False, dump_dir=dump_dir)

    def _reanudar(self) -> None:
        """Completa las corridas pendientes del set actual (o agrega más).

        La spec sale del sidecar del set — NO de los sliders — para que todas
        las corridas del CSV compartan el mismo espacio de muestreo; los widgets
        se re-sincronizan a esa spec para que la GUI muestre lo que corre. Solo
        ``runs`` se toma del spinner (extender el set con más corridas es válido).
        """
        modelo = self._validar_prerrequisitos()
        if modelo is None:
            return
        spec = cargar_spec_sidecar(self._csv_path)
        if spec is None:
            QMessageBox.warning(
                self, "Atención",
                "El set no tiene spec guardada (.spec.json); no se puede reanudar "
                "con garantía de mismos rangos. Ejecutá un set nuevo.")
            return

        hechas = len(cargar_filas_csv(self._csv_path))
        objetivo = max(self.sp_runs.value(), int(spec.runs))
        if objetivo <= hechas:
            QMessageBox.information(
                self, "Set completo",
                f"El set ya tiene {hechas} corridas. Subí «Número de corridas» "
                "por encima de ese valor para agregar más.")
            return

        spec.runs = objetivo
        spec.chunk = max(1, objetivo // 10)
        # La GUI refleja la spec real del set (rangos/fijos del sidecar).
        self._aplicar_mc_a_widgets(
            {"runs": spec.runs, "master_seed": spec.master_seed,
             "chunk": spec.chunk, "fijos": spec.fijos, "rangos": spec.rangos})

        dump_dir = self._pedir_dump_dir()
        if dump_dir == "":
            return
        self._lanzar(modelo, spec, resume=True, dump_dir=dump_dir)

    def _lanzar(self, modelo: Dict[str, Any], spec: EspecMonteCarlo,
                *, resume: bool, dump_dir: Optional[str]) -> None:
        if self._stock_df is None:
            return
        if not resume:
            # Set nuevo desde cero: descarta los resultados de la corrida previa
            # (cards/histogramas/tabla) para no mezclarlos con los nuevos.
            self.results.reset()
        req = MonteCarloRequest(base_cfg=self._cfg, stock_df=self._stock_df,
                                modelo=modelo, spec=spec, csv_path=self._csv_path,
                                dump_dir=dump_dir or None, resume=resume)
        self.set_running(True)
        self._on_run(req)

    def _toggle_run(self) -> None:
        """El botón principal alterna entre ejecutar (parado) y pausar (corriendo)."""
        if self._corriendo:
            self._pausar()
        else:
            self._ejecutar()

    def _pausar(self) -> None:
        if self._on_pause:
            self.btn_run.setEnabled(False)
            self.btn_run.setText("|| Pausando...")
            self.lbl_progress.setText("Pausando (termina la corrida en vuelo)…")
            self._on_pause()

    def _cambiar_destino_set(self) -> None:
        ruta, _ = QFileDialog.getSaveFileName(
            self, "Archivo CSV del set de resultados",
            os.path.basename(self._csv_path), "CSV (*.csv)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if ruta:
            self._csv_path = ruta
            self._refrescar_set_ui()

    def _abrir_set(self) -> None:
        """Abre un set existente: restaura los rangos de input desde su spec y
        muestra los resultados acumulados; queda listo para reanudar/extender."""
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir set de corridas (CSV)",
                                              "", "CSV (*.csv)")
        if not ruta:
            return
        filas = cargar_filas_csv(ruta)
        spec = cargar_spec_sidecar(ruta)
        self._csv_path = ruta
        if spec is not None:
            self._aplicar_mc_a_widgets(
                {"runs": max(int(spec.runs), len(filas)), "master_seed": spec.master_seed,
                 "chunk": spec.chunk, "fijos": spec.fijos, "rangos": spec.rangos})
        else:
            QMessageBox.warning(
                self, "Set sin spec",
                "El CSV no tiene su .spec.json al lado: se muestran los resultados "
                "pero no se puede reanudar (rangos de input desconocidos).")
        if filas:
            self.results.render(filas, f"RESUMEN ESTADÍSTICO · {len(filas)} corridas (set abierto)")
            self.lbl_progress.setText(f"Set abierto: {len(filas)} corridas")
            self.results.set_export_enabled(True)
        self._refrescar_set_ui()

    def _refrescar_set_ui(self) -> None:
        """Actualiza etiqueta del set y habilitación de Reanudar según el disco."""
        nombre = os.path.basename(self._csv_path)
        en_temp = os.path.dirname(self._csv_path) == tempfile.gettempdir()
        self.lbl_set.setText(f"Set: {nombre}{'  (temporal)' if en_temp else ''}")
        self.lbl_set.setToolTip(self._csv_path)
        puede_reanudar = cargar_spec_sidecar(self._csv_path) is not None
        self.btn_resume.setEnabled(puede_reanudar and self.btn_run.isEnabled())

    def set_running(self, running: bool) -> None:
        self._corriendo = running
        self.btn_run.setEnabled(True)
        self.btn_run.setText("|| Pausar Monte Carlo" if running else "▶ Ejecutar Monte Carlo")
        self.btn_run.setToolTip(
            "Corta el barrido de forma limpia: las corridas completadas quedan "
            "en el set (CSV) y se puede reanudar cuando quieras." if running else "")
        self.btn_abrir_set.setEnabled(not running)
        self.btn_set_path.setEnabled(not running)
        self.progress.setVisible(running)
        if running:
            self.btn_resume.setEnabled(False)
            self.progress.setValue(0)
            self.lbl_progress.setText("Simulando...")
        else:
            self._refrescar_set_ui()

    def set_progress(self, hechos: int, total: int) -> None:
        pct = int(hechos / total * 100) if total else 0
        self.progress.setMaximum(100)
        self.progress.setValue(pct)
        self.lbl_progress.setText(f"{hechos}/{total} corridas")

    def mostrar_parciales(self, filas: List[Dict[str, Any]], hechos: int, total: int) -> None:
        """Refresca cards/histogramas/tabla con lo acumulado (cada ~10% del barrido)."""
        self.results.render(filas, f"RESUMEN PARCIAL · {hechos}/{total} corridas")

    def mostrar_resultados(self, filas: List[Dict[str, Any]], pausado: bool = False) -> None:
        self.set_running(False)
        estado = "en el set (pausado)" if pausado else "completadas"
        self.lbl_progress.setText(f"{len(filas)} corridas {estado}")
        titulo = (f"RESUMEN PARCIAL · {len(filas)} corridas (set pausado)" if pausado
                  else f"RESUMEN ESTADÍSTICO · {len(filas)} corridas")
        self.results.render(filas, titulo)
        self.results.set_export_enabled(bool(filas))

    def set_error(self, msg: str) -> None:
        self.set_running(False)
        self.lbl_progress.setText("Error")
        QMessageBox.critical(self, "Error", f"No se pudo ejecutar el Monte Carlo:\n{msg}")

    # ── Export ───────────────────────────────────────────────────────────────

    def _exportar_corridas(self) -> None:
        if not self._csv_path or not os.path.exists(self._csv_path):
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar CSV de corridas",
                                              "montecarlo_corridas.csv", "CSV (*.csv)")
        if ruta:
            import shutil
            shutil.copyfile(self._csv_path, ruta)

    def _exportar_resumen(self) -> None:
        resumen = self.results.resumen()
        if not resumen:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar resumen estadístico",
                                              "montecarlo_resumen.csv", "CSV (*.csv)")
        if ruta:
            exportar_resumen_csv(resumen, ruta)
