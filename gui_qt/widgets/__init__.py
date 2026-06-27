"""Widgets reutilizables de la GUI Qt."""

from gui_qt.widgets.config_table_editors_qt import make_config_cell_input, make_priority_combo
from gui_qt.widgets.flow_card_qt import FlowCard
from gui_qt.widgets.labeled_rows_qt import LabeledFieldRow
from gui_qt.widgets.section_card_qt import SectionCard
from gui_qt.widgets.status_bar_qt import StatusBarWidget
from gui_qt.widgets.styled_table_qt import StyledTableWidget
from gui_qt.widgets.tabs_corner_qt import TabsCornerInfoWidget

__all__ = [
    "FlowCard",
    "LabeledFieldRow",
    "SectionCard",
    "StatusBarWidget",
    "StyledTableWidget",
    "TabsCornerInfoWidget",
    "make_config_cell_input",
    "make_priority_combo",
]
