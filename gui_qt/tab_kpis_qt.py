"""Pestaña KPIs para la GUI Qt (nativa, 1 a 1 con html_ref)."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from config import tema as tk_theme
from gui_qt.format_utils import formato_horizonte
from gui_qt.widgets import SummaryCard, UtilCard
from modelos.kpis import calcular_kpis


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    rgb = [round(a[i] + (b[i] - a[i]) * max(0.0, min(1.0, t))) for i in range(3)]
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _color_util(pct: float) -> str:
    t = max(0.0, min(1.0, pct / 100.0))
    if t < 0.5:
        return _mix(tk_theme.RED, tk_theme.YELLOW, t / 0.5)
    return _mix(tk_theme.YELLOW, tk_theme.GREEN, (t - 0.5) / 0.5)


def _pretty_label(key: str) -> str:
    base = tk_theme.KPI_META_BASE.get(key, {})
    return str(base.get("label", key.replace("_", " ").title()))


def _format_value(key: str, value: Any) -> str:
    if isinstance(value, float):
        if key == "diametro_promedio_mm":
            return f"{value:.1f} mm"
        if key == "desgaste_medio_mm":
            return f"{value:.2f} mm"
        if key == "horizonte_simulacion_h":
            return formato_horizonte(value)
        return f"{value:.2f}"
    return str(value)


def _kpi_color(key: str, value: Any) -> str:
    if key == "activos":
        return tk_theme.KPI_COLOR_OK
    if key == "bajas":
        return tk_theme.KPI_COLOR_ALERT if float(value or 0) > 0 else tk_theme.KPI_COLOR_OK
    if key == "alertas_criticas":
        return tk_theme.KPI_COLOR_ALERT if float(value or 0) > 0 else tk_theme.KPI_COLOR_OK
    if key == "cambios_programados":
        return tk_theme.KPI_COLOR_CAMBIOS
    if key == "rectificados_realizados":
        return tk_theme.KPI_COLOR_RECTIFICADOS
    if key == "horizonte_simulacion_h":
        return tk_theme.KPI_COLOR_HORIZONTE
    if key == "diametro_promedio_mm":
        return tk_theme.KPI_COLOR_DIAMETRO
    if key == "desgaste_medio_mm":
        return tk_theme.KPI_COLOR_DESGASTE
    if key == "reposicion_entregados":
        return tk_theme.KPI_COLOR_OK
    if key == "reposicion_pendientes":
        return tk_theme.KPI_COLOR_ALERT if float(value or 0) > 0 else tk_theme.KPI_COLOR_OK
    return tk_theme.KPI_TEXT_DEFAULT


class KpisPanel(QWidget):
    """Panel KPIs nativo, fiel al HTML y alimentado por calcular_kpis()."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)

        self.banner = QLabel("Se mostrarán datos una vez corrida la simulación")
        self.banner.setObjectName("DashboardBanner")
        self.banner.setStyleSheet("padding: 10px 0 12px 0;")
        self.root.addWidget(self.banner)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; }")
        self.root.addWidget(self.scroll_area)

        self.content = QWidget()
        self.content.setObjectName("KpiScrollContent")
        self.content.setStyleSheet(
            "QWidget#KpiScrollContent { background: transparent; }"
        )
        self.scroll_area.setWidget(self.content)

        self.content_col = QVBoxLayout(self.content)
        self.content_col.setContentsMargins(2, 2, 2, 2)
        self.content_col.setSpacing(0)

        self.general_grid = QGridLayout()
        self.general_grid.setHorizontalSpacing(12)
        self.general_grid.setVerticalSpacing(12)
        self.content_col.addLayout(self.general_grid)

        self.title_disp = QLabel("UTILIZACIÓN DISPONIBLE")
        self.title_disp.setStyleSheet(
            f"margin-top:22px; background:transparent; color:{tk_theme.KPI_SECTION_TITLE}; "
            "font-family:'Space Grotesk'; font-size:13px; font-weight:700; "
            "letter-spacing:0.04em;"
        )
        self.content_col.addWidget(self.title_disp)

        self.util_disp_grid = QGridLayout()
        self.util_disp_grid.setHorizontalSpacing(12)
        self.util_disp_grid.setVerticalSpacing(12)
        self.util_disp_grid.setContentsMargins(0, 10, 0, 0)
        self.content_col.addLayout(self.util_disp_grid)

        self.title_neta = QLabel("UTILIZACIÓN NETA")
        self.title_neta.setStyleSheet(
            f"margin-top:22px; background:transparent; color:{tk_theme.KPI_SECTION_TITLE}; "
            "font-family:'Space Grotesk'; font-size:13px; font-weight:700; "
            "letter-spacing:0.04em;"
        )
        self.content_col.addWidget(self.title_neta)

        self.util_neta_grid = QGridLayout()
        self.util_neta_grid.setHorizontalSpacing(12)
        self.util_neta_grid.setVerticalSpacing(12)
        self.util_neta_grid.setContentsMargins(0, 10, 0, 0)
        self.content_col.addLayout(self.util_neta_grid)

        # Empuja el contenido hacia arriba: las cards quedan a su altura natural
        # (como el grid del HTML), sin estirarse verticalmente.
        self.content_col.addStretch(1)

        self._set_empty(None)

    def _clear_layout(self, layout: QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _metric_keys_from_model(self, taller) -> list[str]:
        if taller is not None:
            k = calcular_kpis(taller)
            metric_order = k.get("metric_order")
            if isinstance(metric_order, list) and metric_order:
                return [str(x) for x in metric_order]
            return [
                key for key, val in k.items()
                if not isinstance(val, dict)
            ]
        # Fallback only when there is no model instance yet.
        return [str(k) for k in tk_theme.KPI_META_BASE.keys()]

    def _set_empty(self, taller) -> None:
        self._clear_layout(self.general_grid)
        self._clear_layout(self.util_disp_grid)
        self._clear_layout(self.util_neta_grid)

        self.banner.setVisible(False)
        self.scroll_area.setVisible(True)

        for col in range(3):
            self.general_grid.setColumnStretch(col, 1)
            self.util_disp_grid.setColumnStretch(col, 1)
            self.util_neta_grid.setColumnStretch(col, 1)

        metric_keys = self._metric_keys_from_model(taller)
        for idx, key in enumerate(metric_keys):
            r, c = divmod(idx, 3)
            self.general_grid.addWidget(
                SummaryCard(_pretty_label(key), "", _kpi_color(key, 0)),
                r,
                c,
            )

        util_names = []
        if taller is not None:
            maq_dict = getattr(taller, "maquinas", {})
            if isinstance(maq_dict, dict):
                util_names = list(maq_dict.keys())
        if not util_names:
            util_names = ["", "", ""]

        for idx, name in enumerate(util_names):
            r, c = divmod(idx, 3)
            self.util_disp_grid.addWidget(UtilCard(name, None, None), r, c)

        for idx, name in enumerate(util_names):
            r, c = divmod(idx, 3)
            self.util_neta_grid.addWidget(UtilCard(name, None, None), r, c)

    def render(self, taller) -> None:
        if taller is None or not getattr(taller, "snapshots", None):
            self._set_empty(taller)
            return

        self._clear_layout(self.general_grid)
        self._clear_layout(self.util_disp_grid)
        self._clear_layout(self.util_neta_grid)

        self.banner.setVisible(False)
        self.scroll_area.setVisible(True)

        k = calcular_kpis(taller)

        # Mostrar TODOS los KPIs escalares que entrega calcular_kpis().
        metric_order = k.get("metric_order")
        if isinstance(metric_order, list) and metric_order:
            metric_keys = [str(x) for x in metric_order]
        else:
            metric_keys = [
                key for key, val in k.items()
                if not isinstance(val, dict)
            ]
        metric_meta = k.get("metric_meta", {})
        for col in range(3):
            self.general_grid.setColumnStretch(col, 1)
        for idx, key in enumerate(metric_keys):
            meta = metric_meta.get(key, {}) if isinstance(metric_meta, dict) else {}
            label = str(meta.get("label", _pretty_label(key)))
            value = _format_value(key, k[key])
            color = _kpi_color(key, k[key])
            r, c = divmod(idx, 3)
            self.general_grid.addWidget(SummaryCard(label, value, color), r, c)

        util_disp = k.get("utilizacion_maquinas_pct", {})
        util_neta = k.get("utilizacion_neta_pct", {})

        for col in range(3):
            self.util_disp_grid.setColumnStretch(col, 1)
            self.util_neta_grid.setColumnStretch(col, 1)

        for idx, (name, pct) in enumerate(util_disp.items()):
            color = _color_util(float(pct))
            r, c = divmod(idx, 3)
            self.util_disp_grid.addWidget(UtilCard(name, float(pct), color), r, c)

        for idx, (name, pct) in enumerate(util_neta.items()):
            color = _color_util(float(pct))
            r, c = divmod(idx, 3)
            self.util_neta_grid.addWidget(UtilCard(name, float(pct), color), r, c)
