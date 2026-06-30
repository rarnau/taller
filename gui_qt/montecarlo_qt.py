"""Pestaña Monte Carlo: barrido de miles de corridas con parámetros sorteados.

Panel izquierdo: rangos ``[min,max]`` por máquina (rate prod/desb, tasa de falla)
y globales (enfriado, traslado CRC), selectores fijos (estrategias, generador,
duración, turnos), N de corridas y botón de ejecución con barra de progreso.
Panel derecho: cards de KPIs (P10/P50/P90), histogramas y tabla resumen
(media/desv/P10/P50/P90), con export a CSV.

La ejecución corre en un hilo de fondo (``MonteCarloService``) que a su vez usa
el pool de procesos de ``montecarlo.correr_montecarlo``; ``MainWindow`` sondea el
avance con un ``QTimer`` (mismo patrón que la simulación simple).
"""
from __future__ import annotations

import copy
import os
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
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
from modelos.estrategias import ESTRATEGIAS_ASIGNACION, ESTRATEGIAS_SELECCION
from modelos.generador_cambios import GENERADORES_CAMBIOS
from modelos import turnos as turnos_mod
from montecarlo import EspecMonteCarlo, exportar_resumen_csv, resumir
from gui_qt.services import MonteCarloRequest
from gui_qt.widgets import SectionCard

# KPIs destacados en cards + histogramas (clave, etiqueta, color).
_KPI_DESTACADOS: List[Tuple[str, str, str]] = [
    ("bajas", "Bajas", tema.RED),
    ("paradas", "Paradas de jaula", tema.ORANGE),
    ("stock_min", "Stock mínimo", tema.GREEN),
    ("nivel_servicio_pct", "Nivel de servicio %", tema.PURPLE),
]


