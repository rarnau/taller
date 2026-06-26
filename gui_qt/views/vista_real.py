"""Pestaña Vista Real: jaulas + buffer CRC + máquinas + cola + enfriamiento."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget)

from .. import theme as T
from ..widgets import (Badge, chip_desde, columna, fila, label, limpiar_layout,
                       marco, titulo_seccion)


class VistaReal(QWidget):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        self.vm = None
        self._build()

    def _build(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(18)

        # ── Columna izquierda: JAULAS ────────────────────────────────────────
        left, left_lay = columna(spacing=0)
        head = QHBoxLayout()
        head.addWidget(titulo_seccion("JAULAS", T.TEXT, size=14, ls=0.6))
        head.addStretch()
        leg = QHBoxLayout()
        leg.setSpacing(7)
        for txt, col in (("● Trabajando", T.BLUE), ("● CRC", T.ORANGE_2), ("● Disponible", T.GREEN)):
            leg.addWidget(label(txt, color=col, size=10))
        head.addLayout(leg)
        left_lay.addLayout(head)
        left_lay.addSpacing(12)

        self.jaulas_box = QVBoxLayout()
        self.jaulas_box.setSpacing(9)
        left_lay.addLayout(self.jaulas_box)
        left_lay.addSpacing(16)

        left_lay.addWidget(titulo_seccion("STOCK DISPONIBLE POR JAULA", T.GREEN, size=12))
        left_lay.addSpacing(10)
        self.bars_box = QHBoxLayout()
        self.bars_box.setSpacing(14)
        left_lay.addLayout(self.bars_box)
        left_lay.addStretch()
        root.addWidget(left, 115)

        # ── Columna derecha: MÁQUINAS ────────────────────────────────────────
        right, right_lay = columna(spacing=0)
        right_lay.addWidget(titulo_seccion("RECTIFICADORAS", T.TEXT, size=14, ls=0.6))
        right_lay.addSpacing(12)
        self.maq_box = QVBoxLayout()
        self.maq_box.setSpacing(9)
        right_lay.addLayout(self.maq_box)
        right_lay.addSpacing(16)

        colah = QHBoxLayout()
        colah.setSpacing(8)
        colah.addWidget(titulo_seccion("COLA A RECTIFICAR", T.RED, size=12))
        self.cola_label = label("", color=T.TEXT_MUTE, size=10)
        colah.addWidget(self.cola_label)
        colah.addStretch()
        right_lay.addLayout(colah)
        right_lay.addSpacing(10)
        self.cola_box = QHBoxLayout()
        self.cola_box.setSpacing(6)
        self.cola_box.setAlignment(Qt.AlignLeft)
        self._cola_wrap = _FlowRow()
        right_lay.addWidget(self._cola_wrap)
        right_lay.addSpacing(16)

        right_lay.addWidget(titulo_seccion("EN ENFRIAMIENTO", T.CYAN, size=12))
        right_lay.addSpacing(10)
        self._enf_wrap = _FlowRow()
        right_lay.addWidget(self._enf_wrap)
        right_lay.addStretch()

        self.footer_box = QHBoxLayout()
        self.footer_box.setSpacing(8)
        right_lay.addLayout(self.footer_box)
        root.addWidget(right, 100)

    # ── API ───────────────────────────────────────────────────────────────────
    def set_vm(self, vm):
        self.vm = vm

    def update_snapshot(self, idx: int):
        if self.vm is None or self.vm.N == 0:
            return
        self._render_jaulas(self.vm.jaulas(idx))
        self._render_bars(self.vm.disp_bars(idx))
        self._render_maquinas(self.vm.machines(idx))
        self._render_chips(self._cola_wrap, self.vm.cola(idx), min_w=42)
        self.cola_label.setText(f"{self.vm.estrategia_label.lower()} primero ▾")
        self._render_chips(self._enf_wrap, self.vm.enfriando(idx), min_w=42)
        self._render_footer(idx)

    # ── Render helpers ──────────────────────────────────────────────────────
    def _render_jaulas(self, jaulas):
        limpiar_layout(self.jaulas_box)
        for j in jaulas:
            row, row_lay = fila(spacing=9)
            num = label(j["n"], color=T.TEXT_2, size=18, weight=700, family=T.FONT_DISPLAY)
            num.setFixedWidth(30)
            num.setAlignment(Qt.AlignCenter)
            row_lay.addWidget(num)
            # Trabajando / PARADA
            trab = marco(QFrame(), bg=T.PANEL, border=j["trab_border"],
                         radius=10, bw=j["trab_bw"])
            tl = QVBoxLayout(trab)
            tl.setContentsMargins(9, 8, 9, 8)
            tl.setSpacing(6)
            tl.addWidget(label(j["trab_label"], color=j["trab_label_color"], size=9.5, weight=700, ls=0.7))
            tl.addWidget(self._chip_row(j["trab"]))
            row_lay.addWidget(trab, 1)
            # CRC
            crc = marco(QFrame(), bg=T.PANEL, border=T.BORDER, radius=10)
            cl = QVBoxLayout(crc)
            cl.setContentsMargins(9, 8, 9, 8)
            cl.setSpacing(6)
            cl.addWidget(label("BUFFER CRC", color=T.ORANGE_2, size=9.5, weight=700, ls=0.7))
            cl.addWidget(self._chip_row(j["crc"]))
            row_lay.addWidget(crc, 1)
            self.jaulas_box.addWidget(row)

    def _chip_row(self, chips) -> QWidget:
        w = _FlowRow()
        w.set_chips(chips, min_w=48)
        return w

    def _render_bars(self, bars):
        limpiar_layout(self.bars_box)
        for b in bars:
            col, col_lay = columna(spacing=5)
            col_lay.setAlignment(Qt.AlignBottom)
            v = label(str(b["val"]), color=b["color"], size=12, weight=600, family=T.FONT_MONO)
            v.setAlignment(Qt.AlignCenter)
            col_lay.addWidget(v)
            barbg = QFrame()
            barbg.setFixedHeight(64)
            barbg.setStyleSheet(f"background:{T.HOLE}; border-radius:6px;")
            bl = QVBoxLayout(barbg)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setAlignment(Qt.AlignBottom)
            fill = QFrame()
            fill.setStyleSheet(f"background:{b['color']}; border-radius:6px;")
            fill.setFixedHeight(max(2, round(b["hpct"] / 100 * 64)))
            bl.addWidget(fill)
            col_lay.addWidget(barbg)
            n = label(b["n"], color=T.TEXT_MUTE, size=11)
            n.setAlignment(Qt.AlignCenter)
            col_lay.addWidget(n)
            self.bars_box.addWidget(col, 1)

    def _render_maquinas(self, machines):
        limpiar_layout(self.maq_box)
        for m in machines:
            f = marco(QFrame(), bg=T.PANEL, border=m["border"], radius=10)
            lay = QVBoxLayout(f)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(5)
            top = QHBoxLayout()
            top.addWidget(label(m["name"], size=13, weight=600, family=T.FONT_MONO))
            top.addStretch()
            top.addWidget(label(m["sub"], color=m["sub_color"], size=11))
            lay.addLayout(top)
            barbg = QFrame()
            barbg.setFixedHeight(7)
            barbg.setStyleSheet(f"background:{T.TRACK}; border-radius:4px;")
            bl = QHBoxLayout(barbg)
            bl.setContentsMargins(0, 0, 0, 0)
            fill = QFrame()
            fill.setStyleSheet(f"background:{m['bar_color']}; border-radius:4px;")
            bl.addWidget(fill, max(0, int(m["pct"])))
            bl.addStretch(max(1, 100 - int(m["pct"])))
            lay.addWidget(barbg)
            lay.addWidget(label(m["status"], color=T.TEXT_MUTE, size=10.5))
            self.maq_box.addWidget(f)

    def _render_chips(self, wrap, chips, min_w=42):
        wrap.set_chips(chips, min_w=min_w, id_size=10.5, sub_size=8.5)

    def _render_footer(self, idx):
        limpiar_layout(self.footer_box)
        total = self.vm.total_cil()
        paradas = self.vm.parada_count(idx)
        alertas = self.vm.alertas_count(idx)
        self.footer_box.addWidget(_pill(f"{total} cilindros"))
        self.footer_box.addWidget(_pill(f"{paradas} paradas"))
        crit = Badge(f"{alertas} alerta crítica", color=T.RED,
                     bg=T.tint(T.RED, "1a"), border=T.tint(T.RED, "55"))
        self.footer_box.addWidget(crit)
        self.footer_box.addStretch()


def _pill(text: str) -> QFrame:
    f = marco(QFrame(), bg=T.PANEL, border=T.BORDER, radius=7)
    lay = QHBoxLayout(f)
    lay.setContentsMargins(10, 6, 10, 6)
    lay.addWidget(label(text, color=T.TEXT_MUTE, size=11))
    return f


class _FlowRow(QWidget):
    """Fila de chips con wrap automático (flex-wrap del HTML)."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background:transparent;")
        self._lay = _FlowLayout(self, hspace=6, vspace=6)

    def set_chips(self, chips, *, min_w=48, id_size=11, sub_size=9):
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for c in chips:
            self._lay.addWidget(chip_desde(c, min_w=min_w, id_size=id_size, sub_size=sub_size))
        self._lay.invalidate()

    def set_widgets(self, widgets):
        while self._lay.count():
            it = self._lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for w in widgets:
            self._lay.addWidget(w)


# ── FlowLayout (wrap de widgets) ──────────────────────────────────────────────
from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QLayout, QSizePolicy  # noqa: E402


class _FlowLayout(QLayout):
    def __init__(self, parent=None, hspace=6, vspace=6):
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
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size + QSize(0, 0)

    def _do_layout(self, rect, test):
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
