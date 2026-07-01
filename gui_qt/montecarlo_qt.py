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
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
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
from nucleo.montecarlo import EspecMonteCarlo, exportar_resumen_csv, resumir
from gui_qt.services import MonteCarloRequest
from gui_qt.widgets import SectionCard

# KPIs destacados en cards + histogramas (clave, etiqueta, color).
_KPI_DESTACADOS: List[Tuple[str, str, str]] = [
    ("bajas", "Bajas", tema.RED),
    ("paradas", "Paradas de jaula", tema.ORANGE),
    ("tiempo_parada_h", "Tiempo de parada", tema.DASH_PARADA_BAND),
    ("parada_pct", "Tiempo en parada %", tema.DASH_PARADA),
    ("stock_min", "Stock mínimo", tema.GREEN),
]


def _fmt_mc_kpi(clave: str, valor: float, *, compact: bool = False) -> str:
    """Formatea valores de KPIs de Monte Carlo para cards/tabla."""
    v = float(valor)
    if clave == "tiempo_parada_h":
        return f"{v:.1f} h"
    if clave == "parada_pct":
        return f"{v:.1f}%"
    if clave in {"bajas", "paradas", "stock_min"}:
        return f"{v:.0f}" if compact else f"{v:.2f}"
    return f"{v:.0f}" if compact else f"{v:.2f}"


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
            for pct, color in ((10, tema.ACCENT), (50, tema.ACCENT), (90, tema.GREEN)):
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


