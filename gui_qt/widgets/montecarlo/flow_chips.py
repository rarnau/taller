"""Contenedor que acomoda chips en filas y envuelve, fijando su propia altura.

A diferencia de ``FlowLayout`` (que depende de ``heightForWidth``, frágil y
dependiente de plataforma dentro de un ``QScrollArea``), este widget reposiciona
los chips a mano en ``resizeEvent`` y **fija su altura** (``setFixedHeight``) al
alto real que ocupan. Así el layout padre siempre reserva el espacio correcto y
los chips nunca colapsan a altura 0 (el bug de "no se ven los botones").
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QSizePolicy, QWidget


class FlowChips(QWidget):
    """Acomoda sus widgets hijos (chips) en filas del ancho de su texto.

    Los chips se agregan con :meth:`add`. En cada cambio de ancho recalcula las
    filas y ajusta su altura fija, de modo que "varios botones por línea" entra
    de forma robusta dentro de una card con scroll (sin ``heightForWidth``).
    """

    def __init__(self, h_spacing: int = 6, v_spacing: int = 6,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._chips: List[QWidget] = []
        self._hs = h_spacing
        self._vs = v_spacing
        # Ancho flexible; la altura la controlamos nosotros (setFixedHeight).
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def add(self, chip: QWidget) -> None:
        chip.setParent(self)
        chip.show()
        self._chips.append(chip)
        self._aplicar(max(self.width(), 1))

    def _visibles(self) -> List[QWidget]:
        return [c for c in self._chips if not c.isHidden()]

    def _alto_para(self, ancho: int, *, colocar: bool) -> int:
        """Recorre los chips acomodándolos; devuelve el alto total ocupado.

        Con ``colocar=True`` fija la geometría de cada chip; con ``False`` solo
        mide (para ``sizeHint``).
        """
        x = 0
        y = 0
        alto_fila = 0
        for chip in self._visibles():
            hint = chip.sizeHint()
            w, h = hint.width(), hint.height()
            if x > 0 and x + w > ancho:  # no entra: salto de línea
                x = 0
                y += alto_fila + self._vs
                alto_fila = 0
            if colocar:
                chip.setGeometry(x, y, w, h)
            x += w + self._hs
            alto_fila = max(alto_fila, h)
        return y + alto_fila

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._aplicar(self.width())

    def _aplicar(self, ancho: int) -> None:
        total = self._alto_para(max(ancho, 1), colocar=True)
        if self.height() != total:
            self.setFixedHeight(total)

    def sizeHint(self) -> QSize:
        ancho = self.width() or 300
        return QSize(ancho, self._alto_para(ancho, colocar=False))

    def minimumSizeHint(self) -> QSize:
        # Ancho del chip más ancho (para no forzar el corte de uno solo) y una fila.
        w = max((c.sizeHint().width() for c in self._visibles()), default=0)
        h = max((c.sizeHint().height() for c in self._visibles()), default=0)
        return QSize(w, h)
