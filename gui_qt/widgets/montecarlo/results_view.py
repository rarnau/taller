"""Panel derecho de resultados Monte Carlo: cards, histogramas y tabla resumen."""

from __future__ import annotations

from typing import Any, Dict, List

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor  # noqa: F401  (import estable para paridad de estilo)
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from config import tema
from nucleo.montecarlo import resumir
from gui_qt.widgets.section_card_qt import SectionCard
from gui_qt.widgets.montecarlo.formatting import KPI_DESTACADOS, fmt_mc_kpi
from gui_qt.widgets.montecarlo.histogram import HistogramWidget


class ResultsView(QWidget):
    """Cards de KPIs (P50 + P10/P90), histogramas y tabla resumen con export.

    Aísla toda la presentación de resultados: recibe filas (crudas por corrida)
    y las resume/pinta. Emite señales para los dos exports; el ``_resumen`` que
    calcula queda accesible vía ``resumen()`` (lo usa el export de resumen).
    """

    exportCorridas = Signal()
    exportResumen = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._resumen: Dict[str, Dict[str, float]] = {}
        self._hist: Dict[str, HistogramWidget] = {}
        self._kpi_cards: Dict[str, QLabel] = {}
        self._kpi_sub: Dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        cont = QWidget()
        col = QVBoxLayout(cont)
        col.setContentsMargins(2, 2, 2, 2)
        col.setSpacing(12)

        # Cards de KPIs (P50 grande + P10/P90).
        cards = QGridLayout()
        cards.setSpacing(12)
        ncols_cards = 3
        for i, (clave, etiqueta, color) in enumerate(KPI_DESTACADOS):
            card = SectionCard(title=etiqueta, object_name="CardSoft")
            card.setMinimumWidth(160)
            lbl = QLabel("—")
            lbl.setStyleSheet(f"font-size:26px; font-weight:700; color:{color};")
            sub = QLabel("")
            sub.setStyleSheet(f"font-size:11px; color:{tema.DASH_LEGEND_TEXT};")
            card.content_layout().addWidget(lbl)
            card.content_layout().addWidget(sub)
            self._kpi_cards[clave] = lbl
            self._kpi_sub[clave] = sub
            cards.addWidget(card, i // ncols_cards, i % ncols_cards)
        col.addLayout(cards)

        # Histogramas 2 columnas.
        hist = QGridLayout()
        hist.setSpacing(10)
        for i, (clave, etiqueta, color) in enumerate(KPI_DESTACADOS):
            card = SectionCard(title=f"Distribución · {etiqueta}", object_name="CardSoft")
            hw = HistogramWidget(color)
            card.content_layout().addWidget(hw)
            self._hist[clave] = hw
            hist.addWidget(card, i // 2, i % 2)
        col.addLayout(hist)

        # Tabla resumen.
        card_t = SectionCard(title="RESUMEN ESTADÍSTICO", object_name="CardSoft")
        self.lbl_tabla = card_t.title_label
        self.tabla = QTableWidget(0, 6)
        self.tabla.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.tabla.setHorizontalHeaderLabels(["Variable", "Media", "Desv.", "P10", "P50", "P90"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabla.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tabla.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        card_t.content_layout().addWidget(self.tabla)
        btns = QHBoxLayout()
        self.btn_csv = QPushButton("⤓ Exportar CSV de corridas")
        self.btn_csv.clicked.connect(self.exportCorridas.emit)
        self.btn_resumen = QPushButton("⤓ Exportar resumen")
        self.btn_resumen.clicked.connect(self.exportResumen.emit)
        btns.addWidget(self.btn_csv)
        btns.addWidget(self.btn_resumen)
        btns.addStretch(1)
        card_t.content_layout().addLayout(btns)
        self.set_export_enabled(False)
        col.addWidget(card_t)

        col.addStretch(1)
        scroll.setWidget(cont)
        root.addWidget(scroll)

    # ── API pública ──────────────────────────────────────────────────────────
    def resumen(self) -> Dict[str, Dict[str, float]]:
        return self._resumen

    def set_titulo(self, titulo: str) -> None:
        if self.lbl_tabla is not None:
            self.lbl_tabla.setText(titulo)

    def set_export_enabled(self, on: bool) -> None:
        self.btn_csv.setEnabled(on)
        self.btn_resumen.setEnabled(on)

    def reset(self) -> None:
        """Limpia cards de KPIs, histogramas y tabla resumen a su estado vacío."""
        self._resumen = {}
        for clave, _et, _c in KPI_DESTACADOS:
            self._kpi_cards[clave].setText("—")
            self._kpi_sub[clave].setText("")
            self._hist[clave].set_values([])
        self.tabla.setRowCount(0)
        self._ajustar_altura_tabla()
        self.set_titulo("RESUMEN ESTADÍSTICO")
        self.set_export_enabled(False)

    def render(self, filas: List[Dict[str, Any]], titulo: str) -> None:
        """Render común de resultados (finales o parciales) a cards/histos/tabla."""
        self._resumen = resumir(filas)
        self.set_titulo(titulo)

        for clave, _et, _c in KPI_DESTACADOS:
            st = self._resumen.get(clave)
            if st:
                self._kpi_cards[clave].setText(fmt_mc_kpi(clave, st["p50"], compact=True))
                self._kpi_sub[clave].setText(
                    f"P10 {fmt_mc_kpi(clave, st['p10'], compact=True)} · "
                    f"P90 {fmt_mc_kpi(clave, st['p90'], compact=True)}")
            self._hist[clave].set_values([float(r[clave]) for r in filas if clave in r])

        variables = sorted(self._resumen)
        self.tabla.setRowCount(len(variables))
        for i, var in enumerate(variables):
            st = self._resumen[var]
            celdas = [var,
                      fmt_mc_kpi(var, st["mean"]),
                      fmt_mc_kpi(var, st["std"]),
                      fmt_mc_kpi(var, st["p10"]),
                      fmt_mc_kpi(var, st["p50"]),
                      fmt_mc_kpi(var, st["p90"])]
            for j, txt in enumerate(celdas):
                item = QTableWidgetItem(txt)
                if j > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(i, j, item)
        self._ajustar_altura_tabla()

    def _ajustar_altura_tabla(self) -> None:
        """Expande la tabla para mostrar todas las filas sin scroll interno."""
        header_h = self.tabla.horizontalHeader().height()
        frame = self.tabla.frameWidth() * 2
        filas_h = sum(self.tabla.rowHeight(i) for i in range(self.tabla.rowCount()))
        self.tabla.setFixedHeight(header_h + filas_h + frame)