class _HistogramWidget(QWidget):
    """Histograma simple con líneas P10/P50/P90 (pintado nativo)."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = color
        self._vals: np.ndarray = np.array([], dtype=float)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, valores: List[float]) -> None:
        self._vals = np.array([float(v) for v in valores], dtype=float)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt API)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        base = h - 18
        if self._vals.size == 0:
            p.setPen(QColor(tema.FG_DIM))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "sin datos")
            return

        lo, hi = float(self._vals.min()), float(self._vals.max())
        nbins = 12
        if hi <= lo:  # todos iguales: una sola barra centrada
            self._barra_unica(p, w, base)
        else:
            counts, edges = np.histogram(self._vals, bins=nbins, range=(lo, hi))
            cmax = max(int(counts.max()), 1)
            bw = w / nbins
            col = QColor(self._color)
            col.setAlpha(205)
            for i, c in enumerate(counts):
                bh = (c / cmax) * (base - 4)
                p.fillRect(int(i * bw) + 1, int(base - bh),
                           max(1, int(bw) - 2), int(bh), col)
            for pct, color in ((10, tema.ACCENT), (50, tema.DASH_TITLE), (90, tema.GREEN)):
                x = (np.percentile(self._vals, pct) - lo) / (hi - lo) * w
                pen = QPen(QColor(color))
                pen.setWidth(2)
                p.setPen(pen)
                p.drawLine(int(x), 0, int(x), int(base))

        # Ejes mínimos y rótulos de extremos.
        p.setPen(QColor(tema.DASH_AXIS))
        p.drawLine(0, int(base), w, int(base))
        p.setPen(QColor(tema.DASH_TICK_TEXT))
        p.drawText(2, h - 4, f"{lo:.1f}")
        p.drawText(w - 48, h - 4, f"{hi:.1f}")

    def _barra_unica(self, p: QPainter, w: int, base: int) -> None:
        col = QColor(self._color)
        col.setAlpha(205)
        p.fillRect(int(w * 0.42), 4, int(w * 0.16), base - 4, col)


class MonteCarloPanel(QWidget):
    """Panel de configuración y resultados del estudio de Monte Carlo."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        on_run: Callable[[MonteCarloRequest], None],
        on_cfg_saved: Callable[[Dict[str, Any]], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = copy.deepcopy(cfg)
        self._on_run = on_run
        self._on_cfg_saved = on_cfg_saved
        self._stock_df = None
        self._csv_path: Optional[str] = None
        self._resumen: Dict[str, Dict[str, float]] = {}

        # Widgets de rangos: clave -> (spin_min, spin_max).
        self._rangos: Dict[Tuple[str, ...], Tuple[QDoubleSpinBox, QDoubleSpinBox]] = {}
        self._hist: Dict[str, _HistogramWidget] = {}
        self._kpi_cards: Dict[str, QLabel] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._build_left(), 0)
        root.addWidget(self._build_right(), 1)
        self._reload_widgets_from_cfg()

    # ── Construcción UI ──────────────────────────────────────────────────────

    def _build_left(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(320)

        cont = QWidget()
        col = QVBoxLayout(cont)
        col.setContentsMargins(2, 2, 8, 2)
        col.setSpacing(10)

        # Una card por máquina (rate prod/desb, tasa de falla).
        self._maq_box = QVBoxLayout()
        self._maq_box.setSpacing(10)
        col.addLayout(self._maq_box)

        # Globales.
        card_g = SectionCard(title="GLOBALES", object_name="CardSoft")
        gl = card_g.content_layout()
        gl.addLayout(self._fila_rango(("global", "tiempo_enfriado"),
                                      "Tiempo de enfriamiento", "h", 0.0, 48.0, 0.5, 1))
        gl.addLayout(self._fila_rango(("global", "tiempo_traslado_crc"),
                                      "Tiempo traslado CRC", "min", 0.0, 240.0, 1.0, 0))
        col.addWidget(card_g)

        # Selectores fijos.
        card_f = SectionCard(title="CONFIGURACIÓN FIJA", object_name="CardSoft")
        fl = card_f.content_layout()
        self.cb_sel = self._combo([(k, v.etiqueta) for k, v in ESTRATEGIAS_SELECCION.items()])
        self.cb_asig = self._combo([(k, v.etiqueta) for k, v in ESTRATEGIAS_ASIGNACION.items()])
        self.cb_gen = self._combo([(k, g.etiqueta) for k, g in GENERADORES_CAMBIOS.items()])
        self.cb_turnos_maq = self._combo(
            [(k, turnos_mod.PRESET_LABELS.get(k, k)) for k in turnos_mod.PRESETS])
        self.cb_turnos_lam = self._combo(
            [(k, turnos_mod.PRESET_LABELS.get(k, k)) for k in turnos_mod.PRESETS])
        self.sp_duracion = QSpinBox()
        self.sp_duracion.setRange(1, 120)
        fl.addLayout(self._fila_widget("Estrategia de rectificado", self.cb_sel))
        fl.addLayout(self._fila_widget("Estrategia de asignación", self.cb_asig))
        fl.addLayout(self._fila_widget("Generador de cambios", self.cb_gen))
        fl.addLayout(self._fila_widget("Duración de corrida (días)", self.sp_duracion))
        fl.addLayout(self._fila_widget("Turnos máquinas", self.cb_turnos_maq))
        fl.addLayout(self._fila_widget("Turnos laminador", self.cb_turnos_lam))
        col.addWidget(card_f)

        # Corridas + seed.
        card_n = SectionCard(title="CORRIDAS", object_name="CardSoft")
        nl = card_n.content_layout()
        self.sp_runs = QSpinBox()
        self.sp_runs.setRange(1, 100000)
        presets = QHBoxLayout()
        for v in (100, 500, 1000, 2000):
            b = QPushButton(f"{v // 1000}k" if v >= 1000 else str(v))
            b.clicked.connect(lambda _=False, n=v: self.sp_runs.setValue(n))
            presets.addWidget(b)
        nl.addLayout(self._fila_widget("Número de corridas", self.sp_runs))
        nl.addLayout(presets)
        self.sp_seed = QSpinBox()
        self.sp_seed.setRange(0, 2_000_000_000)
        self.sp_seed.setSpecialValueText("aleatoria")
        nl.addLayout(self._fila_widget("Master seed (0 = aleatoria)", self.sp_seed))
        self.chk_dump = QCheckBox("Volcar tallers completos a disco")
        nl.addWidget(self.chk_dump)
        col.addWidget(card_n)

        self.btn_run = QPushButton("▶  Ejecutar Monte Carlo")
        self.btn_run.setObjectName("RunButton")
        self.btn_run.clicked.connect(self._ejecutar)
        col.addWidget(self.btn_run)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        col.addWidget(self.progress)
        self.lbl_progress = QLabel("")
        self.lbl_progress.setObjectName("Muted")
        col.addWidget(self.lbl_progress)

        col.addStretch(1)
        scroll.setWidget(cont)
        return scroll

    def _build_right(self) -> QWidget:
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        cont = QWidget()
        col = QVBoxLayout(cont)
        col.setContentsMargins(2, 2, 2, 2)
        col.setSpacing(12)

        # Cards de KPIs (P50 grande + P10/P90).
        cards = QGridLayout()
        cards.setSpacing(10)
        for i, (clave, etiqueta, color) in enumerate(_KPI_DESTACADOS):
            card = SectionCard(title=etiqueta, object_name="CardSoft")
            lbl = QLabel("—")
            lbl.setStyleSheet(f"font-size:24px; font-weight:700; color:{color};")
            card.content_layout().addWidget(lbl)
            self._kpi_cards[clave] = lbl
            cards.addWidget(card, 0, i)
        col.addLayout(cards)

        # Histogramas 2×2.
        hist = QGridLayout()
        hist.setSpacing(10)
        for i, (clave, etiqueta, color) in enumerate(_KPI_DESTACADOS):
            card = SectionCard(title=f"Distribución · {etiqueta}", object_name="CardSoft")
            hw = _HistogramWidget(color)
            card.content_layout().addWidget(hw)
            self._hist[clave] = hw
            hist.addWidget(card, i // 2, i % 2)
        col.addLayout(hist)

        # Tabla resumen.
        card_t = SectionCard(title="RESUMEN ESTADÍSTICO", object_name="CardSoft")
        self.lbl_tabla = card_t.title_label
        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(["Variable", "Media", "Desv.", "P10", "P50", "P90"])
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        card_t.content_layout().addWidget(self.tabla)
        btns = QHBoxLayout()
        self.btn_csv = QPushButton("⤓ Exportar CSV de corridas")
        self.btn_csv.clicked.connect(self._exportar_corridas)
        self.btn_resumen = QPushButton("⤓ Exportar resumen")
        self.btn_resumen.clicked.connect(self._exportar_resumen)
        btns.addWidget(self.btn_csv)
        btns.addWidget(self.btn_resumen)
        btns.addStretch(1)
        card_t.content_layout().addLayout(btns)
        self._set_export_enabled(False)
        col.addWidget(card_t)

        col.addStretch(1)
        scroll.setWidget(cont)
        return scroll

    # ── Helpers de construcción ──────────────────────────────────────────────

    def _combo(self, opciones: List[Tuple[str, str]]) -> QComboBox:
        cb = QComboBox()
        for clave, etiqueta in opciones:
            cb.addItem(etiqueta, clave)
        return cb

    def _fila_widget(self, label: str, widget: QWidget) -> QHBoxLayout:
        fila = QHBoxLayout()
        lab = QLabel(label)
        lab.setMinimumWidth(150)
        fila.addWidget(lab)
        fila.addWidget(widget, 1)
        return fila

    def _spin(self, decimals: int, step: float, maximo: float) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setDecimals(decimals)
        s.setSingleStep(step)
        s.setRange(0.0, maximo)
        s.setMaximumWidth(90)
        return s

    def _fila_rango(self, clave: Tuple[str, ...], label: str, unit: str,
                    maximo_inf: float, maximo: float, step: float,
                    decimals: int) -> QVBoxLayout:
        box = QVBoxLayout()
        cab = QHBoxLayout()
        lab = QLabel(label)
        u = QLabel(unit)
        u.setObjectName("Muted")
        cab.addWidget(lab)
        cab.addStretch(1)
        cab.addWidget(u)
        box.addLayout(cab)
        smin = self._spin(decimals, step, maximo)
        smax = self._spin(decimals, step, maximo)
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Mín"))
        fila.addWidget(smin)
        fila.addStretch(1)
        fila.addWidget(QLabel("Máx"))
        fila.addWidget(smax)
        box.addLayout(fila)
        self._rangos[clave] = (smin, smax)
        return box

    # ── Estado / datos ───────────────────────────────────────────────────────

    def set_stock_df(self, stock_df) -> None:
        self._stock_df = stock_df

    def actualizar_cfg(self, cfg: Dict[str, Any]) -> None:
        """Refresca el cfg base (p. ej. tras guardar en Configuración)."""
        self._cfg = copy.deepcopy(cfg)
        self._rebuild_machine_cards()
        self._reload_widgets_from_cfg()

    def _rebuild_machine_cards(self) -> None:
        # Limpia las cards de máquina y los rangos por máquina previos.
        while self._maq_box.count():
            item = self._maq_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for clave in [k for k in self._rangos if k[0] == "maq"]:
            self._rangos.pop(clave, None)

        for m in obtener_maquinas(self._cfg):
            nombre = m["nombre"]
            card = SectionCard(title=f"MÁQUINA · {nombre}", object_name="CardSoft")
            cl = card.content_layout()
            cl.addLayout(self._fila_rango(("maq", nombre, "rate_prod"),
                                          "Rate producción", "mm/min", 0.0, 1.0, 0.001, 4))
            cl.addLayout(self._fila_rango(("maq", nombre, "rate_desb"),
                                          "Rate desbaste", "mm/min", 0.0, 1.0, 0.001, 4))
            cl.addLayout(self._fila_rango(("maq", nombre, "tasa_falla"),
                                          "Tasa de falla", "frac", 0.0, 1.0, 0.01, 3))
            self._maq_box.addWidget(card)

    def _reload_widgets_from_cfg(self) -> None:
        """Carga los valores de los widgets desde el bloque montecarlo del cfg."""
        if not any(k[0] == "maq" for k in self._rangos):
            self._rebuild_machine_cards()
        mc = obtener_montecarlo(self._cfg)
        self.sp_runs.setValue(int(mc["runs"]))
        self.sp_seed.setValue(int(mc.get("master_seed") or 0))
        fijos = mc["fijos"]
        self._set_combo(self.cb_sel, fijos.get("estrategia_seleccion"))
        self._set_combo(self.cb_asig, fijos.get("estrategia_asignacion"))
        self._set_combo(self.cb_gen, fijos.get("generador"))
        self._set_combo(self.cb_turnos_maq, fijos.get("turnos_maquinas_preset"))
        self._set_combo(self.cb_turnos_lam, fijos.get("turnos_laminador_preset"))
        self.sp_duracion.setValue(int(fijos.get("duracion_dias", 7)))

        r = mc["rangos"]
        self._set_rango(("global", "tiempo_enfriado"), r["tiempo_enfriado"])
        self._set_rango(("global", "tiempo_traslado_crc"), r["tiempo_traslado_crc"])
        for nombre, rr in r.get("maquinas", {}).items():
            for campo in ("rate_prod", "rate_desb", "tasa_falla"):
                self._set_rango(("maq", nombre, campo), rr[campo])

    def _set_combo(self, cb: QComboBox, clave: Optional[str]) -> None:
        idx = cb.findData(clave)
        if idx >= 0:
            cb.setCurrentIndex(idx)

    def _set_rango(self, clave: Tuple[str, ...], par: Any) -> None:
        widgets = self._rangos.get(clave)
        if widgets and par:
            widgets[0].setValue(float(par[0]))
            widgets[1].setValue(float(par[1]))

    def _mc_desde_widgets(self) -> Dict[str, Any]:
        """Arma el dict montecarlo desde los widgets actuales."""
        maquinas: Dict[str, Any] = {}
        for clave, (smin, smax) in self._rangos.items():
            if clave[0] == "maq":
                _, nombre, campo = clave
                maquinas.setdefault(nombre, {})[campo] = [smin.value(), smax.value()]
        return {
            "runs": self.sp_runs.value(),
            "master_seed": (self.sp_seed.value() or None),
            "chunk": max(1, self.sp_runs.value() // 20),
            "fijos": {
                "estrategia_seleccion": self.cb_sel.currentData(),
                "estrategia_asignacion": self.cb_asig.currentData(),
                "generador": self.cb_gen.currentData(),
                "duracion_dias": self.sp_duracion.value(),
                "turnos_maquinas_preset": self.cb_turnos_maq.currentData(),
                "turnos_laminador_preset": self.cb_turnos_lam.currentData(),
            },
            "rangos": {
                "tiempo_enfriado": [v.value() for v in self._rangos[("global", "tiempo_enfriado")]],
                "tiempo_traslado_crc": [v.value() for v in self._rangos[("global", "tiempo_traslado_crc")]],
                "maquinas": maquinas,
            },
        }

    # ── Ejecución ────────────────────────────────────────────────────────────

    def _ejecutar(self) -> None:
        if self._stock_df is None:
            QMessageBox.warning(self, "Atención",
                                "Primero cargue un Excel con Stock_Inicial.")
            return
        modelo = model_store.load_active_model()
        if not modelo:
            QMessageBox.warning(self, "Atención",
                                "No hay modelo del generador. Ajustá uno en la pestaña Generación.")
            return

        mc = self._mc_desde_widgets()
        set_montecarlo(self._cfg, mc)
        guardar_config(self._cfg)
        if self._on_cfg_saved:
            self._on_cfg_saved(self._cfg)

        dump_dir = None
        if self.chk_dump.isChecked():
            dump_dir = QFileDialog.getExistingDirectory(self, "Carpeta para volcar tallers")
            if not dump_dir:
                return

        self._csv_path = os.path.join(tempfile.gettempdir(), "montecarlo_resultados.csv")
        spec = EspecMonteCarlo.desde_cfg(self._cfg)
        req = MonteCarloRequest(base_cfg=self._cfg, stock_df=self._stock_df,
                                modelo=modelo, spec=spec, csv_path=self._csv_path,
                                dump_dir=dump_dir or None)
        self.set_running(True)
        self._on_run(req)

    def set_running(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.progress.setVisible(running)
        if running:
            self.progress.setValue(0)
            self.lbl_progress.setText("Simulando...")

    def set_progress(self, hechos: int, total: int) -> None:
        pct = int(hechos / total * 100) if total else 0
        self.progress.setMaximum(100)
        self.progress.setValue(pct)
        self.lbl_progress.setText(f"{hechos}/{total} corridas")

    def mostrar_resultados(self, filas: List[Dict[str, Any]]) -> None:
        self.set_running(False)
        self.lbl_progress.setText(f"{len(filas)} corridas completadas")
        self._resumen = resumir(filas)
        if self.lbl_tabla is not None:
            self.lbl_tabla.setText(f"RESUMEN ESTADÍSTICO · {len(filas)} corridas")

        for clave, _et, _c in _KPI_DESTACADOS:
            st = self._resumen.get(clave)
            if st:
                self._kpi_cards[clave].setText(
                    f"{st['p50']:.0f}\nP10 {st['p10']:.0f} · P90 {st['p90']:.0f}")
            self._hist[clave].set_values([float(r[clave]) for r in filas if clave in r])

        variables = sorted(self._resumen)
        self.tabla.setRowCount(len(variables))
        for i, var in enumerate(variables):
            st = self._resumen[var]
            celdas = [var, f"{st['mean']:.2f}", f"{st['std']:.2f}",
                      f"{st['p10']:.2f}", f"{st['p50']:.2f}", f"{st['p90']:.2f}"]
            for j, txt in enumerate(celdas):
                item = QTableWidgetItem(txt)
                if j > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(i, j, item)
        self._set_export_enabled(True)

    def set_error(self, msg: str) -> None:
        self.set_running(False)
        self.lbl_progress.setText("Error")
        QMessageBox.critical(self, "Error", f"No se pudo ejecutar el Monte Carlo:\n{msg}")

    # ── Export ───────────────────────────────────────────────────────────────

    def _set_export_enabled(self, on: bool) -> None:
        self.btn_csv.setEnabled(on)
        self.btn_resumen.setEnabled(on)

    def _exportar_corridas(self) -> None:
        if not self._csv_path or not os.path.exists(self._csv_path):
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar CSV de corridas",
                                              "montecarlo_corridas.csv", "CSV (*.csv)")
        if ruta:
            import shutil
            shutil.copyfile(self._csv_path, ruta)

    def _exportar_resumen(self) -> None:
        if not self._resumen:
            return
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar resumen estadístico",
                                              "montecarlo_resumen.csv", "CSV (*.csv)")
        if ruta:
            exportar_resumen_csv(self._resumen, ruta)
