"""Pestaña Inventario para la GUI Qt."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import tema as tk_theme
from modelos.enums import EstadoCilindro


_HEADERS = ["ID", "DIAMETRO", "ORIGINAL", "DESGASTE", "ESTADO", "JAULA"]


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
        self._rows: List[List[str]] = []
        self._load_callback = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

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

        self.btn_export = QPushButton("Descargar resultado")
        self.btn_export.setObjectName("InventoryToolbarButton")
        self.btn_export.clicked.connect(self._export)
        toolbar.addWidget(self.btn_export)

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
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.viewport().setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        card_col.addWidget(self.table, 1)
        root.addWidget(card, 1)

        self._apply_table_style()

    def set_load_callback(self, cb) -> None:
        """Registra la accion de carga usada por el toolbar del inventario."""
        self._load_callback = cb

    def refresh(self, taller=None, stock_df: pd.DataFrame | None = None) -> None:
        """Reconstruye y pinta la tabla desde stock inicial o resultado final."""
        self._rows = self._build_rows(taller=taller, stock_df=stock_df)
        self._paint_rows(self._rows)
        self.count.setText(f"{len(self._rows)} registros")

    def _build_rows(self, taller=None, stock_df: pd.DataFrame | None = None) -> List[List[str]]:
        """Normaliza el origen activo a filas compatibles con la tabla."""
        if taller is not None and getattr(taller, "cilindros", None):
            rows = []
            for c in sorted(taller.cilindros.values(), key=lambda x: x.diametro, reverse=True):
                d0 = float(getattr(c, "diametro_original", c.diametro))
                d1 = float(c.diametro)
                desgaste = d1 - d0
                estado = c.estado.value if hasattr(c, "estado") else "-"
                jaula = str(c.jaula) if c.jaula is not None else "-"
                rows.append(
                    [
                        str(c.id),
                        f"{d1:.1f}",
                        f"{d0:.1f}",
                        f"{desgaste:.1f}",
                        estado,
                        jaula,
                    ]
                )
            return rows

        if stock_df is None or stock_df.empty:
            return []

        rows = []
        df = stock_df.sort_values("Diámetro_mm", ascending=False)
        for _, record in df.iterrows():
            diametro = float(record.get("Diámetro_mm", 0.0))
            estado = str(record.get("Estado", "-") or "-")
            jaula = record.get("Jaula_Asignada")
            rows.append(
                [
                    str(record.get("ID_Cilindro", "")),
                    f"{diametro:.1f}",
                    f"{diametro:.1f}",
                    "0.0",
                    estado,
                    "-" if pd.isna(jaula) else str(int(jaula)),
                ]
            )
        return rows

    def _paint_rows(self, rows: List[List[str]]) -> None:
        """Pinta filas completas aplicando color de estado por inventario."""
        self.table.setRowCount(len(rows))
        colors = _state_colors()

        for r, row in enumerate(rows):
            estado = row[4]
            bg = colors.get(estado, QColor(tk_theme.BG2))
            for c, txt in enumerate(row):
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
                    self.table.setCellWidget(r, c, self._build_id_cell(row[0], estado, bg))
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

    def _load_stock(self) -> None:
        """Dispara la carga del stock desde el callback del contenedor."""
        if callable(self._load_callback):
            self._load_callback()

    def _export(self) -> None:
        """Exporta la vista actual del inventario a Excel."""
        if not self._rows:
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
        df = pd.DataFrame(self._rows, columns=_HEADERS)
        df.to_excel(fp, index=False)
        QMessageBox.information(self, "Inventario", f"Inventario exportado en:\n{fp}")
