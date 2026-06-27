"""Widget reutilizable para el bloque FLUJO del sidebar."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from gui_qt.ui_constants_qt import FLOW_CARD_MARGIN, FLOW_CARD_SPACING


class FlowCard(QFrame):
    """Tarjeta de flujo con 3 pasos y contador por paso."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("FlowCard")

        col = QVBoxLayout(self)
        col.setContentsMargins(FLOW_CARD_MARGIN, FLOW_CARD_MARGIN, FLOW_CARD_MARGIN, FLOW_CARD_MARGIN)
        col.setSpacing(FLOW_CARD_SPACING)

        title = QLabel("FLUJO")
        title.setObjectName("FlowTitle")
        col.addWidget(title)

        self.dot_flow_inv = QLabel("●")
        self.dot_flow_inv.setObjectName("FlowDotOff")
        self.lbl_flow_inv = QLabel("Inventario")
        self.lbl_flow_inv.setObjectName("FlowLabelOff")
        self.lbl_flow_inv_count = QLabel("0")
        self.lbl_flow_inv_count.setObjectName("FlowCountOff")
        self.lbl_flow_inv_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        col.addLayout(self._build_row(self.dot_flow_inv, self.lbl_flow_inv, self.lbl_flow_inv_count))

        self.dot_flow_gen = QLabel("●")
        self.dot_flow_gen.setObjectName("FlowDotOff")
        self.lbl_flow_gen = QLabel("Generacion")
        self.lbl_flow_gen.setObjectName("FlowLabelOff")
        self.lbl_flow_gen_count = QLabel("0")
        self.lbl_flow_gen_count.setObjectName("FlowCountOff")
        self.lbl_flow_gen_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        col.addLayout(self._build_row(self.dot_flow_gen, self.lbl_flow_gen, self.lbl_flow_gen_count))

        self.dot_flow_sim = QLabel("●")
        self.dot_flow_sim.setObjectName("FlowDotOff")
        self.lbl_flow_sim = QLabel("Simulacion")
        self.lbl_flow_sim.setObjectName("FlowLabelOff")
        self.lbl_flow_sim_count = QLabel("0")
        self.lbl_flow_sim_count.setObjectName("FlowCountOff")
        self.lbl_flow_sim_count.setAlignment(Qt.AlignmentFlag.AlignRight)
        col.addLayout(self._build_row(self.dot_flow_sim, self.lbl_flow_sim, self.lbl_flow_sim_count))

    def _build_row(self, dot: QLabel, label: QLabel, count: QLabel) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(dot)
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(count)
        return row

    def set_counts(self, inventario: int | None = None, generacion: int | None = None, simulacion: int | None = None) -> None:
        if inventario is not None:
            self.lbl_flow_inv_count.setText(str(inventario))
        if generacion is not None:
            self.lbl_flow_gen_count.setText(str(generacion))
        if simulacion is not None:
            self.lbl_flow_sim_count.setText(str(simulacion))

    def apply_state(self, inventario: bool, generacion: bool, simulacion: bool) -> None:
        self.dot_flow_inv.setObjectName("FlowDotOn" if inventario else "FlowDotOff")
        self.dot_flow_gen.setObjectName("FlowDotOn" if generacion else "FlowDotOff")
        self.dot_flow_sim.setObjectName("FlowDotOn" if simulacion else "FlowDotOff")

        self.lbl_flow_inv.setObjectName("FlowLabelOn" if inventario else "FlowLabelOff")
        self.lbl_flow_gen.setObjectName("FlowLabelOn" if generacion else "FlowLabelOff")
        self.lbl_flow_sim.setObjectName("FlowLabelOn" if simulacion else "FlowLabelOff")

        self.lbl_flow_inv_count.setObjectName("FlowCountOn" if inventario else "FlowCountOff")
        self.lbl_flow_gen_count.setObjectName("FlowCountOn" if generacion else "FlowCountOff")
        self.lbl_flow_sim_count.setObjectName("FlowCountOn" if simulacion else "FlowCountOff")

        for w in (
            self.dot_flow_inv,
            self.dot_flow_gen,
            self.dot_flow_sim,
            self.lbl_flow_inv,
            self.lbl_flow_gen,
            self.lbl_flow_sim,
            self.lbl_flow_inv_count,
            self.lbl_flow_gen_count,
            self.lbl_flow_sim_count,
        ):
            w.style().unpolish(w)
            w.style().polish(w)
