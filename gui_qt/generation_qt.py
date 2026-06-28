"""Panel de generacion de cambios para la migracion Qt."""

from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict

import pandas as pd
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QTableWidget,
    QTableWidgetItem,
)

from config import generator_model as model_store
from config.tema import JAULA_COLORS
from config.persistencia import (
    guardar_config,
    obtener_generador_cambios,
    obtener_turnos_cambios,
    set_generador_cambios,
)
from modelos import turnos as turnos_mod
from modelos.generador_cambios import GENERADORES_CAMBIOS, ajustar_modelo, generar_cambios
from gui_qt.widgets import LabeledFieldRow, SectionCard


class GenerationPanel(QWidget):
    """Panel funcional para adaptar modelo y generar Programa_Cambios."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        on_cfg_saved: Callable[[Dict[str, Any]], None] | None = None,
        on_cambios_generated: Callable[[pd.DataFrame], None] | None = None,
        on_go_to_snapshot: Callable[[int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = copy.deepcopy(cfg)
        self._on_cfg_saved = on_cfg_saved
        self._on_cambios_generated = on_cambios_generated
        self._on_go_to_snapshot = on_go_to_snapshot

        self._history_df: pd.DataFrame | None = None
        self._modelo = model_store.load_active_model()
        self._modelos_por_clave: Dict[str, Dict[str, Any]] = model_store.load_models()
        if self._modelo and isinstance(self._modelo, dict):
            clave_ini = self._modelo.get("clave")
            if isinstance(clave_ini, str) and clave_ini:
                self._modelos_por_clave[clave_ini] = self._modelo
        self._generated_df: pd.DataFrame | None = None
        self._sim_snapshots: list[Any] = []

        # === SCROLL AREA: evita que el contenido se solape ===
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("GenScrollContent")
        scroll.setWidget(content)

        root = QVBoxLayout(content)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(14)

        # === HEADER: Action Buttons ===
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)

        header_row.addStretch(1)

        btn_regenerate = QPushButton("↻ Regenerar")
        btn_regenerate.setObjectName("PrimaryAction")
        btn_regenerate.clicked.connect(self.generate_changes)
        header_row.addWidget(btn_regenerate)
        
        btn_upload = QPushButton("⤓ Subir cambios")
        btn_upload.setObjectName("PlaybackButton")
        btn_upload.clicked.connect(self._load_changes_excel)
        header_row.addWidget(btn_upload)
        
        root.addLayout(header_row)
        
        # === PARAMETER CARDS GRID ===
        self.params_frame = QFrame(self)
        self.params_frame.setObjectName("CardTransparent")
        params_grid = QHBoxLayout(self.params_frame)
        params_grid.setContentsMargins(0, 0, 0, 0)
        params_grid.setSpacing(12)
        self._param_cards = {}
        for i in range(6):
            card = QFrame(self)
            card.setObjectName("GenKpiCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(14, 14, 14, 14)
            card_layout.setSpacing(8)
            
            k_label = QLabel("-")
            k_label.setObjectName("GenKpiKey")
            
            v_label = QLabel("-")
            v_label.setObjectName("GenKpiVal")
            
            card_layout.addWidget(k_label)
            card_layout.addWidget(v_label)
            params_grid.addWidget(card)
            self._param_cards[i] = (k_label, v_label)
        
        root.addWidget(self.params_frame)
        
        # === Config + Adapt row ===
        row = QHBoxLayout()
        row.setSpacing(12)
        root.addLayout(row)

        row.addWidget(self._build_config_card(), 1)
        row.addWidget(self._build_adapt_card(), 1)

        bottom = QFrame(self)
        bottom.setObjectName("CardSoft")
        bottom_col = QVBoxLayout(bottom)
        bottom_col.setContentsMargins(14, 14, 14, 14)
        bottom_col.setSpacing(12)

        self.lbl_model = QLabel()
        self.lbl_model.setObjectName("Muted")
        bottom_col.addWidget(self.lbl_model)

        tl_title = QLabel("LÍNEA DE TIEMPO")
        tl_title.setObjectName("CardTitle")
        bottom_col.addWidget(tl_title)

        # Timeline visual (matplotlib simplificado)
        self.fig_timeline = Figure(figsize=(9, 1.4), facecolor="#16191d", constrained_layout=True)
        self.canvas_timeline = FigureCanvas(self.fig_timeline)
        self.canvas_timeline.setMinimumHeight(100)
        bottom_col.addWidget(self.canvas_timeline)
        
        # Tabla de cambios (sin headers)
        self.tbl_changes = QTableWidget(self)
        self.tbl_changes.setObjectName("GenChangesTable")
        self.tbl_changes.setColumnCount(3)
        self.tbl_changes.setHorizontalHeaderLabels(["Fecha/Hora", "Jaula", "mm"])
        # Ocultar headers
        self.tbl_changes.horizontalHeader().setVisible(False)
        self.tbl_changes.setMinimumHeight(200)
        self.tbl_changes.setMaximumHeight(300)
        # Expandir columnas para usar todo el ancho
        header = self.tbl_changes.horizontalHeader()
        header.setStretchLastSection(True)
        for i in range(3):
            header.setSectionResizeMode(i, header.ResizeMode.Stretch)
        bottom_col.addWidget(self.tbl_changes)
        self._parada_marker_indices: list[int] = []

        gen_actions = QHBoxLayout()
        gen_actions.setSpacing(8)
        self.btn_generate = QPushButton("Generar cambios")
        self.btn_generate.setObjectName("PrimaryAction")
        self.btn_generate.clicked.connect(self.generate_changes)
        gen_actions.addWidget(self.btn_generate)
        gen_actions.addStretch(1)

        bottom_col.addLayout(gen_actions)
        root.addWidget(bottom)

        self._load_cfg_controls()
        # Sincroniza modelo activo con el algoritmo seleccionado en Adaptación.
        clave_sel = self.cb_adapt_model.currentData()
        self._modelo = self._modelos_por_clave.get(clave_sel)
        self._refresh_model_summary()
        self._render_timeline(None)
        self._update_param_cards()
        self._update_adapt_preview()

    def _build_config_card(self) -> QFrame:
        card = SectionCard(
            self,
            object_name="CardSoft",
            title="Configuracion",
            margins=(14, 4, 14, 14),
            spacing=6,
        )
        col = card.content_layout()

        form = QFormLayout()
        self.cb_generator = QComboBox()
        for key, gen in GENERADORES_CAMBIOS.items():
            self.cb_generator.addItem(gen.etiqueta, key)

        self.sp_umbral = QDoubleSpinBox()
        self.sp_umbral.setRange(0.0, 100.0)
        self.sp_umbral.setDecimals(2)
        self.sp_umbral.setSingleStep(0.1)

        self.sp_seed = QSpinBox()
        self.sp_seed.setRange(-1, 2_147_483_647)
        self.sp_seed.setValue(-1)
        self.sp_seed.setToolTip("Use -1 para semilla aleatoria en cada generacion")

        # Fechas sin checkboxes - siempre usadas
        self.dt_start = QDateEdit()
        self.dt_start.setCalendarPopup(True)
        self.dt_start.setDisplayFormat("yyyy-MM-dd")
        
        self.dt_end = QDateEdit()
        self.dt_end.setCalendarPopup(True)
        self.dt_end.setDisplayFormat("yyyy-MM-dd")

        form.addRow("Algoritmo", self.cb_generator)
        form.addRow("Umbral desbaste (mm)", self.sp_umbral)
        form.addRow("Semilla", self.sp_seed)
        form.addRow("Fecha inicio", self.dt_start)
        form.addRow("Fecha fin", self.dt_end)

        # Opción de turnos: combo de presets para acceso rápido + botón Editar para personalizar
        self._turnos_custom: dict | None = None  # None = 24/7
        turnos_row = QHBoxLayout()
        turnos_row.setSpacing(6)
        self.cb_turnos_preset = QComboBox()
        for key, label in turnos_mod.PRESET_LABELS.items():
            self.cb_turnos_preset.addItem(label, key)
        self.cb_turnos_preset.addItem("Personalizado…", "__custom__")
        self.cb_turnos_preset.currentIndexChanged.connect(self._on_turnos_preset_changed)
        turnos_row.addWidget(self.cb_turnos_preset, stretch=1)
        btn_edit_turnos = QPushButton("Editar…")
        btn_edit_turnos.setObjectName("PlaybackButton")
        btn_edit_turnos.setFixedWidth(70)
        btn_edit_turnos.clicked.connect(self._open_turnos_editor)
        turnos_row.addWidget(btn_edit_turnos)
        form.addRow("Régimen de turnos", turnos_row)

        col.addLayout(form)

        btn_save = QPushButton("Guardar configuracion")
        btn_save.setObjectName("PlaybackButton")
        btn_save.clicked.connect(self._save_generator_cfg)
        col.addWidget(btn_save)

        return card

    def _build_adapt_card(self) -> QFrame:
        card = SectionCard(
            self,
            object_name="CardSoft",
            title="Adaptacion",
            margins=(14, 8, 14, 14),
            spacing=6,
        )
        col = card.content_layout()

        self.lbl_history = QLabel("Historia: no cargada")
        self.lbl_history.setObjectName("Muted")
        col.addWidget(self.lbl_history)

        # Selector de modelo + botones en la misma fila
        self.cb_adapt_model = QComboBox()
        for key, gen in GENERADORES_CAMBIOS.items():
            self.cb_adapt_model.addItem(gen.etiqueta, key)
        self.cb_adapt_model.currentIndexChanged.connect(self._update_adapt_preview)
        model_row = LabeledFieldRow("Modelo:", self.cb_adapt_model, self, stretch_field=True)
        col.addWidget(model_row)

        # Descripción del modelo seleccionado
        self.lbl_model_desc = QLabel("")
        self.lbl_model_desc.setObjectName("Muted")
        self.lbl_model_desc.setWordWrap(True)
        col.addWidget(self.lbl_model_desc)

        # Panel de preview: tabla de cambios antes → después
        self.tbl_preview = QTableWidget(0, 3)
        self.tbl_preview.setObjectName("GenPreviewTable")
        self.tbl_preview.setHorizontalHeaderLabels(["Parámetro", "Actual", "Nuevo"])
        self.tbl_preview.horizontalHeader().setSectionResizeMode(
            0, self.tbl_preview.horizontalHeader().ResizeMode.Stretch)
        self.tbl_preview.horizontalHeader().setSectionResizeMode(
            1, self.tbl_preview.horizontalHeader().ResizeMode.ResizeToContents)
        self.tbl_preview.horizontalHeader().setSectionResizeMode(
            2, self.tbl_preview.horizontalHeader().ResizeMode.ResizeToContents)
        self.tbl_preview.verticalHeader().setVisible(False)
        self.tbl_preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_preview.setMaximumHeight(120)
        self.tbl_preview.setVisible(False)
        col.addWidget(self.tbl_preview)

        actions = QHBoxLayout()

        btn_load = QPushButton("Cargar historia")
        btn_load.setObjectName("PlaybackButton")
        btn_load.clicked.connect(self._load_history)
        actions.addWidget(btn_load)

        # Botón Ajustar inicialmente deshabilitado
        self.btn_fit = QPushButton("Ajustar modelo")
        self.btn_fit.setObjectName("PrimaryAction")
        self.btn_fit.setEnabled(False)  # Deshabilitado hasta cargar historia
        self.btn_fit.clicked.connect(self._fit_model)
        actions.addWidget(self.btn_fit)

        btn_reset = QPushButton("Reset modelo")
        btn_reset.setObjectName("PlaybackButton")
        btn_reset.clicked.connect(self._reset_model)
        actions.addWidget(btn_reset)

        col.addLayout(actions)
        return card

    def set_cfg(self, cfg: Dict[str, Any]) -> None:
        """Actualiza cfg activa y refresca controles/timeline asociado."""
        self._cfg = copy.deepcopy(cfg)
        self._load_cfg_controls()
        clave_sel = self.cb_adapt_model.currentData()
        self._modelo = self._modelos_por_clave.get(clave_sel)
        self._refresh_model_summary()
        self._update_adapt_preview()
        self._render_timeline(self._generated_df)

    def set_simulation_snapshots(self, snapshots: list[Any] | None) -> None:
        """Recibe snapshots de la simulacion para sombrear tramos de PARADA."""
        self._sim_snapshots = list(snapshots or [])
        self._render_timeline(self._generated_df)

    def _load_cfg_controls(self) -> None:
        """Sincroniza widgets desde la config persistida del generador."""
        gc = obtener_generador_cambios(self._cfg)
        idx = self.cb_generator.findData(gc.get("generador"))
        self.cb_generator.setCurrentIndex(idx if idx >= 0 else 0)
        self.sp_umbral.setValue(float(gc.get("umbral_desbaste_mm", 1.0)))

        today = QDate.currentDate()
        self.dt_start.setDate(today)
        self.dt_end.setDate(today.addDays(7))  # Por defecto +7 días

        # Si existen fechas guardadas, usarlas
        if gc.get("fecha_inicio"):
            d = QDate.fromString(str(gc.get("fecha_inicio")), "yyyy-MM-dd")
            if d.isValid():
                self.dt_start.setDate(d)

        if gc.get("fecha_fin"):
            d = QDate.fromString(str(gc.get("fecha_fin")), "yyyy-MM-dd")
            if d.isValid():
                self.dt_end.setDate(d)
        # Cargar turnos
        from config.persistencia import obtener_turnos_cambios
        self._turnos_custom = obtener_turnos_cambios(self._cfg)
        self._update_turnos_combo()

    def _update_turnos_combo(self) -> None:
        """Sincroniza el combo de presets con el esquema de turnos activo."""
        t = self._turnos_custom
        target_key = "24x7"
        if t is not None:
            for key, preset in turnos_mod.PRESETS.items():
                if preset == t:
                    target_key = key
                    break
            else:
                target_key = "__custom__"
        idx = self.cb_turnos_preset.findData(target_key)
        self.cb_turnos_preset.blockSignals(True)
        self.cb_turnos_preset.setCurrentIndex(max(0, idx))
        self.cb_turnos_preset.blockSignals(False)

    def _on_turnos_preset_changed(self, _idx: int) -> None:
        """Al seleccionar un preset en el combo, lo aplica directamente."""
        key = self.cb_turnos_preset.currentData()
        if key == "__custom__":
            # Abrir editor si elige Personalizado desde el combo
            self._open_turnos_editor()
            return
        self._turnos_custom = turnos_mod.PRESETS.get(key) if key != "24x7" else None

    def _open_turnos_editor(self) -> None:
        """Abre el diálogo de edición de turnos y aplica el resultado."""
        if not hasattr(self, '_turnos_dlg') or self._turnos_dlg is None:
            self._turnos_dlg = TurnosDialog(self._turnos_custom, parent=None)
        else:
            # Re-cargar el estado actual en el diálogo existente
            actual = turnos_mod.normalizar(self._turnos_custom)
            self._turnos_dlg._set_grid(actual)
            self._turnos_dlg._sync_preset_combo(actual)
            self._turnos_dlg._accepted = False
        accepted, result = self._turnos_dlg.exec_modal()
        if accepted:
            self._turnos_custom = result
            self._update_turnos_combo()

    def _save_generator_cfg(self) -> None:
        """Persiste parametros del generador en user_config.json."""
        cfg = copy.deepcopy(self._cfg)
        try:
            set_generador_cambios(
                cfg,
                generador=self.cb_generator.currentData(),
                umbral_desbaste=self.sp_umbral.value(),
                horizonte_dias=7,  # Valor fijo
                fecha_inicio=self.dt_start.date().toString("yyyy-MM-dd"),
                fecha_fin=self.dt_end.date().toString("yyyy-MM-dd"),
            )
            # Guardar régimen de turnos por separado
            from config.persistencia import set_turnos_cambios
            set_turnos_cambios(cfg, self._turnos_custom)
            guardar_config(cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar configuracion: {exc}")
            return

        self._cfg = cfg
        if self._on_cfg_saved is not None:
            self._on_cfg_saved(copy.deepcopy(cfg))
        QMessageBox.information(self, "Generacion", "Configuracion del generador guardada.")

    def _load_history(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar historia",
            str(Path.cwd()),
            "Datos (*.csv *.xlsx *.xlsm)",
        )
        if not selected:
            return

        try:
            if selected.lower().endswith(".csv"):
                self._history_df = pd.read_csv(selected)
            else:
                xl = pd.ExcelFile(selected, engine="openpyxl")
                sheet = "Historia" if "Historia" in xl.sheet_names else xl.sheet_names[0]
                self._history_df = xl.parse(sheet)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo cargar historia: {exc}")
            return

        self.lbl_history.setText(
            f"Historia: {Path(selected).name} ({len(self._history_df)} filas)"
        )
        # Habilitar botón "Ajustar modelo" ahora que hay historia
        self.btn_fit.setEnabled(True)
        # Mostrar preview de cambios
        self._update_adapt_preview()

    def _parametros_modelo(self, modelo: dict | None, clave: str) -> "list[tuple[str, str]]":
        """Extrae una lista de (parámetro, valor) legible de un modelo según su algoritmo.

        Independiente de la configuración: solo lee la estructura interna del
        modelo. Devuelve [] si el modelo es None o de otro algoritmo.
        """
        if not modelo or modelo.get("clave") != clave:
            return []

        filas: list[tuple[str, str]] = []
        # Metadatos comunes a todos los modelos
        filas.append(("Muestras (filas)", str(modelo.get("n_filas", 0))))
        filas.append(("Fecha mín", str(modelo.get("fecha_min") or "—")[:10]))
        filas.append(("Fecha máx", str(modelo.get("fecha_max") or "—")[:10]))

        jaulas = modelo.get("jaulas", {})
        orden = sorted(jaulas, key=lambda x: int(x))

        if clave == "empirico":
            for j in orden:
                mj = jaulas[j]
                filas.append((f"J{j} — dur. muestras", str(len(mj.get("duracion", [])))))
                filas.append((f"J{j} — desb. muestras", str(len(mj.get("desbaste", [])))))
        elif clave == "markov":
            for j in orden:
                mj = jaulas[j]
                n_est = len(mj.get("muestras", {}))
                n_tr = sum(sum(v.values()) for v in mj.get("transiciones", {}).values())
                ini = max(mj.get("inicial", {}).items(),
                          key=lambda kv: kv[1], default=(None, 0))[0]
                filas.append((f"J{j} — estados", str(n_est)))
                filas.append((f"J{j} — transiciones", str(n_tr)))
                filas.append((f"J{j} — estado inicial", str(ini) if ini else "—"))
        else:
            # Modelo desconocido: conteo genérico de campos por jaula
            for j in orden:
                filas.append((f"J{j} — campos", str(len(jaulas[j]))))
        return filas

    def _update_adapt_preview(self) -> None:
        """Muestra los parámetros del modelo seleccionado y, si hay historia, su evolución.

        La card de adaptación es **independiente de la configuración del
        generador**: muestra siempre los parámetros del modelo elegido en el
        combo (columna *Actual*) y, cuando se sube historia, hacia dónde irían
        al ajustar (columna *Nuevo*).
        """
        clave = self.cb_adapt_model.currentData()
        if not clave:
            self.tbl_preview.setVisible(False)
            return

        # Descripción del algoritmo seleccionado
        gen = GENERADORES_CAMBIOS.get(clave)
        self.lbl_model_desc.setText(getattr(gen, "descripcion", "") if gen else "")

        # Al cambiar de algoritmo, mostrar su modelo guardado sin perder el otro.
        self._modelo = self._modelos_por_clave.get(clave)
        self._refresh_model_summary()

        # Parámetros actuales: del modelo guardado solo si es del mismo algoritmo
        params_actual = dict(self._parametros_modelo(self._modelo, clave))
        tiene_actual = bool(params_actual)

        # Parámetros nuevos: solo si hay historia subida (preview del ajuste)
        params_nuevo: dict[str, str] = {}
        if self._history_df is not None and not self._history_df.empty:
            try:
                nuevo_modelo = ajustar_modelo(
                    self._history_df, self._cfg, clave=clave, modelo_previo=None,
                )
                params_nuevo = dict(self._parametros_modelo(nuevo_modelo, clave))
            except Exception as exc:
                self.tbl_preview.setRowCount(1)
                self.tbl_preview.setItem(0, 0, QTableWidgetItem("Error al calcular"))
                self.tbl_preview.setItem(0, 1, QTableWidgetItem("—"))
                from PySide6.QtGui import QColor, QBrush
                err = QTableWidgetItem(str(exc)[:60])
                err.setForeground(QBrush(QColor("#FF6B6B")))
                self.tbl_preview.setItem(0, 2, err)
                self.tbl_preview.setVisible(True)
                return

        if not tiene_actual and not params_nuevo:
            # Ni modelo guardado de este algoritmo ni historia → aviso
            self.tbl_preview.setRowCount(1)
            self.tbl_preview.setItem(0, 0, QTableWidgetItem("Sin modelo entrenado"))
            self.tbl_preview.setItem(0, 1, QTableWidgetItem("—"))
            self.tbl_preview.setItem(0, 2, QTableWidgetItem("Suba historia para ajustar"))
            self.tbl_preview.setVisible(True)
            return

        # Unión de claves de parámetros preservando el orden de aparición
        orden_keys: list[str] = []
        for k in list(params_actual) + list(params_nuevo):
            if k not in orden_keys:
                orden_keys.append(k)

        from PySide6.QtGui import QColor, QBrush
        _green = QBrush(QColor("#35D18A"))

        self.tbl_preview.setRowCount(len(orden_keys))
        for r, k in enumerate(orden_keys):
            antes = params_actual.get(k, "—")
            despues = params_nuevo.get(k, "—") if params_nuevo else ""
            self.tbl_preview.setItem(r, 0, QTableWidgetItem(k))
            item_antes = QTableWidgetItem(antes)
            item_despues = QTableWidgetItem(despues)
            if params_nuevo and antes != despues and despues != "—":
                item_despues.setForeground(_green)
            self.tbl_preview.setItem(r, 1, item_antes)
            self.tbl_preview.setItem(r, 2, item_despues)

        self.tbl_preview.setVisible(True)
        self.tbl_preview.resizeRowsToContents()

    def _fit_model(self) -> None:
        """Ajusta/refina el modelo a partir de la historia cargada."""
        if self._history_df is None or self._history_df.empty:
            QMessageBox.warning(self, "Atencion", "Cargue una historia valida antes de ajustar.")
            return

        try:
            clave_sel = self.cb_adapt_model.currentData()
            if not isinstance(clave_sel, str) or not clave_sel:
                raise ValueError("Debe seleccionar un algoritmo válido.")
            self._modelo = ajustar_modelo(
                self._history_df,
                self._cfg,
                clave=clave_sel,
                modelo_previo=self._modelos_por_clave.get(clave_sel),
            )
            self._modelos_por_clave[clave_sel] = self._modelo
            model_store.save_model_for_key(clave_sel, self._modelo, set_active=True)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo ajustar modelo: {exc}")
            return

        self._refresh_model_summary()
        self._update_adapt_preview()
        QMessageBox.information(self, "Generacion", "Modelo ajustado y guardado.")

    def _reset_model(self) -> None:
        clave_sel = self.cb_adapt_model.currentData()
        if isinstance(clave_sel, str) and clave_sel:
            model_store.reset_models(clave_sel)
            self._modelos_por_clave.pop(clave_sel, None)
        else:
            model_store.reset_models()
            self._modelos_por_clave = {}
        self._modelo = self._modelos_por_clave.get(clave_sel) if isinstance(clave_sel, str) else None
        self._generated_df = None
        self._render_timeline(None)
        self._refresh_model_summary()
        self._update_adapt_preview()

    def _refresh_model_summary(self) -> None:
        if not self._modelo:
            self.lbl_model.setText("Modelo: sin adaptar")
            return

        fecha_min = (self._modelo.get("fecha_min") or "-")[:10]
        fecha_max = (self._modelo.get("fecha_max") or "-")[:10]
        self.lbl_model.setText(
            f"Modelo: {self._modelo.get('clave')} | filas={self._modelo.get('n_filas', 0)} | "
            f"periodo={fecha_min} -> {fecha_max}"
        )

    def generate_changes(self) -> None:
        """Genera Programa_Cambios con semilla y ventana temporal seleccionada."""
        if not self._modelo:
            QMessageBox.warning(self, "Atencion", "Primero ajuste o cargue un modelo.")
            return

        gc = obtener_generador_cambios(self._cfg)
        try:
            inicio = datetime.strptime(self.dt_start.date().toString("yyyy-MM-dd"), "%Y-%m-%d")
            fin = datetime.strptime(self.dt_end.date().toString("yyyy-MM-dd"), "%Y-%m-%d")
            seed = self.sp_seed.value()
            self._generated_df = generar_cambios(
                self._modelo,
                self._cfg,
                seed=None if seed < 0 else int(seed),
                inicio=inicio,
                fin=fin,
                horizonte_dias=7,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudieron generar cambios: {exc}")
            return

        if self._generated_df is None or self._generated_df.empty:
            QMessageBox.warning(self, "Atencion", "No se generaron cambios para la ventana/configuracion actual.")
            return

        self._render_timeline(self._generated_df)
        self._update_param_cards()
        # Notifica al MainWindow para activar "Generación" en verde
        if self._on_cambios_generated is not None:
            self._on_cambios_generated(self._generated_df.copy())

    def _load_changes_excel(self) -> None:
        """Carga Programa_Cambios desde un archivo Excel."""
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Seleccionar Excel con Programa_Cambios",
            str(Path.cwd()),
            "Archivos Excel (*.xlsx *.xlsm)",
        )
        if not selected:
            return

        try:
            self._generated_df = pd.read_excel(selected, sheet_name="Programa_Cambios")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo cargar el Excel:\n{exc}")
            return

        if self._generated_df is None or self._generated_df.empty:
            QMessageBox.warning(self, "Atencion", "El Excel no contiene cambios validos.")
            return

        self._render_timeline(self._generated_df)
        self._update_param_cards()
        # Notifica al MainWindow para activar "Generación" en verde
        if self._on_cambios_generated is not None:
            self._on_cambios_generated(self._generated_df.copy())

    def _update_param_cards(self) -> None:
        """Actualiza los parametros mostrados en las tarjetas (Semilla, Nº cambios, etc)."""
        gc = obtener_generador_cambios(self._cfg)
        if self._generated_df is None or self._generated_df.empty:
            params = [
                ("Semilla", str(self.sp_seed.value()) if self.sp_seed.value() >= 0 else "aleatoria"),
                ("Nº de cambios", "-"),
                ("Horizonte", f"{gc.get('horizonte_dias', 60)} d"),
                ("Distribución", str(gc.get("generador", "empírico"))),
                ("Cambios / día", "-"),
                ("Ventana", "-"),
            ]
        else:
            n_cambios = len(self._generated_df)
            generador_name = str(gc.get("generador", "empírico"))
            horizonte = int(gc.get("horizonte_dias", 60))
            cambios_dia = n_cambios / max(1, horizonte)
            # Ventana real desde el DataFrame generado.
            ventana = "-"
            try:
                fechas = pd.to_datetime(self._generated_df["Fecha_Hora"], errors="coerce").dropna()
                if not fechas.empty:
                    ventana = f"{fechas.min():%d/%m} – {fechas.max():%d/%m}"
            except Exception:
                ventana = "-"

            params = [
                ("Semilla", str(self.sp_seed.value()) if self.sp_seed.value() >= 0 else "aleatoria"),
                ("Nº de cambios", str(n_cambios)),
                ("Horizonte", f"{horizonte} d"),
                ("Distribución", generador_name),
                ("Cambios / día", f"~{cambios_dia:.0f}"),
                ("Ventana", ventana),
            ]
        
        for i, (k, v) in enumerate(params):
            if i < len(self._param_cards):
                k_label, v_label = self._param_cards[i]
                k_label.setText(k)
                v_label.setText(v)

    def _render_timeline(self, cambios_df: pd.DataFrame | None) -> None:
        """Dibuja timeline visual con barras coloreadas por jaula, altura completa."""
        self.fig_timeline.clear()
        ax = self.fig_timeline.add_subplot(111)
        ax.set_facecolor("#16191d")
        
        # Limpia la tabla
        self.tbl_changes.setRowCount(0)
        
        if cambios_df is None or cambios_df.empty:
            ax.text(0.5, 0.5, "Sin cambios", color="#9aa3b2", 
                   ha="center", va="center", transform=ax.transAxes, fontsize=9)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            self.canvas_timeline.draw_idle()
            return

        df = cambios_df.copy()
        df["Fecha_Hora"] = pd.to_datetime(df["Fecha_Hora"], errors="coerce")
        df = df.dropna(subset=["Fecha_Hora"]).sort_values("Fecha_Hora")
        
        if df.empty:
            ax.text(0.5, 0.5, "Fechas invalidas", color="#9aa3b2", 
                   ha="center", va="center", transform=ax.transAxes, fontsize=9)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            self.canvas_timeline.draw_idle()
            return

        # Colores por jaula (cíclico sobre JAULA_COLORS)
        def color_jaula(j: int) -> str:
            return JAULA_COLORS[(int(j) - 1) % len(JAULA_COLORS)]
        
        # Timeline visual: barras verticales por cada cambio
        t_min = df["Fecha_Hora"].min().to_pydatetime()
        t_max = df["Fecha_Hora"].max().to_pydatetime()
        t_range = (t_max - t_min).total_seconds()
        
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(0, 1)
        
        # Fondo sutil con color levemente diferente
        ax.axhspan(0, 1, color="#1a1f26", alpha=0.4, zorder=0, linewidth=0)
        
        # Agrupa cambios por fecha para desplazar múltiples en la misma fecha
        df["fecha_solo"] = df["Fecha_Hora"].dt.date
        cambios_por_fecha = df.groupby("fecha_solo").size()
        
        # Dibuja barras verticales, desplazadas si hay múltiples en la misma fecha
        for fecha_solo, group in df.groupby("fecha_solo"):
            n_cambios_fecha = len(group)
            for idx_dentro, (_, row) in enumerate(group.iterrows()):
                t = row["Fecha_Hora"].to_pydatetime()
                x = (t - t_min).total_seconds() / t_range if t_range > 0 else 0.5
                
                # Desplazamiento lateral si hay múltiples cambios en la misma fecha
                if n_cambios_fecha > 1:
                    offset = (idx_dentro - (n_cambios_fecha - 1) / 2) * 0.003
                    x = x + offset
                
                jaula = int(row["Jaula"]) if pd.notna(row["Jaula"]) else 1
                color = color_jaula(jaula)
                # Barra vertical de altura completa
                ax.plot([x, x], [0, 1], color=color, linewidth=1.6,
                       alpha=0.95, solid_capstyle="round", zorder=2)
        
        # Marcas de ejes de tiempo (ticks con etiquetas de fecha)
        n_ticks = min(6, max(2, len(df)))
        tick_positions = [i / (n_ticks - 1) for i in range(n_ticks)] if n_ticks > 1 else [0.5]
        ax.set_xticks(tick_positions)
        tick_labels = []
        for tp in tick_positions:
            t_tick = t_min + pd.Timedelta(seconds=tp * t_range)
            tick_labels.append(t_tick.strftime("%d/%m %H:%M"))
        ax.set_xticklabels(tick_labels, color="#9aa3b2", fontsize=7)
        ax.tick_params(axis="x", colors="#3a4250", length=4, pad=4)
        ax.set_yticks([])
        # Quita bordes salvo eje inferior
        for name, sp in ax.spines.items():
            sp.set_visible(False)
        
        self.canvas_timeline.draw_idle()
        
        # Llena la tabla con los cambios
        self.tbl_changes.setRowCount(len(df))

        for row_idx, (_, row) in enumerate(df.iterrows()):
            # Fecha/Hora
            fecha_hora = row["Fecha_Hora"].strftime("%d/%m %H:%M") if pd.notna(row["Fecha_Hora"]) else "-"
            item_fecha = QTableWidgetItem(fecha_hora)
            item_fecha.setForeground(Qt.GlobalColor.white)
            self.tbl_changes.setItem(row_idx, 0, item_fecha)
            
            # Jaula
            jaula = str(int(row["Jaula"])) if pd.notna(row["Jaula"]) else "-"
            item_jaula = QTableWidgetItem(f"J{jaula}")
            item_jaula.setForeground(Qt.GlobalColor.white)
            self.tbl_changes.setItem(row_idx, 1, item_jaula)
            
            # mm a rectificar
            try:
                mm_val = f"{float(row.get('mm_a_Rectificar', 0)):.3f}"
            except (ValueError, TypeError):
                mm_val = str(row.get("mm_a_Rectificar", "-"))
            item_mm = QTableWidgetItem(mm_val)
            item_mm.setForeground(Qt.GlobalColor.white)
            self.tbl_changes.setItem(row_idx, 2, item_mm)

    def _parada_markers(self, t0: datetime, t1: datetime) -> list[tuple[datetime, int]]:
        """Retorna marcas (tiempo, idx_snapshot) para cada inicio de PARADA en ventana."""
        out: list[tuple[datetime, int]] = []
        en_parada = False
        for idx, s in enumerate(self._sim_snapshots):
            ts = getattr(s, "tiempo", None)
            if ts is None:
                continue
            f = bool(getattr(s, "jaulas_paradas", []))
            if f and not en_parada and t0 <= ts <= t1:
                out.append((ts, idx))
            en_parada = f
        return out

    def _on_pick_event(self, event) -> None:
        """Resuelve click sobre marcador de PARADA y delega la navegacion."""
        if self._on_go_to_snapshot is None:
            return
        idxs = getattr(event, "ind", None)
        if not idxs or not self._parada_marker_indices:
            return
        pos = int(idxs[0])
        if pos < 0 or pos >= len(self._parada_marker_indices):
            return
        self._on_go_to_snapshot(int(self._parada_marker_indices[pos]))

    def _tramos_sin_turno(self, t0: datetime, t1: datetime) -> list[tuple[datetime, datetime]]:
        """Calcula intervalos fuera de turno del laminador en [t0, t1]."""
        turnos = obtener_turnos_cambios(self._cfg)
        if turnos is None:
            return []

        grilla = turnos_mod.expandir(turnos)
        tramos: list[tuple[datetime, datetime]] = []
        t = t0.replace(minute=0, second=0, microsecond=0)
        ini: datetime | None = None
        while t <= t1:
            operativo = grilla[t.weekday()][t.hour]
            if not operativo and ini is None:
                ini = max(t, t0)
            elif operativo and ini is not None:
                tramos.append((ini, t))
                ini = None
            t += pd.Timedelta(hours=1).to_pytimedelta()

        if ini is not None:
            tramos.append((ini, t1))
        return tramos

    def _tramos_parada(self, t0: datetime, t1: datetime) -> list[tuple[datetime, datetime]]:
        """Calcula intervalos de PARADA detectados en snapshots simulados."""
        if not self._sim_snapshots:
            return []

        tramos: list[tuple[datetime, datetime]] = []
        ini: datetime | None = None
        for s in self._sim_snapshots:
            ts = getattr(s, "tiempo", None)
            if ts is None:
                continue
            en_parada = bool(getattr(s, "jaulas_paradas", []))
            if en_parada and ini is None:
                ini = ts
            elif not en_parada and ini is not None:
                a, b = max(ini, t0), min(ts, t1)
                if a < b:
                    tramos.append((a, b))
                ini = None

        if ini is not None and self._sim_snapshots:
            ts_fin = getattr(self._sim_snapshots[-1], "tiempo", None)
            if ts_fin is not None:
                a, b = max(ini, t0), min(ts_fin, t1)
                if a < b:
                    tramos.append((a, b))

        return tramos


# ─────────────────────────────────────────────────────────────────────────────
# Diálogo editor de turnos (7 días × 3 turnos) — equivalente Qt del CTk popup
# ─────────────────────────────────────────────────────────────────────────────

class TurnosDialog(QWidget):
    """Popup para editar un esquema de turnos 7 días × 3 turnos con presets."""

    def __init__(self, turnos_actual, parent=None):
        from PySide6.QtWidgets import QCheckBox as QCB
        from PySide6.QtCore import Qt as _Qt
        super().__init__(parent, _Qt.WindowType.Dialog | _Qt.WindowType.WindowTitleHint | _Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle("Esquema de turnos")
        self.setWindowModality(_Qt.WindowModality.ApplicationModal)
        self.setAttribute(_Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumWidth(440)
        self._accepted = False
        self._result_turnos = None

        root = QVBoxLayout(self)
        root.setSpacing(8)

        desc = QLabel("Marque los turnos operativos (T3 22–06 cubre la madrugada siguiente).")
        desc.setWordWrap(True)
        desc.setObjectName("Muted")
        root.addWidget(desc)

        # Combo de presets
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.cb_preset = QComboBox()
        for key, label in turnos_mod.PRESET_LABELS.items():
            self.cb_preset.addItem(label, key)
        self.cb_preset.addItem("Personalizado", "__custom__")
        self.cb_preset.currentIndexChanged.connect(self._apply_preset)
        preset_row.addWidget(self.cb_preset)
        preset_row.addStretch()
        root.addLayout(preset_row)

        # Grilla: encabezado
        grid = QWidget()
        grid_layout = QVBoxLayout(grid)
        grid_layout.setSpacing(4)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel(""))  # placeholder columna de días
        for lbl in turnos_mod.TURNO_LABELS:
            h = QLabel(lbl)
            h.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_row.addWidget(h)
        grid_layout.addLayout(header_row)

        # Filas de checkboxes por día
        self._checks: dict[str, list[QCB]] = {}
        for dia, nombre in zip(turnos_mod.DIAS, turnos_mod.DIAS_NOMBRES):
            row = QHBoxLayout()
            lbl = QLabel(nombre)
            lbl.setMinimumWidth(80)
            row.addWidget(lbl)
            checks = []
            for t in range(turnos_mod.NUM_TURNOS):
                cb = QCB()
                cb.stateChanged.connect(self._on_manual_change)
                row.addWidget(cb, alignment=Qt.AlignmentFlag.AlignCenter)
                checks.append(cb)
            self._checks[dia] = checks
            grid_layout.addLayout(row)

        root.addWidget(grid)

        # Cargar valores actuales
        actual = turnos_mod.normalizar(turnos_actual)
        self._set_grid(actual)
        self._sync_preset_combo(actual)

        # Botones OK / Cancelar
        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_ok = QPushButton("Aceptar")
        btn_ok.setObjectName("PrimaryAction")
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setObjectName("PlaybackButton")
        btn_cancel.clicked.connect(self.hide)
        btn_box.addWidget(btn_cancel)
        btn_box.addWidget(btn_ok)
        root.addLayout(btn_box)

    def _set_grid(self, turnos: dict) -> None:
        for dia, checks in self._checks.items():
            vals = turnos.get(dia, [True, True, True])
            for i, cb in enumerate(checks):
                cb.blockSignals(True)
                cb.setChecked(bool(vals[i]))
                cb.blockSignals(False)

    def _apply_preset(self, _idx: int) -> None:
        key = self.cb_preset.currentData()
        if key == "__custom__":
            return
        preset = turnos_mod.normalizar(turnos_mod.PRESETS.get(key))
        self._set_grid(preset)

    def _on_manual_change(self) -> None:
        """Al editar manualmente, cambia combo a 'Personalizado'."""
        idx = self.cb_preset.findData("__custom__")
        if idx >= 0:
            self.cb_preset.blockSignals(True)
            self.cb_preset.setCurrentIndex(idx)
            self.cb_preset.blockSignals(False)

    def _sync_preset_combo(self, turnos: dict) -> None:
        """Selecciona en el combo el preset que corresponde al turnos dado (o Personalizado)."""
        for key, preset in turnos_mod.PRESETS.items():
            if preset == turnos:
                idx = self.cb_preset.findData(key)
                if idx >= 0:
                    self.cb_preset.blockSignals(True)
                    self.cb_preset.setCurrentIndex(idx)
                    self.cb_preset.blockSignals(False)
                return
        # No coincide con ningún preset → Personalizado
        idx = self.cb_preset.findData("__custom__")
        if idx >= 0:
            self.cb_preset.blockSignals(True)
            self.cb_preset.setCurrentIndex(idx)
            self.cb_preset.blockSignals(False)

    def _accept(self) -> None:
        result = {dia: [cb.isChecked() for cb in checks]
                  for dia, checks in self._checks.items()}
        # Si equivale a 24/7 → None (motor interpreta None como siempre operativo)
        self._result_turnos = None if turnos_mod.normalizar(result) == turnos_mod.PRESETS["24x7"] else result
        self._accepted = True
        self.hide()

    def exec_modal(self) -> tuple[bool, dict | None]:
        """Muestra el diálogo modalmente y retorna (aceptado, turnos)."""
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        self.show()
        # Esperar hasta que se oculte (aceptar/cancelar llaman hide())
        # Conectamos al hide via closeEvent no disponible, usamos windowHidden via timer
        def _check():
            if not self.isVisible():
                loop.quit()
        from PySide6.QtCore import QTimer
        timer = QTimer()
        timer.setInterval(50)
        timer.timeout.connect(_check)
        timer.start()
        loop.exec()
        timer.stop()
        return self._accepted, self._result_turnos

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def get_result(self) -> tuple[bool, dict | None]:
        """Retorna (aceptado, turnos_dict_o_None)."""
        return self._accepted, self._result_turnos
