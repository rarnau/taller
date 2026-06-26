"""Pestaña Generación: parámetros, línea de tiempo y tabla de cambios.

"Regenerar" ajusta un modelo (persistido o desde la historia de ejemplo) y
produce un ``Programa_Cambios`` reproducible con ``modelos.generador_cambios``,
que la simulación de la barra lateral consume.
"""
from __future__ import annotations

import os

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QHBoxLayout, QPushButton,
                               QVBoxLayout, QWidget)

from config.persistencia import obtener_generador_cambios
from modelos import generador_cambios as gencambios

from .. import theme as T
from ..charts import VectorChart
from ..widgets import label, panel, titulo_seccion

_RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HISTORIA = os.path.join(_RAIZ, "datos", "historia_ejemplo.csv")
_MOTIVO_COLOR = {"produccion": T.BLUE, "desbaste": T.ORANGE_2}


class VistaGeneracion(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setStyleSheet("background:transparent;")
        self.cambios_df: pd.DataFrame | None = None
        self._seed = 7
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(16)
        self._build_header()
        self.params_grid = QGridLayout()
        self.params_grid.setSpacing(12)
        self.lay.addLayout(self.params_grid)
        self.timeline_panel = panel()
        self.lay.addWidget(self.timeline_panel)
        self.lay.addStretch()
        self._render(None)

    def _build_header(self):
        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(label("Generación de cambios", size=15, weight=700, family=T.FONT_DISPLAY))
        head.addStretch()
        b_gen = QPushButton("↻ Regenerar")
        b_gen.setCursor(Qt.PointingHandCursor)
        b_gen.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {T.GREEN_3},stop:1 {T.GREEN_2});"
            f" border:none; color:#062014; border-radius:8px; padding:7px 14px; font-size:12px; font-weight:700;}}")
        b_gen.clicked.connect(self.regenerar)
        head.addWidget(b_gen)
        b_up = QPushButton("⤓ Subir cambios")
        b_up.setCursor(Qt.PointingHandCursor)
        b_up.setStyleSheet(
            f"QPushButton{{background:{T.TRACK}; border:1px solid {T.BORDER_IN}; color:{T.TEXT_2};"
            f" border-radius:8px; padding:7px 12px; font-size:12px;}}")
        b_up.clicked.connect(self.subir_cambios)
        head.addWidget(b_up)
        self.lay.addLayout(head)

    # ── Acciones ──────────────────────────────────────────────────────────────
    def regenerar(self):
        self._seed += 1
        try:
            from config import modelo_generador as mg
            modelo = mg.cargar_modelo()
            if modelo is None and os.path.exists(_HISTORIA):
                hist = pd.read_csv(_HISTORIA)
                modelo = gencambios.ajustar_modelo(hist, self.app.cfg)
            if modelo is None:
                raise RuntimeError("sin modelo")
            df = gencambios.generar_cambios(modelo, self.app.cfg, seed=self._seed)
            self.cambios_df = df
            self._render(df)
        except Exception as e:  # noqa: BLE001
            self.app.views["consola"].append(f"⚠ No se pudieron generar cambios: {e}")

    def subir_cambios(self):
        fp, _ = QFileDialog.getOpenFileName(self, "Subir cambios", _RAIZ, "Excel (*.xlsx)")
        if not fp:
            return
        try:
            df = pd.read_excel(fp, sheet_name="Programa_Cambios")
            self.cambios_df = df
            self.app.cambios_df = df
            self._render(df)
        except Exception as e:  # noqa: BLE001
            self.app.views["consola"].append(f"⚠ No se pudo leer el Excel: {e}")

    def refrescar_timeline(self, taller=None):
        df = self.cambios_df if self.cambios_df is not None else self.app.cambios_df
        self._render(df)

    # ── Render ─────────────────────────────────────────────────────────────────
    def _render(self, df):
        self._render_params(df)
        self._render_timeline(df)

    def _render_params(self, df):
        while self.params_grid.count():
            it = self.params_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        gc = obtener_generador_cambios(self.app.cfg)
        n = 0 if df is None else len(df)
        ventana = "—"
        cpd = "—"
        if df is not None and n and "Fecha_Hora" in df.columns:
            fechas = pd.to_datetime(df["Fecha_Hora"])
            dias = max(1, (fechas.max() - fechas.min()).days)
            ventana = f"{fechas.min():%d/%m}–{fechas.max():%d/%m}"
            cpd = f"~{round(n / dias)}"
        params = [
            ("Semilla", str(self._seed)),
            ("Nº de cambios", str(n)),
            ("Generador", str(gc.get("generador", "empirico"))),
            ("Umbral desbaste", f"{gc.get('umbral_desbaste_mm', '—')} mm"),
            ("Cambios / día", cpd),
            ("Ventana", ventana),
        ]
        for i, (k, v) in enumerate(params):
            p = panel(14)
            p.layout().setSpacing(6)
            p.layout().addWidget(label(k, color=T.TEXT_MUTE, size=11, weight=700, ls=0.4))
            p.layout().addWidget(label(v, color=T.TEXT, size=17, family=T.FONT_MONO))
            self.params_grid.addWidget(p, i // 3, i % 3)

    def _render_timeline(self, df):
        lay = self.timeline_panel.layout()
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._del_layout(it.layout())
        lay.addWidget(titulo_seccion("LÍNEA DE TIEMPO", T.ORANGE, size=12))
        if df is None or len(df) == 0:
            lay.addWidget(label("Sin cambios generados. Use «Regenerar» o «Subir cambios».",
                                color=T.TEXT_MUTE, size=12.5))
            return
        chart = VectorChart(40, pad=(0, 0, 0, 0))
        chart.setMaximumHeight(40)
        fechas = pd.to_datetime(df["Fecha_Hora"])
        t0, t1 = fechas.min(), fechas.max()
        span = max(1.0, (t1 - t0).total_seconds())
        vlines = []
        for _, r in df.iterrows():
            pos = (pd.to_datetime(r["Fecha_Hora"]) - t0).total_seconds() / span
            tipo = str(r.get("Tipo_Rectificado", "produccion")).lower()
            vlines.append({"x": pos, "color": _MOTIVO_COLOR.get(tipo, T.PURPLE), "width": 3})
        chart.set_series(rects=[{"x": 0, "y": 0, "w": 1, "h": 1, "color": T.HOLE, "radius": 6}], vlines=vlines)
        lay.addWidget(chart)
        # Tabla (primeras filas)
        for _, r in df.head(40).iterrows():
            row = QHBoxLayout()
            row.setSpacing(10)
            fecha = pd.to_datetime(r["Fecha_Hora"]).strftime("%d/%m %H:%M")
            tipo = str(r.get("Tipo_Rectificado", "")).lower()
            col = _MOTIVO_COLOR.get(tipo, T.PURPLE)
            row.addWidget(self._cell(fecha, T.TEXT_2, 130, mono=True))
            row.addWidget(self._cell(f"J{r.get('Jaula', '')}", T.TEXT_MUTE, 50, mono=True))
            row.addWidget(self._cell(f"{tipo} · {r.get('mm_a_Rectificar', '')} mm", T.TEXT_2, 160, mono=True))
            obs_raw = r.get("Observación", "")
            motivo = tipo if pd.isna(obs_raw) or not str(obs_raw).strip() else str(obs_raw)
            obs = self._cell(f"●  {motivo}", col, 0)
            row.addWidget(obs, 1)
            w = QWidget()
            w.setStyleSheet(f"background:transparent; border-bottom:1px solid {T.ROW_LINE};")
            w.setLayout(row)
            lay.addWidget(w)

    def _cell(self, text, color, width, mono=False):
        lb = label(str(text), color=color, size=12.5, family=T.FONT_MONO if mono else T.FONT_UI)
        if width:
            lb.setFixedWidth(width)
        return lb

    def _del_layout(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                self._del_layout(it.layout())
