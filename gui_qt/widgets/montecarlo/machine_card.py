"""Card de configuración de una máquina para el barrido Monte Carlo."""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

from config import tema
from gui_qt.widgets.section_card_qt import SectionCard
from gui_qt.widgets.montecarlo.chip_selector import ChipSelector
from gui_qt.widgets.montecarlo.range_row import RangeRow
from gui_qt.widgets.montecarlo.shift_selector import ShiftSelector

# (campo, etiqueta, unidad, máximo, paso, decimales) de los rangos por máquina.
_CAMPOS_RANGO = (
    ("rate_prod", "Rate producción", "mm/min", 0.05, 0.0005, 4),
    ("rate_desb", "Rate desbaste", "mm/min", 0.06, 0.0005, 4),
    ("tasa_falla", "Tasa de falla", "frac", 0.5, 0.005, 3),
)


class MachineCard(SectionCard):
    """Una máquina: rangos (rate prod/desb, tasa de falla), prioridad y turnos.

    Encapsula todo el estado por-máquina que antes vivía disperso en el panel
    (rangos, chips de prioridad y turnos). Expone getters/setters simples para
    que el panel arme/lea la spec sin conocer los widgets internos.
    """

    def __init__(self, nombre: str, prioridad_inicial: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, title=f"MÁQUINA · {nombre}", object_name="CardSoft")
        self.nombre = nombre
        if self.title_label is not None:
            self.title_label.setTextFormat(Qt.TextFormat.RichText)

        cl = self.content_layout()
        self._rangos: Dict[str, RangeRow] = {}
        for campo, label, unit, mx, step, dec in _CAMPOS_RANGO:
            rr = RangeRow(label, unit, mx, step, dec)
            self._rangos[campo] = rr
            cl.addWidget(rr)

        self._prio = ChipSelector(
            "Prioridad", [("produccion", "Producción"), ("desbaste", "Desbaste")],
            orientation="h", chip_object_name="McOptionChip")
        self._prio.changed.connect(self._recolorear_titulo)
        cl.addWidget(self._prio)

        self._turnos = ShiftSelector()
        cl.addWidget(self._turnos)

        # Prioridad inicial: la de la máquina en la config (el fijo del spec, si
        # existe, la pisa vía set_prioridad desde el panel).
        prio = "desbaste" if "desb" in str(prioridad_inicial).lower() else "produccion"
        self.set_prioridad(prio)
        self._recolorear_titulo()

    def _recolorear_titulo(self) -> None:
        """Sincroniza el punto de color del título con la prioridad elegida."""
        if self.title_label is None:
            return
        dot = (tema.DASH_ORANGE if self._prio.current_data() == "desbaste"
               else tema.DASH_ESTADO_DISPONIBLE)
        self.title_label.setText(
            f'<span style="color:{dot};">●</span>&nbsp;&nbsp;MÁQUINA · {self.nombre}')

    # ── Rangos ───────────────────────────────────────────────────────────────
    def campos_rango(self) -> List[str]:
        return list(self._rangos)

    def rangos(self) -> Dict[str, List[float]]:
        return {campo: list(rr.values()) for campo, rr in self._rangos.items()}

    def set_rango(self, campo: str, par) -> None:
        rr = self._rangos.get(campo)
        if rr is not None:
            rr.set_values(par)

    # ── Prioridad ────────────────────────────────────────────────────────────
    def prioridad(self) -> Optional[str]:
        d = self._prio.current_data()
        return d if d in ("produccion", "desbaste") else None

    def set_prioridad(self, prio: Optional[str]) -> None:
        if prio in ("produccion", "desbaste"):
            self._prio.set_current_data(prio)

    # ── Turnos ───────────────────────────────────────────────────────────────
    def turnos(self) -> str:
        return self._turnos.value()

    def set_turnos(self, val: str) -> None:
        self._turnos.set_value(val)
