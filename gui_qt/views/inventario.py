"""Pestaña Inventario: tabla de cilindros (stock inicial / final) + carga Excel."""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from modelos.enums import EstadoCilindro

from .. import theme as T
from ..widgets import label

_COLS = ["ID", "DIÁMETRO", "ORIGINAL", "DESGASTE", "ESTADO", "JAULA"]


class VistaInventario(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setStyleSheet("background:transparent;")
        self._stock_df: pd.DataFrame | None = None
        self._modo_final = False
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.titulo = label("Inventario de cilindros", size=15, weight=700, family=T.FONT_DISPLAY)
        head.addWidget(self.titulo)
        self.conteo = label("0 registros", color=T.TEXT_MUTE, size=12, family=T.FONT_MONO)
        head.addWidget(self.conteo)
        head.addStretch()
        self.btn_vista = self._btn("Stock inicial")
        self.btn_vista.clicked.connect(self._toggle_vista)
        head.addWidget(self.btn_vista)
        b_load = self._btn("⤓ Cargar stock (Excel)")
        b_load.clicked.connect(self.app.abrir_stock)
        head.addWidget(b_load)
        b_dl = self._btn("⤧ Descargar resultado")
        b_dl.clicked.connect(self.app._exportar)
        head.addWidget(b_dl)
        lay.addLayout(head)

        self.tabla = QTableWidget(0, len(_COLS))
        self.tabla.setHorizontalHeaderLabels(_COLS)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setShowGrid(False)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setSelectionMode(QTableWidget.NoSelection)
        self.tabla.setStyleSheet(
            f"QTableWidget{{background:{T.PANEL}; border:1px solid {T.BORDER}; border-radius:12px;"
            f" gridline-color:transparent; color:{T.TEXT_2};}}"
            f"QHeaderView::section{{background:{T.PANEL_2}; color:{T.TEXT_MUTE}; border:none;"
            f" border-bottom:1px solid {T.BORDER}; padding:10px 12px; font-size:10.5px; font-weight:700;}}"
            f"QTableWidget::item{{border-bottom:1px solid {T.ROW_LINE}; padding:8px 12px;}}")
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.tabla, 1)

    def _btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setCursor(Qt.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{T.TRACK}; border:1px solid {T.BORDER_IN}; color:{T.TEXT_2};"
            f" border-radius:8px; padding:7px 12px; font-size:12px;}} QPushButton:hover{{border-color:{T.ORANGE};}}")
        return b

    # ── Datos ─────────────────────────────────────────────────────────────────
    def set_stock(self, df: pd.DataFrame):
        self._stock_df = df
        if not self._modo_final:
            self._render_stock_inicial()

    def set_taller(self, taller):
        self._taller = taller
        if self._modo_final:
            self._render_stock_final()

    def _toggle_vista(self):
        self._modo_final = not self._modo_final
        if self._modo_final:
            self.btn_vista.setText("Stock final")
            self._render_stock_final()
        else:
            self.btn_vista.setText("Stock inicial")
            self._render_stock_inicial()

    def _render_stock_inicial(self):
        df = self._stock_df
        self.titulo.setText("Inventario de cilindros · stock inicial")
        if df is None:
            self.tabla.setRowCount(0)
            self.conteo.setText("0 registros")
            return
        # Detectar columnas con tolerancia (por subcadena, sin acentos)
        def _buscar(*claves):
            for c in df.columns:
                cl = str(c).lower()
                if any(k in cl for k in claves):
                    return c
            return None

        cid = _buscar("id") or list(df.columns)[0]
        cdia = _buscar("diámetro", "diametro")
        corig = _buscar("original") or cdia
        cest = _buscar("estado")
        cjaula = _buscar("jaula")
        filas = []
        for _, r in df.iterrows():
            d = float(r[cdia]) if cdia and pd.notna(r[cdia]) else 0.0
            o = float(r[corig]) if corig and pd.notna(r[corig]) else d
            est = str(r[cest]) if cest else "Disponible"
            jaula = "—"
            if cjaula and pd.notna(r[cjaula]):
                jaula = f"J{int(r[cjaula])}"
            filas.append((str(r[cid]), d, o, est, jaula))
        self._llenar(filas)

    def _render_stock_final(self):
        t = getattr(self, "_taller", None)
        self.titulo.setText("Inventario de cilindros · stock final")
        if t is None or not getattr(t, "snapshots", None):
            self.tabla.setRowCount(0)
            self.conteo.setText("Ejecute la simulación para ver el stock final")
            return
        filas = []
        for c in t.cilindros.values():
            jaula = "—"
            if c.jaula:
                jaula = f"J{c.jaula}"
            elif c.jaula_destino:
                jaula = f"J{c.jaula_destino}"
            filas.append((c.id, c.diametro, c.diametro_original, c.estado.value, jaula))
        self._llenar(filas)

    def _llenar(self, filas):
        self.tabla.setRowCount(len(filas))
        self.conteo.setText(f"{len(filas)} registros")
        for i, (cid, dia, orig, est, jaula) in enumerate(filas):
            color = T.COL_ESTADO.get(est, T.TEXT_MUTE)
            vals = [cid, f"{dia:.1f}", f"{orig:.1f}", f"−{orig - dia:.1f}", est, jaula]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j == 0:
                    it.setForeground(Qt.white)
                elif j == 3:
                    it.setForeground(_qcolor(T.ORANGE_2))
                elif j == 4:
                    it.setForeground(_qcolor(color))
                else:
                    it.setForeground(_qcolor(T.TEXT_2))
                self.tabla.setItem(i, j, it)


def _qcolor(hexc: str):
    from PySide6.QtGui import QColor
    return QColor(hexc)
