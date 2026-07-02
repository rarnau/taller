"""Selector de opción por *chips* (botones toggle) respaldado por un combo oculto."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import tema

_Opciones = Sequence[Tuple[Any, str]]


class ChipSelector(QWidget):
    """Fila de chips exclusivos sobre un ``QComboBox`` oculto (fuente de verdad).

    El combo mantiene la semántica de ``findData``/``currentData`` y emite
    ``changed`` cuando cambia la selección (por chip o programáticamente). El
    resto del panel interactúa vía ``current_data()``/``set_current_data()``.
    """

    changed = Signal()

    def __init__(self, label: Optional[str], opciones: _Opciones, *,
                 orientation: str = "v", chip_object_name: Optional[str] = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._combo = QComboBox()
        for data, texto in opciones:
            self._combo.addItem(texto, data)
        self._combo.setVisible(False)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        if label:
            lab = QLabel(label)
            lab.setStyleSheet(f"color:{tema.FG2}; font-size:11px;")
            box.addWidget(lab)

        contenedor = QHBoxLayout() if orientation == "h" else None
        if contenedor is not None:
            contenedor.setSpacing(6)

        self._chips: List[Tuple[QPushButton, Any]] = []
        for data, texto in opciones:
            btn = QPushButton(texto)
            if chip_object_name:
                btn.setObjectName(chip_object_name)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _=False, d=data: self.set_current_data(d))
            if contenedor is not None:
                contenedor.addWidget(btn)
            else:
                box.addWidget(btn)
            self._chips.append((btn, data))
        if contenedor is not None:
            box.addLayout(contenedor)

        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        self._refresh()

    def _on_combo_changed(self, *_: Any) -> None:
        self._refresh()
        self.changed.emit()

    def current_data(self) -> Any:
        return self._combo.currentData()

    def set_current_data(self, data: Any) -> None:
        idx = self._combo.findData(data)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)

    def _refresh(self) -> None:
        cur = self._combo.currentData()
        for btn, data in self._chips:
            btn.setChecked(data == cur)
