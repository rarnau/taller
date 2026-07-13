"""Pestaña Inventario para la GUI Qt.

Vista dual del stock (inicial editable / resultado simulado de solo lectura)
con ordenamiento por columna, filtros y CRUD sobre el stock inicial. El panel
calcula y presenta; la mutación del ``stock_df`` la hace el contenedor
(``MainWindow``) vía callbacks, igual que la carga (``set_load_callback``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import tema as tk_theme
from config.persistencia import obtener_config_global
from gui_qt.inventory_logic import COLUMNAS_VISTA, filtrar_registros, ordenar_registros
from gui_qt.widgets.cilindro_dialog import CilindroDialog
from modelos.enums import EstadoCilindro
from nucleo import stock as stock_mod


_HEADERS = ["ID", "DIAMETRO", "ORIGINAL", "DESGASTE", "ESTADO", "JAULA"]

_FILTRO_TODOS = "Todos"
_FILTRO_TODAS = "Todas"
_FILTRO_SIN_JAULA = "Sin jaula"


def _state_colors() -> Dict[str, QColor]:
    """Mapa de estado->color de fila, alineado con el tema global."""
    palette = tk_theme.COLORES_ESTADO_DASH
    return {
        "Trabajando": QColor(palette["Trabajando"]).darker(320),
        "CRC": QColor(palette["CRC"]).darker(320),
        "Disponible": QColor(palette["Disponible"]).darker(320),
        "Enfriando": QColor(palette["Enfriando"]).darker(320),
        "A rectificar": QColor(palette["A rectificar"]).darker(320),
        "Rectificando": QColor(palette["Rectificando"]).darker(320),
        "Baja": QColor("#262C35"),
    }


class InventoryPanel(QWidget):
    """Tabla de inventario estilo dark con filas coloreadas por estado."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._registros: List[Dict[str, Any]] = []
        self._registros_visibles: List[Dict[str, Any]] = []
        self._taller = None
        self._taller_id: Optional[int] = None
        self._stock_df: Optional[pd.DataFrame] = None
        self._modo = "inicial"  # "inicial" | "final"
        self._sort: tuple[str, bool] = ("diametro", True)  # (columna vista, descendente)
        self._stale = False
        self._load_callback = None
        self._save_callback = None
        self._stock_edited_cb = None
        self._cfg_provider = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        # ── Fila 1: título + acciones de archivo ────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        root.addLayout(toolbar)

        self.title = QLabel("Inventario de cilindros")
        self.title.setObjectName("SectionTitle")
        toolbar.addWidget(self.title)

        self.count = QLabel("0 registros")
        self.count.setObjectName("InventoryMeta")
        toolbar.addWidget(self.count)
        toolbar.addStretch(1)

        self.btn_load = QPushButton("↓ Cargar stock (Excel)")
        self.btn_load.setObjectName("InventoryToolbarButton")
        self.btn_load.clicked.connect(self._load_stock)
        toolbar.addWidget(self.btn_load)

        self.btn_save = QPushButton("Guardar stock…")
        self.btn_save.setObjectName("InventoryToolbarButton")
        self.btn_save.clicked.connect(self._save_stock)
        toolbar.addWidget(self.btn_save)

        self.btn_export = QPushButton("Exportar vista…")
        self.btn_export.setObjectName("InventoryToolbarButton")
        self.btn_export.clicked.connect(self._export)
        toolbar.addWidget(self.btn_export)

        # ── Fila 2: toggle de vista + CRUD ──────────────────────────────
        viewbar = QHBoxLayout()
        viewbar.setContentsMargins(0, 0, 0, 0)
        viewbar.setSpacing(8)
        root.addLayout(viewbar)

        self.btn_view_inicial = QPushButton("Stock inicial")
        self.btn_view_final = QPushButton("Resultado simulado")
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for btn in (self.btn_view_inicial, self.btn_view_final):
            btn.setObjectName("InventoryViewToggle")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._view_group.addButton(btn)
            viewbar.addWidget(btn)
        self.btn_view_inicial.setChecked(True)
        self.btn_view_final.setEnabled(False)
        self.btn_view_inicial.clicked.connect(lambda: self._set_modo("inicial"))
        self.btn_view_final.clicked.connect(lambda: self._set_modo("final"))

        self.stale_label = QLabel(
            "Resultado desactualizado — el stock inicial fue editado después de simular"
        )
        self.stale_label.setObjectName("InventoryStale")
        self.stale_label.setVisible(False)
        viewbar.addWidget(self.stale_label)
        viewbar.addStretch(1)

        self.btn_add = QPushButton("+ Agregar")
        self.btn_add.setObjectName("PrimaryAction")
        self.btn_edit = QPushButton("Editar")
        self.btn_edit.setObjectName("InventoryToolbarButton")
        self.btn_delete = QPushButton("Eliminar")
        self.btn_delete.setObjectName("InventoryDeleteButton")
        for btn, handler in (
            (self.btn_add, self._on_add),
            (self.btn_edit, self._on_edit),
            (self.btn_delete, self._on_delete),
        ):
            btn.clicked.connect(handler)
            viewbar.addWidget(btn)

        # ── Fila 3: filtros ─────────────────────────────────────────────
        filterbar = QHBoxLayout()
        filterbar.setContentsMargins(0, 0, 0, 0)
        filterbar.setSpacing(8)
        root.addLayout(filterbar)

        def _filter_label(texto: str) -> QLabel:
            lbl = QLabel(texto)
            lbl.setObjectName("InventoryFilterLabel")
            return lbl

        self.ed_filter_id = QLineEdit()
        self.ed_filter_id.setObjectName("InventoryFilterInput")
        self.ed_filter_id.setPlaceholderText("Buscar ID…")
        self.ed_filter_id.setClearButtonEnabled(True)
        self.ed_filter_id.setFixedWidth(170)
        filterbar.addWidget(self.ed_filter_id)

        filterbar.addWidget(_filter_label("Estado"))
        self.cb_filter_estado = QComboBox()
        self.cb_filter_estado.setObjectName("InventoryFilterCombo")
        self.cb_filter_estado.addItem(_FILTRO_TODOS)
        for e in EstadoCilindro:
            self.cb_filter_estado.addItem(e.value)
        self.cb_filter_estado.setMinimumWidth(120)
        filterbar.addWidget(self.cb_filter_estado)

        filterbar.addWidget(_filter_label("Jaula"))
        self.cb_filter_jaula = QComboBox()
        self.cb_filter_jaula.setObjectName("InventoryFilterCombo")
        self.cb_filter_jaula.setMinimumWidth(105)
        self._poblar_filtro_jaulas()
        filterbar.addWidget(self.cb_filter_jaula)

        self.sp_filter_dmin = QDoubleSpinBox()
        self.sp_filter_dmax = QDoubleSpinBox()
        for etiqueta, sp in (("Ø mín", self.sp_filter_dmin), ("Ø máx", self.sp_filter_dmax)):
            sp.setObjectName("InventoryFilterSpin")
            sp.setDecimals(1)
            sp.setRange(0.0, 9999.0)
            sp.setValue(0.0)
            sp.setSpecialValueText("—")  # 0 = sin límite
            # Sin flechitas: valor tipeado, look pill como el resto de filtros.
            sp.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
            sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sp.setFixedWidth(72)
            filterbar.addWidget(_filter_label(etiqueta))
            filterbar.addWidget(sp)

        self.btn_filter_clear = QPushButton("Limpiar")
        self.btn_filter_clear.setObjectName("InventoryToolbarButton")
        self.btn_filter_clear.clicked.connect(self._clear_filters)
        filterbar.addWidget(self.btn_filter_clear)
        filterbar.addStretch(1)

        # Debounce compartido: cada repaint reconstruye cell widgets.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(200)
        self._filter_timer.timeout.connect(self._refresh_view)
        self.ed_filter_id.textChanged.connect(self._filter_timer.start)
        self.cb_filter_estado.currentIndexChanged.connect(self._filter_timer.start)
        self.cb_filter_jaula.currentIndexChanged.connect(self._filter_timer.start)
        self.sp_filter_dmin.valueChanged.connect(self._filter_timer.start)
        self.sp_filter_dmax.valueChanged.connect(self._filter_timer.start)

        # ── Tabla ───────────────────────────────────────────────────────
        card = QFrame()
        card.setObjectName("InventoryShell")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card_col = QVBoxLayout(card)
        card_col.setContentsMargins(0, 0, 0, 0)
        card_col.setSpacing(0)

        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setObjectName("InventoryTable")
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.viewport().setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.itemSelectionChanged.connect(self._update_action_states)
        self.table.doubleClicked.connect(lambda _ix: self._on_edit())
        card_col.addWidget(self.table, 1)
        root.addWidget(card, 1)

        # Sort por click en header. NO usar setSortingEnabled: reordenaría los
        # items pero no los cell widgets (guía ID / badge de estado) — el orden
        # se aplica en Python sobre los registros y se repinta completo.
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._on_header_clicked)

        self._apply_table_style()
        self._sync_sort_indicator()
        self._update_action_states()

    # ── Callbacks del contenedor ─────────────────────────────────────────

    def set_load_callback(self, cb) -> None:
        """Registra la accion de carga usada por el toolbar del inventario."""
        self._load_callback = cb

    def set_save_callback(self, cb) -> None:
        """Registra la acción "Guardar stock…" (la ejecuta MainWindow)."""
        self._save_callback = cb

    def set_stock_edited_callback(self, cb) -> None:
        """Registra el receptor del stock_df nuevo tras cada operación CRUD."""
        self._stock_edited_cb = cb

    def set_cfg_provider(self, provider) -> None:
        """Registra un callable que devuelve la config vigente (user_cfg)."""
        self._cfg_provider = provider

    def set_stale(self, stale: bool) -> None:
        """Marca la vista Final como desactualizada tras editar el stock."""
        self._stale = bool(stale)
        self.stale_label.setVisible(self._stale and self._modo == "final")

    # ── Refresh / vista ──────────────────────────────────────────────────

    def refresh(self, taller=None, stock_df: pd.DataFrame | None = None) -> None:
        """Reconstruye y pinta la tabla desde stock inicial o resultado final."""
        taller_nuevo = taller is not None and id(taller) != self._taller_id
        self._taller = taller
        self._taller_id = id(taller) if taller is not None else None
        self._stock_df = stock_df

        tiene_final = taller is not None and bool(getattr(taller, "cilindros", None))
        self.btn_view_final.setEnabled(tiene_final)
        # Auto-switch solo cuando cambia la identidad del taller; el resto
        # respeta la elección del usuario.
        if taller_nuevo and tiene_final:
            self._modo = "final"
        elif not tiene_final:
            self._modo = "inicial"
        self._sync_toggle_buttons()
        self._poblar_filtro_jaulas()
        self._refresh_view()

    def _set_modo(self, modo: str) -> None:
        if modo == "final" and not self.btn_view_final.isEnabled():
            modo = "inicial"
        if modo != self._modo:
            self._modo = modo
            self.table.clearSelection()
            self._refresh_view()
        self._sync_toggle_buttons()

    def _sync_toggle_buttons(self) -> None:
        self.btn_view_inicial.setChecked(self._modo == "inicial")
        self.btn_view_final.setChecked(self._modo == "final")
        self.stale_label.setVisible(self._stale and self._modo == "final")

    def _refresh_view(self) -> None:
        self._registros = self._build_records()
        visibles = filtrar_registros(self._registros, **self._filtros_activos())
        columna, descendente = self._sort
        self._registros_visibles = ordenar_registros(visibles, columna, descendente)
        self._paint_rows(self._registros_visibles)
        total, vis = len(self._registros), len(self._registros_visibles)
        texto = f"{vis} de {total} registros" if vis != total else f"{total} registros"
        bajas = sum(1 for r in self._registros
                    if r["estado"] == EstadoCilindro.BAJA.value)
        if bajas:
            texto += f" / {bajas} baja"
        self.count.setText(texto)
        self._update_action_states()

    def _build_records(self) -> List[Dict[str, Any]]:
        """Normaliza el origen del modo activo a registros tipados de la vista."""
        if self._modo == "final" and self._taller is not None:
            registros = []
            for c in self._taller.cilindros.values():
                d0 = float(getattr(c, "diametro_original", c.diametro))
                d1 = float(c.diametro)
                registros.append(
                    {
                        "id": str(c.id),
                        "diametro": d1,
                        "original": d0,
                        "desgaste": d1 - d0,
                        "estado": c.estado.value if hasattr(c, "estado") else "-",
                        "jaula": c.jaula,
                    }
                )
            return registros

        df = self._stock_df
        if df is None or df.empty:
            return []
        registros = []
        for _, record in df.iterrows():
            diametro = float(record.get(stock_mod.COL_DIAMETRO, 0.0))
            jaula = record.get(stock_mod.COL_JAULA)
            registros.append(
                {
                    "id": str(record.get(stock_mod.COL_ID, "")),
                    "diametro": diametro,
                    "original": diametro,
                    "desgaste": 0.0,
                    "estado": str(record.get(stock_mod.COL_ESTADO, "-") or "-"),
                    "jaula": None if pd.isna(jaula) else int(jaula),
                }
            )
        return registros

    # ── Filtros ──────────────────────────────────────────────────────────

    def _filtros_activos(self) -> Dict[str, Any]:
        estado = self.cb_filter_estado.currentText()
        jaula_data = self.cb_filter_jaula.currentData()
        return {
            "texto_id": self.ed_filter_id.text(),
            "estado": None if estado == _FILTRO_TODOS else estado,
            "jaula": jaula_data,
            "diametro_min": self.sp_filter_dmin.value(),
            "diametro_max": self.sp_filter_dmax.value(),
        }

    def _poblar_filtro_jaulas(self) -> None:
        """Rellena el combo Jaula con la unión de la config vigente y los datos."""
        jaulas = set()
        if callable(self._cfg_provider):
            try:
                cg = obtener_config_global(self._cfg_provider())
                jaulas.update(range(1, int(cg["cantidad_jaulas"]) + 1))
            except Exception:
                pass
        jaulas.update(r["jaula"] for r in self._registros if r.get("jaula") is not None)

        seleccion = self.cb_filter_jaula.currentData() if self.cb_filter_jaula.count() else None
        self.cb_filter_jaula.blockSignals(True)
        self.cb_filter_jaula.clear()
        self.cb_filter_jaula.addItem(_FILTRO_TODAS, None)
        self.cb_filter_jaula.addItem(_FILTRO_SIN_JAULA, "sin")
        for j in sorted(jaulas):
            self.cb_filter_jaula.addItem(f"Jaula {j}", j)
        idx = self.cb_filter_jaula.findData(seleccion)
        self.cb_filter_jaula.setCurrentIndex(idx if idx >= 0 else 0)
        self.cb_filter_jaula.blockSignals(False)

    def _clear_filters(self) -> None:
        for w in (self.ed_filter_id, self.cb_filter_estado, self.cb_filter_jaula,
                  self.sp_filter_dmin, self.sp_filter_dmax):
            w.blockSignals(True)
        self.ed_filter_id.clear()
        self.cb_filter_estado.setCurrentIndex(0)
        self.cb_filter_jaula.setCurrentIndex(0)
        self.sp_filter_dmin.setValue(0.0)
        self.sp_filter_dmax.setValue(0.0)
        for w in (self.ed_filter_id, self.cb_filter_estado, self.cb_filter_jaula,
                  self.sp_filter_dmin, self.sp_filter_dmax):
            w.blockSignals(False)
        self._refresh_view()

    # ── Sort ─────────────────────────────────────────────────────────────

    def _on_header_clicked(self, seccion: int) -> None:
        columna = COLUMNAS_VISTA[seccion]
        actual, descendente = self._sort
        self._sort = (columna, not descendente if columna == actual else False)
        self._sync_sort_indicator()
        self._refresh_view()

    def _sync_sort_indicator(self) -> None:
        columna, descendente = self._sort
        orden = Qt.SortOrder.DescendingOrder if descendente else Qt.SortOrder.AscendingOrder
        self.table.horizontalHeader().setSortIndicator(COLUMNAS_VISTA.index(columna), orden)

    # ── CRUD ─────────────────────────────────────────────────────────────

    def _cfg(self) -> Optional[Dict[str, Any]]:
        return self._cfg_provider() if callable(self._cfg_provider) else None

    def _ids_stock(self) -> set:
        if self._stock_df is None or self._stock_df.empty:
            return set()
        return set(self._stock_df[stock_mod.COL_ID].astype(str))

    def _selected_id(self) -> Optional[str]:
        fila = self.table.currentRow()
        seleccion = self.table.selectionModel()
        if fila < 0 or seleccion is None or not seleccion.hasSelection():
            return None
        if fila >= len(self._registros_visibles):
            return None
        return self._registros_visibles[fila]["id"]

    def _puede_editar(self) -> bool:
        return self._modo == "inicial" and self._stock_df is not None

    def _update_action_states(self) -> None:
        editable = self._puede_editar()
        con_stock = self._stock_df is not None and not self._stock_df.empty
        hay_seleccion = self._selected_id() is not None
        # Alta habilitada en vista Inicial aun sin stock cargado (stock desde cero).
        self.btn_add.setEnabled(self._modo == "inicial")
        self.btn_edit.setEnabled(editable and hay_seleccion)
        self.btn_delete.setEnabled(editable and hay_seleccion)
        self.btn_save.setEnabled(self._modo == "inicial" and con_stock)

    def _emitir_stock(self, nuevo_df: pd.DataFrame) -> None:
        if callable(self._stock_edited_cb):
            self._stock_edited_cb(nuevo_df)

    def _on_add(self) -> None:
        cfg = self._cfg()
        if cfg is None or self._modo != "inicial":
            return
        aceptado, fila = CilindroDialog.create(cfg, self._ids_stock(), parent=self)
        if not aceptado or fila is None:
            return
        self._emitir_stock(stock_mod.agregar_fila_stock(self._stock_df, fila))

    def _on_edit(self) -> None:
        cfg = self._cfg()
        id_cil = self._selected_id()
        if cfg is None or id_cil is None or not self._puede_editar():
            return
        df = self._stock_df
        mask = df[stock_mod.COL_ID].astype(str) == id_cil
        if not mask.any():
            return
        fila_actual = df.loc[mask].iloc[0].to_dict()
        aceptado, fila = CilindroDialog.edit(cfg, fila_actual, self._ids_stock(), parent=self)
        if not aceptado or fila is None:
            return
        self._emitir_stock(stock_mod.actualizar_fila_stock(df, id_cil, fila))

    def _on_delete(self) -> None:
        id_cil = self._selected_id()
        if id_cil is None or not self._puede_editar():
            return
        resp = QMessageBox.question(
            self,
            "Eliminar cilindro",
            f"¿Eliminar el cilindro {id_cil} del stock inicial?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return
        self._emitir_stock(stock_mod.eliminar_fila_stock(self._stock_df, id_cil))

    # ── Pintado ──────────────────────────────────────────────────────────

    def _paint_rows(self, registros: List[Dict[str, Any]]) -> None:
        """Pinta filas completas aplicando color de estado por inventario."""
        self.table.setRowCount(len(registros))
        colors = _state_colors()

        for r, reg in enumerate(registros):
            estado = reg["estado"]
            fila_txt = [
                reg["id"],
                f"{reg['diametro']:.1f}",
                f"{reg['original']:.1f}",
                f"{reg['desgaste']:.1f}",
                estado,
                "-" if reg["jaula"] is None else str(reg["jaula"]),
            ]
            bg = colors.get(estado, QColor(tk_theme.BG2))
            for c, txt in enumerate(fila_txt):
                it = QTableWidgetItem("") if c in (0, 4) else QTableWidgetItem(txt)
                it.setTextAlignment(
                    Qt.AlignmentFlag.AlignVCenter
                    | (Qt.AlignmentFlag.AlignLeft if c == 0 else Qt.AlignmentFlag.AlignCenter)
                )
                if c == 3:
                    it.setForeground(QColor("#F0A32E"))
                else:
                    it.setForeground(QColor("#F0F4F8" if c == 0 else tk_theme.FG))
                it.setBackground(bg)
                if c in (0, 5):
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                self.table.setItem(r, c, it)
                if c == 0:
                    self.table.setCellWidget(r, c, self._build_id_cell(fila_txt[0], estado, bg))
                if c == 4:
                    self.table.setCellWidget(r, c, self._build_state_badge(estado, bg))

        self.table.resizeRowsToContents()

    def _build_id_cell(self, value: str, estado: str, bg: QColor) -> QWidget:
        """Compone la celda ID con una guia lateral del color del estado."""
        container = QWidget()
        container.setAutoFillBackground(True)
        palette = container.palette()
        palette.setColor(QPalette.ColorRole.Window, bg)
        container.setPalette(palette)
        container.setStyleSheet("background: transparent; border: none;")
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(5)

        accent = QFrame(container)
        accent.setObjectName("InventoryAccent")
        accent.setProperty("state", estado)
        accent.setFixedWidth(2)
        row.addWidget(accent)

        label = QLabel(value, container)
        label.setObjectName("InventoryIdLabel")
        row.addWidget(label)
        row.addStretch(1)
        return container

    def _build_state_badge(self, estado: str, bg: QColor) -> QWidget:
        """Crea una pastilla visual para el estado de la fila, centrada verticalmente."""
        badge = QLabel(estado)
        badge.setObjectName("InventoryStateBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setProperty("state", estado)
        badge.style().unpolish(badge)
        badge.style().polish(badge)
        badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        badge.setFixedHeight(24)

        # Envolver en contenedor con layout para centrar verticalmente en la celda
        container = QWidget()
        container.setObjectName("InventoryBadgeCell")
        container.setStyleSheet("QWidget#InventoryBadgeCell { background: transparent; border: none; }")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()
        layout.addWidget(badge, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        return container

    # ── Estilos ──────────────────────────────────────────────────────────

    def _apply_table_style(self) -> None:
        """Aplica estilo oscuro fijo del inventario para la migracion Qt."""
        self.table.setStyleSheet(
            f"""
            QTableWidget#InventoryTable {{
                background-color: {tk_theme.BG_CARD};
                border: none;
                border-radius: 0px;
                gridline-color: transparent;
            }}
            QTableWidget#InventoryTable::item:selected {{
                background-color: #2A3F5C;
                color: #FFFFFF;
            }}
            QHeaderView::section {{
                background-color: #141B26;
                color: #6F7B89;
                font-weight: 700;
                border: none;
                border-bottom: 1px solid #242F3A;
                padding: 6px 12px;
            }}
            """
        )

        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setStretchLastSection(False)
        for index in range(len(_HEADERS)):
            header.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setMinimumSectionSize(80)
        self.table.verticalHeader().setDefaultSectionSize(32)
        self.table.setColumnWidth(0, 118)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 72)

    # ── Acciones de archivo ──────────────────────────────────────────────

    def _load_stock(self) -> None:
        """Dispara la carga del stock desde el callback del contenedor."""
        if callable(self._load_callback):
            self._load_callback()

    def _save_stock(self) -> None:
        """Dispara "Guardar stock…" en el contenedor (dueño del stock_df)."""
        if callable(self._save_callback):
            self._save_callback()

    def _export(self) -> None:
        """Exporta la vista actual (filtrada/ordenada) del inventario a Excel."""
        if not self._registros_visibles:
            QMessageBox.information(self, "Inventario", "No hay datos para exportar.")
            return
        fp, _ = QFileDialog.getSaveFileName(
            self,
            "Guardar inventario",
            str(Path.cwd() / "inventario.xlsx"),
            "Excel (*.xlsx)",
        )
        if not fp:
            return
        filas = [
            [
                reg["id"],
                f"{reg['diametro']:.1f}",
                f"{reg['original']:.1f}",
                f"{reg['desgaste']:.1f}",
                reg["estado"],
                "-" if reg["jaula"] is None else str(reg["jaula"]),
            ]
            for reg in self._registros_visibles
        ]
        df = pd.DataFrame(filas, columns=_HEADERS)
        df.to_excel(fp, index=False)
        QMessageBox.information(self, "Inventario", f"Inventario exportado en:\n{fp}")
