"""Panel de configuracion (Qt) para parametros estructurales del taller."""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from config.persistencia import (
    guardar_config,
    obtener_config_global,
    obtener_estrategia_asignacion,
    obtener_estrategia_seleccion,
    obtener_max_iteraciones,
    obtener_maquinas,
    obtener_rangos,
    obtener_tasa_falla,
    obtener_tiempo_enfriado,
    problemas_coherencia,
    set_config_global,
    set_rango,
    set_sim,
)
from modelos import turnos as turnos_mod
from modelos.estrategias import ESTRATEGIAS_ASIGNACION, ESTRATEGIAS_SELECCION
from gui_qt.widgets import StyledTableWidget, make_config_cell_input, make_priority_combo


class TurnosDialog(QDialog):
    """Editor simple 7x3 de turnos (dias x T1/T2/T3) para una maquina."""

    def __init__(self, turnos: Dict[str, list[bool]] | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar turnos de maquina")
        self.resize(560, 360)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        hint = QLabel("Marque turnos operativos por dia. T3 corresponde 22-06 del dia de inicio.")
        hint.setObjectName("Muted")
        root.addWidget(hint)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(10)
        self.grid.setVerticalSpacing(6)
        root.addLayout(self.grid)

        self._checks: Dict[str, list[QCheckBox]] = {}

        self.grid.addWidget(QLabel("Dia"), 0, 0)
        for col, tlabel in enumerate(turnos_mod.TURNO_LABELS, start=1):
            self.grid.addWidget(QLabel(tlabel), 0, col)

        for row, (dia_key, dia_name) in enumerate(zip(turnos_mod.DIAS, turnos_mod.DIAS_NOMBRES), start=1):
            self.grid.addWidget(QLabel(dia_name), row, 0)
            cks: list[QCheckBox] = []
            for col in range(1, len(turnos_mod.TURNO_LABELS) + 1):
                ck = QCheckBox()
                self.grid.addWidget(ck, row, col, alignment=Qt.AlignmentFlag.AlignCenter)
                cks.append(ck)
            self._checks[dia_key] = cks

        presets_row = QHBoxLayout()
        presets_row.addWidget(QLabel("Preset"))
        self.cb_preset = QComboBox()
        for key in ("24x7", "lv3", "3escuadras", "off"):
            self.cb_preset.addItem(turnos_mod.PRESET_LABELS[key], key)
        presets_row.addWidget(self.cb_preset)

        btn_apply_preset = QPushButton("Aplicar")
        btn_apply_preset.setObjectName("PlaybackButton")
        btn_apply_preset.clicked.connect(self._apply_selected_preset)
        presets_row.addWidget(btn_apply_preset)
        presets_row.addStretch(1)
        root.addLayout(presets_row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._load_turnos(turnos)

    def _apply_selected_preset(self) -> None:
        key = self.cb_preset.currentData()
        if isinstance(key, str) and key in turnos_mod.PRESETS:
            self._load_turnos(turnos_mod.PRESETS[key])

    def _load_turnos(self, turnos: Dict[str, list[bool]] | None) -> None:
        norm = turnos_mod.normalizar(turnos)
        for dia in turnos_mod.DIAS:
            vals = norm.get(dia, [False, False, False])
            for i, ck in enumerate(self._checks[dia]):
                ck.setChecked(bool(vals[i]))

    def collect_turnos(self) -> Dict[str, list[bool]]:
        """Recolecta el estado actual de la grilla de checks."""
        out: Dict[str, list[bool]] = {}
        for dia in turnos_mod.DIAS:
            out[dia] = [ck.isChecked() for ck in self._checks[dia]]
        return out

    @staticmethod
    def edit(turnos: Dict[str, list[bool]] | None, parent: QWidget | None = None) -> tuple[bool, Dict[str, list[bool]] | None]:
        """Abre el dialogo y retorna (aceptado, turnos)."""
        dlg = TurnosDialog(turnos, parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False, None
        return True, dlg.collect_turnos()


class ConfigPanel(QWidget):
    """Editor de configuracion persistente para la migracion Qt."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        on_saved: Callable[[Dict[str, Any]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_saved = on_saved
        self._cfg = copy.deepcopy(cfg)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)

        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)

        hint = QLabel("La configuracion se guarda en user_config.json y se aplica en la siguiente simulacion.")
        hint.setObjectName("Muted")
        body.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        body.addLayout(grid)

        self.card_global = self._build_global_group()
        self.card_ranges = self._build_ranges_group()
        self.card_machines = self._build_machines_group()
        self.card_runtime = self._build_runtime_group()

        grid.addWidget(self.card_global, 0, 0)
        grid.addWidget(self.card_ranges, 0, 1)
        grid.addWidget(self.card_machines, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addWidget(self.card_runtime)

        self.lbl_coherence = QLabel("● Configuracion en edicion")
        self.lbl_coherence.setObjectName("Muted")
        actions.addWidget(self.lbl_coherence)
        actions.addStretch(1)

        self.btn_reload = QPushButton("Recargar")
        self.btn_reload.setObjectName("PlaybackButton")
        self.btn_reload.setMinimumWidth(92)
        self.btn_reload.setMinimumHeight(38)
        self.btn_reload.clicked.connect(self.reload_from_cfg)
        actions.addWidget(self.btn_reload)

        self.btn_save = QPushButton("Guardar configuracion")
        self.btn_save.setObjectName("PrimaryAction")
        self.btn_save.clicked.connect(self.save_cfg)
        actions.addWidget(self.btn_save)

        body.addLayout(actions)

        self._wire_live_status_signals()
        self.reload_from_cfg()

    def _build_global_group(self) -> QFrame:
        """Construye bloque de parametros globales del taller."""
        card = QFrame(self)
        card.setObjectName("CardSoft")
        col = QVBoxLayout(card)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(10)

        title = QLabel("Parámetros globales del taller")
        title.setObjectName("CardTitle")
        col.addWidget(title)

        note = QLabel("Rango de diámetro útil, traslado CRC, jaulas, enfriado y estrategias.")
        note.setObjectName("Muted")
        col.addWidget(note)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.sp_diam_max = self._make_float(min_v=0.0, max_v=9999.0, decimals=1, step=0.1)
        self.sp_diam_min = self._make_float(min_v=0.0, max_v=9999.0, decimals=1, step=0.1)
        self.sp_crc_min = self._make_float(min_v=0.0, max_v=9999.0, decimals=1, step=0.1)
        self.sp_jaulas = QSpinBox()
        self.sp_jaulas.setRange(1, 32)
        self.sp_jaulas.valueChanged.connect(self._sync_range_rows)

        self.sp_cooling = self._make_float(min_v=0.0, max_v=240.0, decimals=1, step=0.1)

        self.cb_strategy_select = QComboBox()
        for key, strat in ESTRATEGIAS_SELECCION.items():
            self.cb_strategy_select.addItem(strat.etiqueta, key)
        self.cb_strategy_select.setMinimumWidth(220)

        self.cb_strategy_assign = QComboBox()
        for key, strat in ESTRATEGIAS_ASIGNACION.items():
            self.cb_strategy_assign.addItem(strat.etiqueta, key)
        self.cb_strategy_assign.setMinimumWidth(220)

        form.addRow("Diametro maximo (mm)", self.sp_diam_max)
        form.addRow("Diametro minimo (mm)", self.sp_diam_min)
        form.addRow("Traslado CRC por pareja (min)", self.sp_crc_min)
        form.addRow("Cantidad de jaulas", self.sp_jaulas)
        form.addRow("Tiempo enfriado (h)", self.sp_cooling)
        form.addRow("Estrategia de seleccion", self.cb_strategy_select)
        form.addRow("Estrategia de asignacion", self.cb_strategy_assign)

        col.addLayout(form)
        return card

    def _build_runtime_group(self) -> QFrame:
        """Construye bloque compacto de parametros de corrida."""
        card = QFrame(self)
        card.setObjectName("CardSoft")
        col = QVBoxLayout(card)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(6)

        title = QLabel("Parámetros de corrida")
        title.setObjectName("CardTitle")
        col.addWidget(title)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        lbl = QLabel("Max iteraciones")
        lbl.setObjectName("Muted")
        row.addWidget(lbl)

        self.sp_iter = QSpinBox()
        self.sp_iter.setRange(1, 5_000_000)
        self.sp_iter.setMinimumWidth(130)
        row.addWidget(self.sp_iter)
        row.addStretch(1)

        col.addLayout(row)
        return card

    def _build_ranges_group(self) -> QFrame:
        """Construye editor tabular de rangos de SubStock por jaula."""
        card = QFrame(self)
        card.setObjectName("CardSoft")
        col = QVBoxLayout(card)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(10)

        lbl = QLabel("Rangos de SubStock por jaula")
        lbl.setObjectName("CardTitle")
        col.addWidget(lbl)

        note = QLabel("Convención: hasta < diámetro <= desde. Perfil vacío = sin restricción.")
        note.setObjectName("Muted")
        col.addWidget(note)

        self.tbl_ranges = StyledTableWidget(0, 4, self)
        self.tbl_ranges.setObjectName("ConfigTable")
        self.tbl_ranges.setHorizontalHeaderLabels(["Jaula", "Desde", "Hasta", "Perfil"])
        self.tbl_ranges.apply_base_defaults()
        self.tbl_ranges.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.tbl_ranges.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        self.tbl_ranges.horizontalHeader().setStretchLastSection(True)
        self.tbl_ranges.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.tbl_ranges.setMinimumHeight(220)
        col.addWidget(self.tbl_ranges)

        return card

    def _build_machines_group(self) -> QFrame:
        """Construye editor tabular del parque de maquinas y turnos."""
        card = QFrame(self)
        card.setObjectName("CardSoft")
        col = QVBoxLayout(card)
        col.setContentsMargins(16, 14, 16, 14)
        col.setSpacing(10)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        lbl = QLabel("Máquinas rectificadoras")
        lbl.setObjectName("CardTitle")
        top.addWidget(lbl)
        top.addStretch(1)

        self.btn_add_machine = QPushButton("+ Agregar maquina")
        self.btn_add_machine.setObjectName("PlaybackButton")
        self.btn_add_machine.clicked.connect(self._add_machine_row)
        top.addWidget(self.btn_add_machine)
        col.addLayout(top)

        note = QLabel(
            "Tasas por tipo (mm y minutos), prioridad y esquema de turnos por máquina."
        )
        note.setObjectName("Muted")
        col.addWidget(note)

        self.tbl_machines = StyledTableWidget(0, 9, self)
        self.tbl_machines.setObjectName("ConfigTable")
        self.tbl_machines.setHorizontalHeaderLabels(
            [
                "Nombre",
                "Prod mm",
                "Prod min",
                "Desb mm",
                "Desb min",
                "Prioridad",
                "Turnos",
                "Falla %",
                "",
            ]
        )
        self.tbl_machines.apply_base_defaults()
        self.tbl_machines.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft)
        self.tbl_machines.setMinimumHeight(140)
        self.tbl_machines.setWordWrap(False)
        self.tbl_machines.setTextElideMode(Qt.TextElideMode.ElideRight)
        vheader = self.tbl_machines.verticalHeader()
        vheader.setDefaultSectionSize(46)
        vheader.setMinimumSectionSize(34)
        hdr = self.tbl_machines.horizontalHeader()
        hdr.setSectionResizeMode(0, hdr.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, hdr.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, hdr.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, hdr.ResizeMode.Fixed)
        hdr.setSectionResizeMode(4, hdr.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, hdr.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, hdr.ResizeMode.Fixed)
        hdr.setSectionResizeMode(7, hdr.ResizeMode.Fixed)
        hdr.setSectionResizeMode(8, hdr.ResizeMode.Fixed)
        self.tbl_machines.setColumnWidth(1, 110)
        self.tbl_machines.setColumnWidth(2, 110)
        self.tbl_machines.setColumnWidth(3, 110)
        self.tbl_machines.setColumnWidth(4, 110)
        self.tbl_machines.setColumnWidth(5, 170)
        self.tbl_machines.setColumnWidth(6, 160)
        self.tbl_machines.setColumnWidth(7, 90)
        self.tbl_machines.setColumnWidth(8, 34)
        col.addWidget(self.tbl_machines)

        return card

    def _make_float(self, min_v: float, max_v: float, decimals: int, step: float) -> QDoubleSpinBox:
        sp = QDoubleSpinBox(self)
        sp.setRange(min_v, max_v)
        sp.setDecimals(decimals)
        sp.setSingleStep(step)
        return sp

    def reload_from_cfg(self) -> None:
        """Recarga controles desde la configuracion actual en memoria."""
        cg = obtener_config_global(self._cfg)
        self.sp_diam_max.setValue(float(cg.get("diametro_maximo", 575.0)))
        self.sp_diam_min.setValue(float(cg.get("diametro_minimo", 520.0)))
        self.sp_crc_min.setValue(float(cg.get("tiempo_traslado_crc_min", 10.0)))
        self.sp_jaulas.setValue(int(cg.get("cantidad_jaulas", 4)))

        self.sp_cooling.setValue(obtener_tiempo_enfriado(self._cfg))
        self.sp_iter.setValue(obtener_max_iteraciones(self._cfg))

        self._set_combo_by_data(
            self.cb_strategy_select,
            obtener_estrategia_seleccion(self._cfg),
        )
        self._set_combo_by_data(
            self.cb_strategy_assign,
            obtener_estrategia_asignacion(self._cfg),
        )

        self._populate_ranges_table()
        self._populate_machines_table()
        self._refresh_coherence_status()

    def set_cfg(self, cfg: Dict[str, Any]) -> None:
        """Actualiza referencia local y refresca controles."""
        self._cfg = copy.deepcopy(cfg)
        self.reload_from_cfg()

    def save_cfg(self) -> None:
        """Valida y persiste la configuracion."""
        try:
            new_cfg = self._build_cfg_from_ui()
            guardar_config(new_cfg)
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"No se pudo guardar la configuracion:\n{exc}")
            return

        self._cfg = new_cfg
        self._refresh_coherence_status()
        QMessageBox.information(self, "Configuracion", "Configuracion guardada correctamente.")
        if self._on_saved is not None:
            self._on_saved(copy.deepcopy(self._cfg))

    def _build_cfg_from_ui(self) -> Dict[str, Any]:
        """Arma una cfg candidata desde controles y valida coherencia."""
        new_cfg = copy.deepcopy(self._cfg)

        set_config_global(
            new_cfg,
            diametro_maximo=self.sp_diam_max.value(),
            diametro_minimo=self.sp_diam_min.value(),
            tiempo_traslado_crc_min=self.sp_crc_min.value(),
            cantidad_jaulas=self.sp_jaulas.value(),
        )
        set_sim(
            new_cfg,
            tiempo_enfriado=self.sp_cooling.value(),
            max_iteraciones=self.sp_iter.value(),
            estrategia_seleccion=self.cb_strategy_select.currentData(),
            estrategia_asignacion=self.cb_strategy_assign.currentData(),
        )

        new_cfg["maquinas"] = []
        for row in range(self.tbl_machines.rowCount()):
            nombre = self._cell_text(self.tbl_machines, row, 0)
            if not nombre:
                raise ValueError(f"Fila maquina {row + 1}: 'Nombre' no puede estar vacio.")

            prod_mm = self._parse_float_machine(row, 1, "Prod mm")
            prod_min = self._parse_float_machine(row, 2, "Prod min")
            desb_mm = self._parse_float_machine(row, 3, "Desb mm")
            desb_min = self._parse_float_machine(row, 4, "Desb min")
            prioridad = self._machine_priority_value(row)
            if prioridad not in {"produccion", "desbaste"}:
                raise ValueError(
                    f"Fila maquina {row + 1}: 'Prioridad' debe ser produccion o desbaste."
                )

            maq = {
                "nombre": nombre,
                "prioridad": prioridad,
                "tasas": {
                    "produccion": {"mm": prod_mm, "tiempo_min": prod_min},
                    "desbaste": {"mm": desb_mm, "tiempo_min": desb_min},
                },
            }
            turnos = self._machine_turnos_value(row)
            if turnos is not None and not turnos_mod.es_completo(turnos):
                maq["turnos"] = turnos
            tasa_pct = self._parse_float_machine(row, 7, "Falla %")
            if not (0.0 <= tasa_pct <= 100.0):
                raise ValueError(
                    f"Fila maquina {row + 1}: 'Falla %' debe estar entre 0 y 100."
                )
            if tasa_pct > 0:
                maq["tasa_falla"] = round(tasa_pct / 100.0, 4)
            new_cfg["maquinas"].append(maq)

        new_cfg["rangos"] = []
        for row in range(self.tbl_ranges.rowCount()):
            jaula = int(self.tbl_ranges.item(row, 0).text())
            desde = self._parse_float_cell(row, 1, "Desde")
            hasta = self._parse_float_cell(row, 2, "Hasta")
            perfil_txt = self.tbl_ranges.item(row, 3).text().strip()
            set_rango(
                new_cfg,
                jaula,
                desde,
                hasta,
                perfil=perfil_txt,
            )

        probs = problemas_coherencia(new_cfg)
        if probs:
            raise ValueError(" ".join(probs))
        return new_cfg

    def _wire_live_status_signals(self) -> None:
        """Conecta señales de edición para refrescar estado de coherencia."""
        self.sp_diam_max.valueChanged.connect(self._refresh_coherence_status)
        self.sp_diam_min.valueChanged.connect(self._refresh_coherence_status)
        self.sp_crc_min.valueChanged.connect(self._refresh_coherence_status)
        self.sp_jaulas.valueChanged.connect(self._refresh_coherence_status)
        self.sp_cooling.valueChanged.connect(self._refresh_coherence_status)
        self.sp_iter.valueChanged.connect(self._refresh_coherence_status)
        self.cb_strategy_select.currentIndexChanged.connect(self._refresh_coherence_status)
        self.cb_strategy_assign.currentIndexChanged.connect(self._refresh_coherence_status)
        self.tbl_ranges.itemChanged.connect(self._refresh_coherence_status)
        self.tbl_machines.itemChanged.connect(self._refresh_coherence_status)

    def _refresh_coherence_status(self) -> None:
        """Actualiza badge de estado según validez actual del formulario."""
        try:
            self._build_cfg_from_ui()
        except Exception as exc:
            self.lbl_coherence.setObjectName("CoherenceStatus")
            self.lbl_coherence.setProperty("state", "error")
            self.lbl_coherence.setText(f"● Configuracion con pendientes: {exc}")
            self.lbl_coherence.style().unpolish(self.lbl_coherence)
            self.lbl_coherence.style().polish(self.lbl_coherence)
            return

        self.lbl_coherence.setObjectName("CoherenceStatus")
        self.lbl_coherence.setProperty("state", "ok")
        self.lbl_coherence.setText("● Configuracion coherente")
        self.lbl_coherence.style().unpolish(self.lbl_coherence)
        self.lbl_coherence.style().polish(self.lbl_coherence)

    def _populate_ranges_table(self) -> None:
        """Carga filas de rangos segun cfg y cantidad actual de jaulas."""
        rangos = {int(r["jaula"]): r for r in obtener_rangos(self._cfg)}
        cantidad = self.sp_jaulas.value()

        self.tbl_ranges.blockSignals(True)
        self.tbl_ranges.setRowCount(cantidad)
        for i in range(cantidad):
            jaula = i + 1
            row_data = rangos.get(jaula, {})

            it_jaula = QTableWidgetItem(str(jaula))
            it_jaula.setFlags(it_jaula.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_ranges.setItem(i, 0, it_jaula)

            self.tbl_ranges.setItem(i, 1, QTableWidgetItem(str(row_data.get("desde", ""))))
            self.tbl_ranges.setItem(i, 2, QTableWidgetItem(str(row_data.get("hasta", ""))))
            self.tbl_ranges.setItem(i, 3, QTableWidgetItem(str(row_data.get("perfil", ""))))
        self.tbl_ranges.blockSignals(False)

    def _populate_machines_table(self) -> None:
        """Carga filas de maquinas con editores de prioridad/turnos por fila."""
        maquinas = obtener_maquinas(self._cfg)
        self.tbl_machines.blockSignals(True)
        self.tbl_machines.setRowCount(len(maquinas))
        for i, m in enumerate(maquinas):
            tasas = m.get("tasas", {})
            prod = tasas.get("produccion", {})
            desb = tasas.get("desbaste", {})
            self._set_machine_text_editor(i, 0, str(m.get("nombre", "")))
            self._set_machine_text_editor(i, 1, str(prod.get("mm", "")), align_center=True)
            self._set_machine_text_editor(i, 2, str(prod.get("tiempo_min", "")), align_center=True)
            self._set_machine_text_editor(i, 3, str(desb.get("mm", "")), align_center=True)
            self._set_machine_text_editor(i, 4, str(desb.get("tiempo_min", "")), align_center=True)
            self._set_machine_priority_editor(i, str(m.get("prioridad", "produccion")))
            self._set_machine_turnos_editor(i, m.get("turnos"))
            tasa_pct = obtener_tasa_falla(self._cfg, str(m.get("nombre", ""))) * 100.0
            self._set_machine_text_editor(i, 7, f"{tasa_pct:.1f}", align_center=True)
            self._set_machine_remove_button(i)
        self.tbl_machines.blockSignals(False)
        self._adjust_machines_table_height()

    def _add_machine_row(self) -> None:
        row = self.tbl_machines.rowCount()
        self.tbl_machines.insertRow(row)
        self._set_machine_text_editor(row, 0, f"M{row + 1}")
        self._set_machine_text_editor(row, 1, "0.8", align_center=True)
        self._set_machine_text_editor(row, 2, "60", align_center=True)
        self._set_machine_text_editor(row, 3, "5.0", align_center=True)
        self._set_machine_text_editor(row, 4, "480", align_center=True)
        self._set_machine_priority_editor(row, "produccion")
        self._set_machine_turnos_editor(row, None)
        self._set_machine_text_editor(row, 7, "0", align_center=True)
        self._set_machine_remove_button(row)
        self._adjust_machines_table_height()

    def _remove_machine_row(self) -> None:
        row = self.tbl_machines.currentRow()
        if row < 0:
            row = self.tbl_machines.rowCount() - 1
        if row >= 0:
            self.tbl_machines.removeRow(row)
            self._adjust_machines_table_height()

    def _sync_range_rows(self) -> None:
        """Sincroniza filas de rangos con cantidad de jaulas preservando valores."""
        prev = {}
        for row in range(self.tbl_ranges.rowCount()):
            if self.tbl_ranges.item(row, 0) is None:
                continue
            jaula = int(self.tbl_ranges.item(row, 0).text())
            prev[jaula] = {
                "desde": self.tbl_ranges.item(row, 1).text() if self.tbl_ranges.item(row, 1) else "",
                "hasta": self.tbl_ranges.item(row, 2).text() if self.tbl_ranges.item(row, 2) else "",
                "perfil": self.tbl_ranges.item(row, 3).text() if self.tbl_ranges.item(row, 3) else "",
            }

        cantidad = self.sp_jaulas.value()
        self.tbl_ranges.setRowCount(cantidad)
        for i in range(cantidad):
            jaula = i + 1
            data = prev.get(jaula, {"desde": "", "hasta": "", "perfil": ""})
            it_jaula = QTableWidgetItem(str(jaula))
            it_jaula.setFlags(it_jaula.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.tbl_ranges.setItem(i, 0, it_jaula)
            self.tbl_ranges.setItem(i, 1, QTableWidgetItem(data["desde"]))
            self.tbl_ranges.setItem(i, 2, QTableWidgetItem(data["hasta"]))
            self.tbl_ranges.setItem(i, 3, QTableWidgetItem(data["perfil"]))

    def _parse_float_cell(self, row: int, col: int, title: str) -> float:
        item = self.tbl_ranges.item(row, col)
        raw = item.text().strip() if item is not None else ""
        if not raw:
            raise ValueError(f"Fila {row + 1}: '{title}' no puede estar vacio.")
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"Fila {row + 1}: '{title}' invalido ('{raw}').") from exc

    def _parse_float_machine(self, row: int, col: int, title: str) -> float:
        raw = self._cell_text(self.tbl_machines, row, col)
        if not raw:
            raise ValueError(f"Fila maquina {row + 1}: '{title}' no puede estar vacio.")
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(
                f"Fila maquina {row + 1}: '{title}' invalido ('{raw}')."
            ) from exc

    def _cell_text(self, table: QTableWidget, row: int, col: int) -> str:
        w = table.cellWidget(row, col)
        if isinstance(w, QLineEdit):
            return w.text().strip()
        item = table.item(row, col)
        return item.text().strip() if item is not None else ""

    def _set_machine_text_editor(self, row: int, col: int, value: str, align_center: bool = False) -> None:
        editor = make_config_cell_input(self.tbl_machines, value, align_center=align_center)
        self.tbl_machines.setCellWidget(row, col, editor)

    def _set_machine_priority_editor(self, row: int, value: str) -> None:
        combo = make_priority_combo(self.tbl_machines, value)
        self.tbl_machines.setCellWidget(row, 5, combo)

    def _machine_priority_value(self, row: int) -> str:
        widget = self.tbl_machines.cellWidget(row, 5)
        if isinstance(widget, QComboBox):
            return str(widget.currentData() or "").strip().lower()
        return self._cell_text(self.tbl_machines, row, 5).lower()

    def _set_machine_turnos_editor(self, row: int, turnos: dict | None) -> None:
        """Configura combo de turnos con presets y fallback a personalizado."""
        host = QWidget(self.tbl_machines)
        lay = QHBoxLayout(host)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(8)

        combo = QComboBox(host)
        combo.setObjectName("ConfigCellCombo")
        combo.setMinimumWidth(112)
        combo.setMaximumHeight(30)
        for key in ("24x7", "lv3", "3escuadras", "off"):
            combo.addItem(turnos_mod.PRESET_LABELS[key], key)

        preset = self._preset_for_turnos(turnos)
        if preset is not None:
            idx = combo.findData(preset)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
        else:
            resumen = turnos_mod.resumen(turnos_mod.normalizar(turnos))
            combo.addItem(resumen, {"custom": copy.deepcopy(turnos)})
            combo.setCurrentIndex(combo.count() - 1)

        btn_edit = QPushButton("⚙")
        btn_edit.setObjectName("ConfigTurnosButton")
        btn_edit.setFixedSize(22, 22)
        btn_edit.clicked.connect(self._edit_machine_turnos_from_sender)

        lay.addWidget(combo, 1)
        lay.addWidget(btn_edit)

        self.tbl_machines.setCellWidget(row, 6, host)

    def _set_machine_remove_button(self, row: int) -> None:
        btn = QPushButton("✕")
        btn.setObjectName("ConfigDeleteButton")
        btn.setFixedSize(24, 24)
        btn.clicked.connect(self._remove_machine_from_sender)
        self.tbl_machines.setCellWidget(row, 8, btn)

    def _set_machine_turnos_button(self, row: int) -> None:
        """Inserta boton para editar turnos custom de la fila."""
        host = QWidget(self.tbl_machines)
        lay = QHBoxLayout(host)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)

        btn = QPushButton("Editar")
        btn.setObjectName("ConfigInlineButton")
        btn.setMinimumWidth(82)
        btn.setMaximumHeight(28)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.clicked.connect(self._edit_machine_turnos_from_sender)

        lay.addWidget(btn)
        # Col 6 = columna de turnos (coincide con el finder de _edit_machine_turnos_from_sender,
        # que busca el sender en la col 6); antes apuntaba a la 7 y pisaba el botón de borrar.
        self.tbl_machines.setCellWidget(row, 6, host)

    def _edit_machine_turnos_from_sender(self) -> None:
        """Resuelve la fila del boton presionado y abre editor custom."""
        sender = self.sender()
        if sender is None:
            return
        row = self._find_widget_row(sender, 6)
        if row < 0:
            return
        self._edit_machine_turnos(row)

    def _remove_machine_from_sender(self) -> None:
        sender = self.sender()
        if sender is None:
            return
        row = self._find_widget_row(sender, 8)
        if row < 0:
            return
        self.tbl_machines.removeRow(row)
        self._adjust_machines_table_height()

    def _edit_machine_turnos(self, row: int) -> None:
        """Abre dialogo 7x3 y persiste en el combo como turno custom."""
        base = self._machine_turnos_value(row)
        ok, turnos = TurnosDialog.edit(base, self)
        if not ok or turnos is None:
            return
        self._set_machine_turnos_editor(row, turnos)
        self._set_machine_turnos_button(row)

    def _machine_turnos_value(self, row: int) -> dict | None:
        """Convierte el valor de combo a dict de turnos persistible o None (24/7)."""
        widget = self.tbl_machines.cellWidget(row, 6)
        if widget is None:
            return None

        combo = widget.findChild(QComboBox)
        if not isinstance(combo, QComboBox):
            return None

        data = combo.currentData()
        if isinstance(data, dict) and "custom" in data:
            return data["custom"]
        if isinstance(data, str):
            if data == "24x7":
                return None
            return copy.deepcopy(turnos_mod.PRESETS[data])
        return None

    def _preset_for_turnos(self, turnos: dict | None) -> str | None:
        """Mapea un dict de turnos al preset equivalente, si existe."""
        if turnos is None or turnos_mod.es_completo(turnos):
            return "24x7"
        for key, preset in turnos_mod.PRESETS.items():
            if turnos_mod.normalizar(preset) == turnos_mod.normalizar(turnos):
                return key
        return None

    def _set_combo_by_data(self, combo: QComboBox, value: str) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _find_widget_row(self, widget: QWidget, col: int) -> int:
        """Busca fila de una celda por identidad del widget incrustado."""
        for row in range(self.tbl_machines.rowCount()):
            cell = self.tbl_machines.cellWidget(row, col)
            if cell is widget:
                return row
            if cell is not None and cell.findChild(QWidget) is widget:
                return row
            if cell is not None and widget.parentWidget() is cell:
                return row
        return -1

    def _adjust_machines_table_height(self) -> None:
        """Ajusta altura de la tabla para evitar solapados y bloque vacío grande."""
        rows = self.tbl_machines.rowCount()
        row_h = self.tbl_machines.verticalHeader().defaultSectionSize()
        head_h = self.tbl_machines.horizontalHeader().height()
        visible_rows = max(3, min(rows, 6))
        height = head_h + (visible_rows * row_h) + 8
        self.tbl_machines.setFixedHeight(height)