class _FloatSlider(QWidget):
    """Slider horizontal para un float en ``[0, maximo]`` con paso fijo + valor.

    Qt maneja sliders enteros, así que internamente trabaja en *ticks*
    (``valor / step``) y expone ``value()``/``setValue()`` en float, igual
    interfaz que un ``QDoubleSpinBox`` (así el resto del panel no cambia).
    """

    def __init__(self, maximo: float, step: float, decimals: int, color: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._step = step
        self._dec = decimals
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setObjectName("McRangeSlider")
        self._slider.setRange(0, max(1, int(round(maximo / step))))
        self._slider.setSingleStep(1)
        self._lbl = QLabel("0")
        self._lbl.setMinimumWidth(48)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._lbl.setStyleSheet(f"color:{color}; font-family:monospace; font-size:11px;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._slider, 1)
        lay.addWidget(self._lbl, 0)
        self._slider.valueChanged.connect(self._refrescar_label)
        self._refrescar_label()

    def value(self) -> float:
        return self._slider.value() * self._step

    def setValue(self, v: float) -> None:
        # Bloquea señales: la carga programática no debe disparar el acople
        # Mín≤Máx (que clamparía antes de fijar ambos sliders).
        self._slider.blockSignals(True)
        self._slider.setValue(int(round(float(v) / self._step)))
        self._slider.blockSignals(False)
        self._refrescar_label()

    def _refrescar_label(self) -> None:
        self._lbl.setText(f"{self.value():.{self._dec}f}")

    @property
    def slider(self) -> QSlider:
        return self._slider


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
        self._rangos: Dict[Tuple[str, ...], Tuple[_FloatSlider, _FloatSlider]] = {}
        self._hist: Dict[str, _HistogramWidget] = {}
        self._kpi_cards: Dict[str, QLabel] = {}
        self._kpi_sub: Dict[str, QLabel] = {}
        self._chip_groups: Dict[str, List[Tuple[QPushButton, Any]]] = {}
        self._run_preset_buttons: List[Tuple[int, QPushButton]] = []
        # {nombre_maquina: (combo_hidden, le_custom)} para turnos per-máquina
        self._turnos_maq_widgets: Dict[str, Tuple[QComboBox, Any]] = {}

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
        scroll.setMinimumWidth(290)
        scroll.setMaximumWidth(320)
        # Sin scroll horizontal: el contenido se ajusta al ancho y los valores
        # de los sliders (a la derecha) nunca quedan recortados.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        cont = QWidget()
        col = QVBoxLayout(cont)
        col.setContentsMargins(6, 4, 12, 4)
        col.setSpacing(10)

        # Una card por máquina (rate prod/desb, tasa de falla).
        self._maq_box = QVBoxLayout()
        self._maq_box.setSpacing(10)
        col.addLayout(self._maq_box)

        # Globales.
        card_g = SectionCard(title="GLOBALES", object_name="CardSoft")
        gl = card_g.content_layout()
        gl.addLayout(self._fila_rango(("global", "tiempo_enfriado"),
                                      "Tiempo de enfriamiento", "h", 0.0, 24.0, 0.5, 1))
        gl.addLayout(self._fila_rango(("global", "tiempo_traslado_crc"),
                                      "Tiempo traslado CRC", "min", 0.0, 120.0, 1.0, 0))
        col.addWidget(card_g)

        # Selectores fijos.
        card_f = SectionCard(title="CONFIGURACIÓN FIJA", object_name="CardSoft")
        fl = card_f.content_layout()
        self.cb_sel = self._combo([(k, v.etiqueta) for k, v in ESTRATEGIAS_SELECCION.items()])
        self.cb_asig = self._combo([(k, v.etiqueta) for k, v in ESTRATEGIAS_ASIGNACION.items()])
        self.cb_gen = self._combo([(k, g.etiqueta) for k, g in GENERADORES_CAMBIOS.items()])
        self.cb_turnos_lam = self._combo(
            [(k, turnos_mod.PRESET_LABELS.get(k, k)) for k in turnos_mod.PRESETS])
        for cb in (self.cb_sel, self.cb_asig, self.cb_gen, self.cb_turnos_lam):
            cb.setVisible(False)
        self.sp_duracion = QSpinBox()
        self.sp_duracion.setRange(1, 120)
        fl.addLayout(self._fila_chips("Estrategia de rectificado", "sel", self.cb_sel))
        fl.addLayout(self._fila_chips("Estrategia de asignación", "asig", self.cb_asig))
        fl.addLayout(self._fila_chips("Generador de cambios", "gen", self.cb_gen))
        fl.addLayout(self._fila_widget("Duración de corrida (días)", self.sp_duracion))
        fl.addLayout(self._fila_chips("Turnos laminador", "tlam", self.cb_turnos_lam))
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

        self.btn_run = QPushButton("▶ Ejecutar Monte Carlo")
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
        self._sync_run_presets(self.sp_runs.value())
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
        cards.setSpacing(12)
        ncols_cards = 3
        for i, (clave, etiqueta, color) in enumerate(_KPI_DESTACADOS):
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
        # Permite que el combo se encoja y elida el texto largo en vez de forzar
        # el ancho del panel (los nombres de estrategia son largos).
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(12)
        cb.setMinimumWidth(0)
        cb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return cb

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

    def _fila_chips(self, label: str, key: str, combo: QComboBox) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(4)
        lab = QLabel(label)
        lab.setStyleSheet(f"color:{tema.FG2}; font-size:11px;")
        box.addWidget(lab)

        chips: List[Tuple[QPushButton, Any]] = []
        for i in range(combo.count()):
            txt = combo.itemText(i)
            data = combo.itemData(i)
            btn = QPushButton(txt)
            btn.setObjectName("McOptionChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _=False, c=combo, d=data: self._select_chip(c, d))
            box.addWidget(btn)
            chips.append((btn, data))

        self._chip_groups[key] = chips
        combo.currentIndexChanged.connect(lambda _=0, k=key: self._refresh_chips(k))
        self._refresh_chips(key)
        return box

    def _select_chip(self, combo: QComboBox, data: Any) -> None:
        idx = combo.findData(data)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _refresh_chips(self, key: str) -> None:
        group = self._chip_groups.get(key, [])
        if not group:
            return
        combo_map = {
            "sel": self.cb_sel,
            "asig": self.cb_asig,
            "gen": self.cb_gen,
            "tlam": self.cb_turnos_lam,
        }
        combo = combo_map.get(key)
        # Claves dinámicas tmaq_<nombre>
        if combo is None and key.startswith("tmaq_"):
            nombre = key[5:]
            t = self._turnos_maq_widgets.get(nombre)
            combo = t[0] if t else None
        if combo is None:
            return
        cur = combo.currentData()
        for btn, data in group:
            btn.setChecked(data == cur)

    def _sync_run_presets(self, value: int) -> None:
        for n, btn in self._run_preset_buttons:
            btn.setChecked(n == value)

    def _fila_turnos_maquina(self, nombre: str) -> QVBoxLayout:
        """Fila de turnos para una máquina: chips de preset + campo Personalizado."""
        opciones = [(k, turnos_mod.PRESET_LABELS.get(k, k)) for k in turnos_mod.PRESETS]
        # None = Personalizado
        opciones.append((None, "Personalizado"))
        cb_t = self._combo(opciones)
        cb_t.setVisible(False)

        le_custom = QLineEdit()
        le_custom.setPlaceholderText("ej: lv5|lv5|lv5|lv5|lv5|off|off")
        le_custom.setVisible(False)
        le_custom.setStyleSheet(f"font-size:10px; font-family:monospace; color:{tema.FG2};")

        box = QVBoxLayout()
        box.setSpacing(4)
        lab = QLabel("Turnos")
        lab.setStyleSheet(f"color:{tema.FG2}; font-size:11px;")
        box.addWidget(lab)

        key = f"tmaq_{nombre}"
        chips: List[Tuple[QPushButton, Any]] = []
        for data, txt in opciones:
            btn = QPushButton(txt)
            btn.setObjectName("McOptionChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            def _on_click(_, cb=cb_t, d=data, le=le_custom):
                idx = cb.findData(d)
                if idx >= 0:
                    cb.setCurrentIndex(idx)
                le.setVisible(d is None)
            btn.clicked.connect(_on_click)
            box.addWidget(btn)
            chips.append((btn, data))

        box.addWidget(le_custom)

        self._chip_groups[key] = chips
        cb_t.currentIndexChanged.connect(lambda _=0, k=key: self._refresh_chips(k))
        self._turnos_maq_widgets[nombre] = (cb_t, le_custom)
        self._refresh_chips(key)
        return box

    def _fila_slider(self, etiqueta: str, slider: _FloatSlider) -> QHBoxLayout:
        fila = QHBoxLayout()
        fila.setSpacing(6)
        cap = QLabel(etiqueta)
        cap.setMinimumWidth(32)
        cap_color = tema.RED if etiqueta == "Mín" else tema.GREEN
        cap.setStyleSheet(f"color:{cap_color}; font-size:9.5px;")
        fila.addWidget(cap, 0)
        fila.addWidget(slider, 1)
        return fila

    def _fila_rango(self, clave: Tuple[str, ...], label: str, unit: str,
                    maximo_inf: float, maximo: float, step: float,
                    decimals: int) -> QVBoxLayout:
        """Una entrada de rango: cabecera + dos sliders apilados (Mín / Máx).

        Stack vertical (no lado a lado) para que entre en el panel de 320px sin
        cortar el control de Máx. Los sliders se acoplan: Mín nunca supera a Máx
        ni viceversa (clamp del que se mueve, igual que el mockup HTML).
        """
        box = QVBoxLayout()
        box.setSpacing(3)
        cab = QHBoxLayout()
        lab = QLabel(label)
        u = QLabel(unit)
        u.setMinimumWidth(30)
        u.setObjectName("Muted")
        u.setStyleSheet(f"color:{tema.FG_DIM}; font-family:monospace; font-size:10px;")
        cab.addWidget(lab)
        cab.addStretch(1)
        cab.addWidget(u)
        box.addLayout(cab)

        smin = _FloatSlider(maximo, step, decimals, tema.RED)
        smax = _FloatSlider(maximo, step, decimals, tema.GREEN)
        box.addLayout(self._fila_slider("Mín", smin))
        box.addLayout(self._fila_slider("Máx", smax))

        # Acople Mín ≤ Máx (clamp del slider que se mueve).
        smin.slider.valueChanged.connect(
            lambda _=0: smin.slider.setValue(min(smin.slider.value(), smax.slider.value())))
        smax.slider.valueChanged.connect(
            lambda _=0: smax.slider.setValue(max(smax.slider.value(), smin.slider.value())))

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
        # Limpia widgets de turnos por máquina previos
        for key in [k for k in self._chip_groups if k.startswith("tmaq_")]:
            self._chip_groups.pop(key, None)
        self._turnos_maq_widgets.clear()

        for m in obtener_maquinas(self._cfg):
            nombre = m["nombre"]
            card = SectionCard(title=f"MÁQUINA · {nombre}", object_name="CardSoft")
            prio = str(m.get("prioridad", "")).lower()
            dot = tema.DASH_ORANGE if "desb" in prio else tema.DASH_ESTADO_DISPONIBLE
            if card.title_label is not None:
                card.title_label.setTextFormat(Qt.TextFormat.RichText)
                card.title_label.setText(
                    f'<span style="color:{dot};">●</span>&nbsp;&nbsp;MÁQUINA · {nombre}')
            cl = card.content_layout()
            cl.addLayout(self._fila_rango(("maq", nombre, "rate_prod"),
                                          "Rate producción", "mm/min", 0.0, 0.05, 0.0005, 4))
            cl.addLayout(self._fila_rango(("maq", nombre, "rate_desb"),
                                          "Rate desbaste", "mm/min", 0.0, 0.06, 0.0005, 4))
            cl.addLayout(self._fila_rango(("maq", nombre, "tasa_falla"),
                                          "Tasa de falla", "frac", 0.0, 0.5, 0.005, 3))
            cl.addLayout(self._fila_turnos_maquina(nombre))
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
        self._set_combo(self.cb_turnos_lam, fijos.get("turnos_laminador_preset"))
        self.sp_duracion.setValue(int(fijos.get("duracion_dias", 7)))

        r = mc["rangos"]
        self._set_rango(("global", "tiempo_enfriado"), r["tiempo_enfriado"])
        self._set_rango(("global", "tiempo_traslado_crc"), r["tiempo_traslado_crc"])
        for nombre, rr in r.get("maquinas", {}).items():
            for campo in ("rate_prod", "rate_desb", "tasa_falla"):
                self._set_rango(("maq", nombre, campo), rr[campo])

        # Turnos por máquina
        turnos_por_maq = fijos.get("turnos_por_maquina") or {}
        for nombre, widgets in self._turnos_maq_widgets.items():
            cb_t, le_custom = widgets
            val = turnos_por_maq.get(nombre, "24x7")
            idx = cb_t.findData(val)
            if idx >= 0:
                cb_t.setCurrentIndex(idx)
                le_custom.setVisible(False)
            else:
                cb_t.setCurrentIndex(cb_t.count() - 1)  # «Personalizado»
                le_custom.setText(val)
                le_custom.setVisible(True)
            self._refresh_chips(f"tmaq_{nombre}")

    def _set_combo(self, cb: QComboBox, clave: Optional[str]) -> None:
        idx = cb.findData(clave)
        if idx >= 0:
            cb.setCurrentIndex(idx)
        self._refresh_chips("sel")
        self._refresh_chips("asig")
        self._refresh_chips("gen")
        self._refresh_chips("tlam")

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

        turnos_por_maquina: Dict[str, str] = {}
        for nombre, (cb_t, le_custom) in self._turnos_maq_widgets.items():
            data = cb_t.currentData()
            if data is None:  # «Personalizado»
                val = le_custom.text().strip() or "24x7"
            else:
                val = data
            turnos_por_maquina[nombre] = val

        return {
            "runs": self.sp_runs.value(),
            "master_seed": (self.sp_seed.value() or None),
            "chunk": max(1, self.sp_runs.value() // 20),
            "fijos": {
                "estrategia_seleccion": self.cb_sel.currentData(),
                "estrategia_asignacion": self.cb_asig.currentData(),
                "generador": self.cb_gen.currentData(),
                "duracion_dias": self.sp_duracion.value(),
                "turnos_por_maquina": turnos_por_maquina,
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
                self._kpi_cards[clave].setText(_fmt_mc_kpi(clave, st["p50"], compact=True))
                self._kpi_sub[clave].setText(
                    f"P10 {_fmt_mc_kpi(clave, st['p10'], compact=True)} · "
                    f"P90 {_fmt_mc_kpi(clave, st['p90'], compact=True)}")
            self._hist[clave].set_values([float(r[clave]) for r in filas if clave in r])

        variables = sorted(self._resumen)
        self.tabla.setRowCount(len(variables))
        for i, var in enumerate(variables):
            st = self._resumen[var]
            celdas = [var,
                      _fmt_mc_kpi(var, st["mean"]),
                      _fmt_mc_kpi(var, st["std"]),
                      _fmt_mc_kpi(var, st["p10"]),
                      _fmt_mc_kpi(var, st["p50"]),
                      _fmt_mc_kpi(var, st["p90"])]
            for j, txt in enumerate(celdas):
                item = QTableWidgetItem(txt)
                if j > 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.tabla.setItem(i, j, item)
            self._ajustar_altura_tabla()
        self._set_export_enabled(True)

    def set_error(self, msg: str) -> None:
        self.set_running(False)
        self.lbl_progress.setText("Error")
        QMessageBox.critical(self, "Error", f"No se pudo ejecutar el Monte Carlo:\n{msg}")

    # ── Export ───────────────────────────────────────────────────────────────

    def _set_export_enabled(self, on: bool) -> None:
        self.btn_csv.setEnabled(on)
        self.btn_resumen.setEnabled(on)

    def _ajustar_altura_tabla(self) -> None:
        """Expande la tabla para mostrar todas las filas sin scroll interno."""
        header_h = self.tabla.horizontalHeader().height()
        frame = self.tabla.frameWidth() * 2
        filas_h = sum(self.tabla.rowHeight(i) for i in range(self.tabla.rowCount()))
        self.tabla.setFixedHeight(header_h + filas_h + frame)

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
