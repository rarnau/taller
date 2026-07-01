"""Layout que acomoda los widgets en fila y los envuelve a la línea siguiente.

Evita que una fila de chips fuerce un ancho mínimo mayor que el panel (que, con
el scroll horizontal apagado, recortaría el contenido a la derecha).
"""

from __future__ import annotations

from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy, QWidget


class FlowWidget(QWidget):
    """QWidget que delega hasHeightForWidth/heightForWidth/sizeHint a su FlowLayout.

    Un QWidget plano NO propaga height-for-width al layout padre, así que los
    chips colapsan a alto 0. Esta subclase cierra ese hueco: además del override
    de ``heightForWidth`` hace falta activar el flag en la *size policy* porque
    ``QWidgetItem.hasHeightForWidth()`` consulta la policy, no el método.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        lay = self.layout()
        return lay is not None and lay.hasHeightForWidth()

    def heightForWidth(self, w: int) -> int:
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            return lay.heightForWidth(w)
        return super().heightForWidth(w)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        # El alto depende del ancho: al cambiar el ancho hay que reconsultar el
        # height-for-width del layout padre.
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        lay = self.layout()
        if lay is not None and lay.hasHeightForWidth():
            w = self.width() or lay.minimumSize().width()
            h = lay.heightForWidth(w)
            return QSize(w, max(h, lay.minimumSize().height()))
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:
        lay = self.layout()
        if lay is not None:
            return lay.minimumSize()
        return super().minimumSizeHint()


class FlowLayout(QLayout):
    def __init__(
        self,
        parent: QWidget | None = None,
        margin: int = 0,
        h_spacing: int = 6,
        v_spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(QMargins(margin, margin, margin, margin))

    def __del__(self) -> None:  # pragma: no cover - Qt cleanup
        while self._items:
            self._items.pop()

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(
            margins.left() + margins.right(),
            margins.top() + margins.bottom(),
        )
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            margins.left(), margins.top(), -margins.right(), -margins.bottom()
        )
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisible():
                continue
            hint = item.sizeHint()
            next_x = x + hint.width() + self._h_spacing
            if next_x - self._h_spacing > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + self._v_spacing
                next_x = x + hint.width() + self._h_spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_height = max(line_height, hint.height())

        return y + line_height - rect.y() + margins.bottom()
