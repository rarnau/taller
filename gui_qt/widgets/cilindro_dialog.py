"""Diálogo de alta/edición de un cilindro del stock inicial.

Cáscara fina sobre ``nucleo.stock.validar_fila_stock``: los campos cubren el
contrato completo de la hoja ``Stock_Inicial`` (incluye los que la tabla del
Inventario no muestra) y toda la regla de validación vive en la función pura.
Patrón de uso estático como ``TurnosDialog.edit`` (gui_qt/config_qt.py).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

import pandas as pd
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from config.persistencia import obtener_config_global
from modelos.enums import EstadoCilindro, TipoRectificado
from nucleo.stock import (
    COL_DIAMETRO,
    COL_ESTADO,
    COL_ID,
    COL_JAULA,
    COL_MM,
    COL_PERFIL,
    COL_POSICION,
    COL_TIPO,
    validar_fila_stock,
)

_SIN_VALOR = "—"
_ESTADOS_CON_PASE = (EstadoCilindro.A_RECTIFICAR.value, EstadoCilindro.RECTIFICANDO.value)
_ESTADOS_CON_POSICION = (EstadoCilindro.TRABAJANDO.value, EstadoCilindro.CRC.value)


def _valor_o_none(valor: Any) -> Any:
    """Traduce NaN/'' (celda vacía del DataFrame) a None."""
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return valor


class CilindroDialog(QDialog):
    """Formulario del contrato Stock_Inicial con validación al aceptar."""

    def __init__(
        self,
        cfg: Dict[str, Any],
        ids_existentes: Set[str],
        fila: Optional[Dict[str, Any]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._ids = {str(i) for i in ids_existentes}
        self._editando = fila is not None
        self._id_original = str(fila[COL_ID]) if fila else None
        self.setWindowTitle("Editar cilindro" if self._editando else "Agregar cilindro")
        self.setMinimumWidth(360)

        cg = obtener_config_global(cfg)
        diametro_maximo = float(cg["diametro_maximo"])
        cantidad_jaulas = int(cg["cantidad_jaulas"])

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        root.addLayout(form)

        self.ed_id = QLineEdit()
        self.ed_id.setPlaceholderText("p. ej. CIL-141")
        if self._editando:
            self.ed_id.setReadOnly(True)
            self.ed_id.setEnabled(False)
        form.addRow("ID", self.ed_id)

        self.sp_diametro = QDoubleSpinBox()
        self.sp_diametro.setDecimals(1)
        self.sp_diametro.setRange(1.0, diametro_maximo)
        self.sp_diametro.setSuffix(" mm")
        self.sp_diametro.setValue(diametro_maximo)
        form.addRow("Diámetro", self.sp_diametro)

        self.cb_estado = QComboBox()
        for e in EstadoCilindro:
            self.cb_estado.addItem(e.value)
        self.cb_estado.setCurrentText(EstadoCilindro.DISPONIBLE.value)
        self.cb_estado.currentTextChanged.connect(self._on_estado_changed)
        form.addRow("Estado", self.cb_estado)

        self.cb_jaula = QComboBox()
        self.cb_jaula.addItem(_SIN_VALOR, None)
        for j in range(1, cantidad_jaulas + 1):
            self.cb_jaula.addItem(f"Jaula {j}", j)
        form.addRow("Jaula asignada", self.cb_jaula)

        self.cb_posicion = QComboBox()
        self.cb_posicion.addItem(_SIN_VALOR, None)
        self.cb_posicion.addItem("1", 1)
        self.cb_posicion.addItem("2", 2)
        form.addRow("Posición", self.cb_posicion)

        self.ed_perfil = QLineEdit()
        self.ed_perfil.setPlaceholderText("opcional (se deriva de la jaula)")
        form.addRow("Perfil", self.ed_perfil)

        self.sp_mm = QDoubleSpinBox()
        self.sp_mm.setDecimals(2)
        self.sp_mm.setRange(0.0, 50.0)
        self.sp_mm.setSuffix(" mm")
        self.sp_mm.setValue(0.5)
        form.addRow("mm a rectificar", self.sp_mm)

        self.cb_tipo = QComboBox()
        for t in TipoRectificado:
            self.cb_tipo.addItem(t.value)
        form.addRow("Tipo rectificado", self.cb_tipo)

        box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        if fila:
            self._cargar_fila(fila)
        self._on_estado_changed(self.cb_estado.currentText())

    # ── carga / recolección ──────────────────────────────────────────────

    def _cargar_fila(self, fila: Dict[str, Any]) -> None:
        self.ed_id.setText(str(fila.get(COL_ID, "")))
        diametro = _valor_o_none(fila.get(COL_DIAMETRO))
        if diametro is not None:
            self.sp_diametro.setValue(float(diametro))
        estado = _valor_o_none(fila.get(COL_ESTADO))
        if estado is not None:
            self.cb_estado.setCurrentText(str(estado))
        jaula = _valor_o_none(fila.get(COL_JAULA))
        if jaula is not None:
            idx = self.cb_jaula.findData(int(jaula))
            if idx >= 0:
                self.cb_jaula.setCurrentIndex(idx)
        posicion = _valor_o_none(fila.get(COL_POSICION))
        if posicion is not None:
            idx = self.cb_posicion.findData(int(posicion))
            if idx >= 0:
                self.cb_posicion.setCurrentIndex(idx)
        perfil = _valor_o_none(fila.get(COL_PERFIL))
        if perfil is not None:
            self.ed_perfil.setText(str(perfil))
        mm = _valor_o_none(fila.get(COL_MM))
        if mm is not None:
            self.sp_mm.setValue(float(mm))
        tipo = _valor_o_none(fila.get(COL_TIPO))
        if tipo is not None:
            self.cb_tipo.setCurrentText(str(tipo))

    def _on_estado_changed(self, estado: str) -> None:
        con_pase = estado in _ESTADOS_CON_PASE
        self.sp_mm.setEnabled(con_pase)
        self.cb_tipo.setEnabled(con_pase)
        self.cb_posicion.setEnabled(estado in _ESTADOS_CON_POSICION)

    def collect_fila(self) -> Dict[str, Any]:
        estado = self.cb_estado.currentText()
        con_pase = estado in _ESTADOS_CON_PASE
        return {
            COL_ID: self.ed_id.text().strip(),
            COL_DIAMETRO: self.sp_diametro.value(),
            COL_ESTADO: estado,
            COL_JAULA: self.cb_jaula.currentData(),
            COL_POSICION: (
                self.cb_posicion.currentData() if estado in _ESTADOS_CON_POSICION else None
            ),
            COL_PERFIL: self.ed_perfil.text().strip() or None,
            COL_MM: self.sp_mm.value() if con_pase else None,
            COL_TIPO: self.cb_tipo.currentText() if con_pase else None,
        }

    def _on_accept(self) -> None:
        fila = self.collect_fila()
        errores, avisos = validar_fila_stock(
            fila, self._cfg, self._ids, id_original=self._id_original
        )
        if errores:
            QMessageBox.warning(self, "Datos inválidos", "\n".join(errores))
            return
        if avisos:
            resp = QMessageBox.question(
                self,
                "Confirmar",
                "\n".join(avisos) + "\n\n¿Continuar igual?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if resp != QMessageBox.StandardButton.Yes:
                return
        self.accept()

    # ── API estática (patrón TurnosDialog) ───────────────────────────────

    @staticmethod
    def create(
        cfg: Dict[str, Any], ids_existentes: Set[str], parent: QWidget | None = None
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Alta: abre el diálogo vacío y retorna (aceptado, fila)."""
        dlg = CilindroDialog(cfg, ids_existentes, fila=None, parent=parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False, None
        return True, dlg.collect_fila()

    @staticmethod
    def edit(
        cfg: Dict[str, Any],
        fila: Dict[str, Any],
        ids_existentes: Set[str],
        parent: QWidget | None = None,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Edición: abre el diálogo pre-cargado (ID read-only)."""
        dlg = CilindroDialog(cfg, ids_existentes, fila=fila, parent=parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return False, None
        return True, dlg.collect_fila()
