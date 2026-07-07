"""Panel Dashboard para la GUI Qt — nativo (sin Matplotlib), 1 a 1 con html_ref.

Reemplaza el antiguo dashboard de Matplotlib embebido por un grid 2×2 de
:class:`DashboardCard` con widgets dibujados con QPainter
(``gui_qt/widgets/dashboard_charts_qt``). Las cards se muestran **siempre**
(también sin simular: vacías, con su título y leyenda) y ``render(taller)``
sólo les pasa datos. Las series salen de ``gui_qt.dashboard_data`` (que a su vez
usa ``modelos.kpis.calcular_kpis``).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from config import tema
from modelos.enums import EstadoCilindro
from gui_qt.dashboard_data import extraer_datos_dashboard
from gui_qt.widgets.dashboard_card_qt import DashboardCard
from gui_qt.widgets.dashboard_charts_qt import (BufferChart, GanttChart,
                                                GroupedBarChart,
                                                StackedAreaChart)

_EST_BAJA = EstadoCilindro.BAJA.value
_EST_DISP = EstadoCilindro.DISPONIBLE.value
_EST_CRC = EstadoCilindro.CRC.value


class DashboardPanel(QWidget):
    """Dashboard nativo: evolución de estados, buffer, utilización y Gantt."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._cursor_tiempos = []

        # Estado del filtro por jaula (0 = Todas) y del toggle de bajas.
        self._data = None
        self._jaula_sel = 0
        self._ocultar_bajas = False

        # Barra de filtro por jaula (chips Todas / J1..Jn), arriba de las cards.
        # Afecta la evolución de estados y el buffer (las otras dos cards son
        # por máquina / globales). Los chips se reconstruyen en render() según
        # la cantidad de jaulas del taller.
        self._filter_bar = QHBoxLayout()
        self._filter_bar.setContentsMargins(2, 0, 2, 0)
        self._filter_bar.setSpacing(6)
        lbl = QLabel("JAULA")
        lbl.setObjectName("BoardHeader")
        lbl.setProperty("muted", "true")
        self._filter_bar.addWidget(lbl)
        self._jaula_group = QButtonGroup(self)
        self._jaula_group.setExclusive(True)
        self._jaula_group.buttonClicked.connect(self._on_jaula_clicked)
        self._filter_bar.addStretch(1)
        self._root.addLayout(self._filter_bar)
        self._construir_chips_jaula([])

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._grid_host = QWidget()
        host_box = QVBoxLayout(self._grid_host)
        host_box.setContentsMargins(2, 2, 2, 2)
        host_box.setSpacing(0)
        self.grid = QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(14)
        self.grid.setVerticalSpacing(14)
        host_box.addLayout(self.grid)
        host_box.addStretch(1)  # cards al tope, el sobrante queda debajo (como el HTML).
        self.scroll_area.setWidget(self._grid_host)
        self._root.addWidget(self.scroll_area)

        # Gráficos (se crean una vez; render() les pasa datos).
        self.chart_estados = StackedAreaChart()
        self.chart_estados.setMaximumHeight(300)
        self.chart_buffer = BufferChart()
        self.chart_buffer.setMaximumHeight(300)
        self.chart_util = GroupedBarChart()
        self.chart_gantt = GanttChart()

        self._build_cards()
        # Arranca vacío: las cards quedan visibles para anticipar qué se mostrará.

    # ── Construcción de las tarjetas ────────────────────────────────────────
    def _build_cards(self) -> None:
        self.card_estados = DashboardCard("Evolución temporal de estados")
        self.btn_ocultar_bajas = QPushButton("Ocultar bajas")
        self.btn_ocultar_bajas.setObjectName("PlaybackButton")
        self.btn_ocultar_bajas.setCheckable(True)
        self.btn_ocultar_bajas.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_ocultar_bajas.toggled.connect(self._on_ocultar_bajas)
        self.card_estados.add_header_action(self.btn_ocultar_bajas)
        self.card_estados.add_content(self.chart_estados)

        self.card_buffer = DashboardCard("Buffer de seguridad global")
        self.card_buffer.add_content(self.chart_buffer)
        self.card_buffer.set_legend([
            (tema.DASH_GREEN, "Disp + CRC"),
            (tema.DASH_DISP, "Disponible"),
            (tema.DASH_ORANGE, "CRC"),
        ])

        self.card_util = DashboardCard("Utilización de máquinas — Disponible vs Neta")
        self.card_util.add_content(self.chart_util)
        self.card_util.set_legend([
            (tema.DASH_GREEN, "Disponible"),
            (tema.DASH_PURPLE, "Neta"),
        ])

        self.card_gantt = DashboardCard("Cronograma de rectificado")
        self.card_gantt.add_content(self.chart_gantt)
        self.card_gantt.set_legend([
            (tema.TIPO_RECT_COLORS_DASH["produccion"], "Producción"),
            (tema.TIPO_RECT_COLORS_DASH["desbaste"], "Desbaste"),
            (tema.DASH_PARADA, "Parada (turno)"),
            (tema.DASH_FALLA, "Falla"),
        ])

        self.grid.addWidget(self.card_estados, 0, 0)
        self.grid.addWidget(self.card_buffer, 0, 1)
        self.grid.addWidget(self.card_util, 1, 0)
        self.grid.addWidget(self.card_gantt, 1, 1)
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

    # ── Filtro por jaula ─────────────────────────────────────────────────────
    def _construir_chips_jaula(self, jaulas: list[int]) -> None:
        """(Re)construye los chips Todas / J1..Jn según el taller actual."""
        for b in list(self._jaula_group.buttons()):
            self._jaula_group.removeButton(b)
            self._filter_bar.removeWidget(b)
            b.deleteLater()
        # Insertar antes del stretch final (índice = count - 1).
        pos = self._filter_bar.count() - 1
        for jid, texto in [(0, "Todas")] + [(j, f"J{j}") for j in jaulas]:
            chip = QPushButton(texto)
            chip.setObjectName("PlaybackSpeedButton")
            chip.setCheckable(True)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setChecked(jid == self._jaula_sel)
            self._jaula_group.addButton(chip, jid)
            self._filter_bar.insertWidget(pos, chip)
            pos += 1

    def _on_jaula_clicked(self, *_args) -> None:
        self._jaula_sel = self._jaula_group.checkedId()
        self._render_estados()
        self._render_buffer()

    def _on_ocultar_bajas(self, checked: bool) -> None:
        self._ocultar_bajas = checked
        self.btn_ocultar_bajas.setText("Mostrar bajas" if checked else "Ocultar bajas")
        self._render_estados()

    def _render_estados(self) -> None:
        """Dibuja la evolución de estados para la jaula elegida (0 = global)."""
        d = self._data
        if d is None:
            self.chart_estados.set_data([], [], {}, {})
            return
        series = (d.series_estado if self._jaula_sel == 0
                  else d.series_estado_por_jaula.get(self._jaula_sel, {}))
        estados = [e for e in d.estados if not (self._ocultar_bajas and e == _EST_BAJA)]
        self.chart_estados.set_data(d.tiempos, estados, series, d.colores_estado)

    def _render_buffer(self) -> None:
        """Dibuja el buffer Disp/CRC para la jaula elegida (0 = global)."""
        d = self._data
        if d is None:
            self.chart_buffer.set_data([], [], [], [])
            return
        if self._jaula_sel == 0:
            disp, crc = d.disponibles, d.crc
        else:
            sj = d.series_estado_por_jaula.get(self._jaula_sel, {})
            n = len(d.tiempos)
            disp = sj.get(_EST_DISP, [0] * n)
            crc = sj.get(_EST_CRC, [0] * n)
        buffer = [a + b for a, b in zip(disp, crc)]
        self.chart_buffer.set_data(d.tiempos, disp, crc, buffer)

    # ── API consumida por MainWindow ────────────────────────────────────────
    def render(self, taller) -> None:
        """Reconstruye el dashboard para el taller actual (o lo deja vacío)."""
        if taller is None or not getattr(taller, "snapshots", None):
            self._set_empty()
            return

        data = extraer_datos_dashboard(taller)
        self._data = data
        self._cursor_tiempos = list(data.tiempos)
        # Reconstruye los chips por si cambió la cantidad de jaulas; si la
        # selección previa ya no existe, vuelve a "Todas".
        if self._jaula_sel not in data.jaulas and self._jaula_sel != 0:
            self._jaula_sel = 0
        self._construir_chips_jaula(data.jaulas)
        self._render_estados()
        self._render_buffer()
        self.chart_util.set_data(data.maquinas, data.util_disponible, data.util_neta)
        self.chart_gantt.set_data(
            data.maquinas, data.gantt, data.paradas_turno,
            data.t0, data.t1, tema.TIPO_RECT_COLORS_DASH, data.tramos_falla,
        )
        self.set_cursor(0, len(data.tiempos))

    def _set_empty(self) -> None:
        """Vacía los gráficos dejando las cards (título + leyenda + área vacía)."""
        self._data = None
        self._cursor_tiempos = []
        self.chart_estados.set_data([], [], {}, {})
        self.chart_buffer.set_data([], [], [], [])
        self.chart_util.set_data([], {}, {})
        self.chart_gantt.set_data([], {}, {}, None, None, {})

    def set_cursor(self, idx: int, total: int) -> None:
        """Marca el snapshot actual con el cursor del replay en los gráficos temporales."""
        if not self._cursor_tiempos:
            frac: float | None = 0.0 if total <= 1 else max(0.0, min(1.0, idx / (total - 1)))
        elif len(self._cursor_tiempos) <= 1:
            frac: float | None = 0.0
        else:
            i = max(0, min(int(idx), len(self._cursor_tiempos) - 1))
            t0 = self._cursor_tiempos[0]
            t1 = self._cursor_tiempos[-1]
            t = self._cursor_tiempos[i]
            span = (t1 - t0).total_seconds()
            frac = 0.0 if span <= 0 else max(0.0, min(1.0, (t - t0).total_seconds() / span))
        self.chart_estados.set_cursor_frac(frac)
        self.chart_buffer.set_cursor_frac(frac)
        self.chart_gantt.set_cursor_frac(frac)
