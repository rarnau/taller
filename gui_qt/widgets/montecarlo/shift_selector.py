"""Selector de turnos por máquina: chips de preset + grilla «Personalizada»."""

from __future__ import annotations

from typing import Any, List, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from config import tema
from modelos import turnos as turnos_mod


class ShiftSelector(QWidget):
    """Chips de preset de turnos + opción «Personalizado» (editor 7×3).

    «Personalizado» abre el mismo editor que la pestaña Configuración
    (``TurnosDialog``, importado en forma diferida para evitar ciclos) y guarda
    la grilla elegida en formato compacto. ``value()`` devuelve la clave del
    preset o el string compacto de la grilla; ``set_value()`` hace la inversa.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        opciones: List[Tuple[Any, str]] = [
            (k, turnos_mod.PRESET_LABELS.get(k, k)) for k in turnos_mod.PRESETS
        ]
        opciones.append((None, "Personalizado"))  # None = Personalizado

        self._combo = QComboBox()
        for data, texto in opciones:
            self._combo.addItem(texto, data)
        self._combo.setVisible(False)
        self._custom: str = ""  # grilla personalizada en formato compacto

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        lab = QLabel("Turnos")
        lab.setStyleSheet(f"color:{tema.FG2}; font-size:11px;")
        box.addWidget(lab)

        self._chips: List[Tuple[QPushButton, Any]] = []
        for data, texto in opciones:
            btn = QPushButton(texto)
            btn.setObjectName("McOptionChip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _=False, d=data: self._on_chip(d))
            box.addWidget(btn)
            self._chips.append((btn, data))

        self._btn_editar = QPushButton("✎ Editar grilla…")
        self._btn_editar.setObjectName("PlaybackButton")
        self._btn_editar.setVisible(False)
        self._btn_editar.clicked.connect(self._editar)
        box.addWidget(self._btn_editar)

        self._lbl_resumen = QLabel("")
        self._lbl_resumen.setVisible(False)
        self._lbl_resumen.setWordWrap(True)
        self._lbl_resumen.setStyleSheet(f"font-size:10px; color:{tema.FG2};")
        box.addWidget(self._lbl_resumen)

        self._combo.currentIndexChanged.connect(self._refresh_chips)
        self._refresh_chips()

    def _on_chip(self, data: Any) -> None:
        idx = self._combo.findData(data)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._mostrar_custom(data is None)
        # Elegir «Personalizado» sin grilla previa abre el editor directo.
        if data is None and not self._custom:
            self._editar()

    def _mostrar_custom(self, visible: bool) -> None:
        self._btn_editar.setVisible(visible)
        self._lbl_resumen.setVisible(visible and bool(self._custom))

    def _editar(self) -> None:
        # Import diferido: TurnosDialog vive en gui_qt.config_qt, evita el ciclo
        # de importación al cargar el paquete de widgets.
        from gui_qt.config_qt import TurnosDialog

        actual = None
        if self._custom:
            try:
                actual = turnos_mod.parse_compacto(self._custom)
            except ValueError:
                actual = None
        ok, turnos = TurnosDialog.edit(actual, self)
        if not ok or turnos is None:
            return
        self._custom = turnos_mod.format_compacto(turnos)
        self._refrescar_resumen()

    def _refrescar_resumen(self) -> None:
        if not self._custom:
            return
        try:
            self._lbl_resumen.setText(
                turnos_mod.resumen(turnos_mod.parse_compacto(self._custom)))
            self._lbl_resumen.setVisible(True)
        except ValueError:
            self._lbl_resumen.setText("")

    def _refresh_chips(self, *_: Any) -> None:
        cur = self._combo.currentData()
        for btn, data in self._chips:
            btn.setChecked(data == cur)

    def value(self) -> str:
        data = self._combo.currentData()
        if data is None:  # «Personalizado»: grilla del pop-up, en compacto
            return self._custom or "24x7"
        return data

    def set_value(self, val: str) -> None:
        idx = self._combo.findData(val)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
            self._mostrar_custom(False)
        else:
            self._combo.setCurrentIndex(self._combo.count() - 1)  # «Personalizado»
            self._custom = val
            self._mostrar_custom(True)
            self._refrescar_resumen()
        self._refresh_chips()
