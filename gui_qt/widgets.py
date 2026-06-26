"""Componentes reutilizables (chips, tarjetas, badges) y helpers de estilo.

Pequeñas piezas que reproducen los bloques del HTML: el chip de cilindro
(id + día, monoespaciado, fondo por estado), las tarjetas-panel, los títulos de
sección, etc. Sin dependencias del motor.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QVBoxLayout,
                               QWidget)

from . import theme as T


# ── Helpers de bajo nivel ─────────────────────────────────────────────────────

def label(text: str = "", *, color: str = T.TEXT, size: int = 13,
          weight: int = 400, family: str = T.FONT_UI,
          ls: float | None = None) -> QLabel:
    """QLabel estilizado por hoja inline (espejo de los ``style=`` del HTML)."""
    lb = QLabel(text)
    css = f"color:{color}; font-size:{size}px; font-weight:{weight}; font-family:{family}; background:transparent;"
    if ls is not None:
        css += f" letter-spacing:{ls}px;"
    lb.setStyleSheet(css)
    return lb


def titulo_seccion(text: str, color: str = T.ORANGE, size: int = 13,
                   ls: float = 0.5) -> QLabel:
    """Título de panel: Space Grotesk, bold, con tracking."""
    return label(text, color=color, size=size, weight=700,
                 family=T.FONT_DISPLAY, ls=ls)


_marco_uid = 0


def marco(frame: QFrame, *, bg: str = T.PANEL, border: str = T.BORDER,
          radius: int = 12, bw: int = 1) -> QFrame:
    """Aplica fondo/borde/radio **sólo a este QFrame** (selector por objectName).

    Imprescindible: una regla ``QFrame{border:...}`` también matchea los QLabel
    hijos (QLabel hereda de QFrame), por lo que un borde de color se "derramaría"
    sobre cada etiqueta interna. El selector ``QFrame#id`` lo evita.
    """
    global _marco_uid
    _marco_uid += 1
    name = f"mc{_marco_uid}"
    frame.setObjectName(name)
    frame.setStyleSheet(
        f"QFrame#{name}{{background:{bg}; border:{bw}px solid {border}; border-radius:{radius}px;}}")
    return frame


def panel(padding: int = 16, *, radius: int = 12, bg: str = T.PANEL,
          border: str = T.BORDER) -> QFrame:
    """Tarjeta con fondo, borde y radio (el contenedor base de las vistas)."""
    f = marco(QFrame(), bg=bg, border=border, radius=radius)
    lay = QVBoxLayout(f)
    lay.setContentsMargins(padding, padding, padding, padding)
    lay.setSpacing(10)
    return f


def fila(spacing: int = 9, margins: tuple = (0, 0, 0, 0)) -> tuple[QWidget, QHBoxLayout]:
    """Contenedor horizontal transparente con su layout."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return w, lay


def columna(spacing: int = 9, margins: tuple = (0, 0, 0, 0)) -> tuple[QWidget, QVBoxLayout]:
    """Contenedor vertical transparente con su layout."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    lay = QVBoxLayout(w)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    return w, lay


# ── Chip de cilindro (id grande + día pequeño) ────────────────────────────────

class Chip(QFrame):
    """Ficha de un cilindro: id arriba, sub (día/diámetro) abajo, fondo por estado."""

    def __init__(self, cid: str, sub: str, color: str, txt: str,
                 *, min_w: int = 48, id_size: float = 11, sub_size: float = 9):
        super().__init__()
        self.setStyleSheet(
            f"QFrame{{background:{color}; border-radius:7px;}}")
        self.setMinimumWidth(min_w)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 5)
        lay.setSpacing(0)
        l1 = QLabel(str(cid))
        l1.setAlignment(Qt.AlignCenter)
        l1.setStyleSheet(
            f"color:{txt}; font-family:{T.FONT_MONO}; font-size:{id_size}px; font-weight:600; background:transparent;")
        l2 = QLabel(str(sub))
        l2.setAlignment(Qt.AlignCenter)
        l2.setStyleSheet(
            f"color:{txt}; font-family:{T.FONT_MONO}; font-size:{sub_size}px; background:transparent;")
        l2.setStyleSheet(l2.styleSheet() + "opacity:0.65;")
        lay.addWidget(l1)
        lay.addWidget(l2)


def chip_desde(d: dict, *, min_w: int = 48, id_size: float = 11,
               sub_size: float = 9) -> Chip:
    """Crea un Chip a partir de un dict {id, dia/sub, color, txt}."""
    return Chip(d.get("id", ""), d.get("sub", d.get("dia", "")),
                d.get("color", T.TEXT_MUTE), d.get("txt", "#fff"),
                min_w=min_w, id_size=id_size, sub_size=sub_size)


class Badge(QLabel):
    """Pastilla redondeada (estado en tabla, contadores del footer)."""

    def __init__(self, text: str, *, color: str, bg: str | None = None,
                 border: str | None = None, size: int = 11):
        super().__init__(text)
        bg = bg or T.tint(color)
        border = border or color
        self.setStyleSheet(
            f"QLabel{{background:{bg}; border:1px solid {border}; color:{color};"
            f" border-radius:20px; padding:3px 10px; font-size:{size}px; font-weight:600;}}")


class FlowLayout(QLayout):
    """Layout que envuelve sus items a la siguiente línea (flex-wrap del HTML).

    Su ancho mínimo es el del item más ancho (puede colocar uno por línea), así
    que no fuerza un ancho mínimo grande sobre su contenedor — clave para que las
    grillas de dos columnas no se desborden por culpa de una leyenda larga.
    """

    def __init__(self, parent=None, hspace=8, vspace=6):
        super().__init__(parent)
        self._items = []
        self._h = hspace
        self._v = vspace
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            w = it.sizeHint().width()
            h = it.sizeHint().height()
            if x + w > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + self._v
                line_h = 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), it.sizeHint()))
            x += w + self._h
            line_h = max(line_h, h)
        return y + line_h - rect.y()


def leyenda(items, *, marca: str = "■", size: float = 10.5) -> QWidget:
    """Fila de leyenda con wrap: ``items`` = lista de (texto, color)."""
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    fl = FlowLayout(w, hspace=14, vspace=6)
    for txt, col in items:
        cell = QWidget()
        cell.setStyleSheet("background:transparent;")
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(5)
        cl.addWidget(label(marca, color=col, size=size))
        cl.addWidget(label(txt, color=T.TEXT_2, size=size))
        fl.addWidget(cell)
    return w


def limpiar_layout(lay) -> None:
    """Elimina todos los widgets/sub-layouts de un layout (para re-render)."""
    while lay.count():
        item = lay.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        else:
            sub = item.layout()
            if sub is not None:
                limpiar_layout(sub)
