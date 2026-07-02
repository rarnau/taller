"""Sub-widgets aislados del panel Monte Carlo.

Se importan directamente desde ``gui_qt.widgets.montecarlo`` (no se re-exportan
en ``gui_qt.widgets.__init__`` a propósito: ``ShiftSelector`` depende —de forma
diferida— de ``gui_qt.config_qt``, que a su vez importa ``gui_qt.widgets``, así
que mantener este paquete fuera del ``__init__`` del padre evita el ciclo).
"""

from gui_qt.widgets.montecarlo.chip_selector import ChipSelector
from gui_qt.widgets.montecarlo.float_slider import FloatSlider
from gui_qt.widgets.montecarlo.formatting import KPI_DESTACADOS, fmt_mc_kpi
from gui_qt.widgets.montecarlo.histogram import HistogramWidget
from gui_qt.widgets.montecarlo.machine_card import MachineCard
from gui_qt.widgets.montecarlo.range_row import RangeRow
from gui_qt.widgets.montecarlo.results_view import ResultsView
from gui_qt.widgets.montecarlo.shift_selector import ShiftSelector

__all__ = [
    "ChipSelector",
    "FloatSlider",
    "HistogramWidget",
    "KPI_DESTACADOS",
    "MachineCard",
    "RangeRow",
    "ResultsView",
    "ShiftSelector",
    "fmt_mc_kpi",
]
