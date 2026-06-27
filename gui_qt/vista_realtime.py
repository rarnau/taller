"""Vista Real para la GUI Qt (fase inicial visual)."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


_QUEUE_HINTS = {
    "mayor_diametro": "mayor diametro primero",
    "menor_diametro": "menor diametro primero",
    "fifo": "FIFO",
    "menor_mm_desb_fifo_prod": "menor mm (desbaste) / FIFO (produccion)",
}


def _clear_layout(layout) -> None:
    """Elimina widgets hijos de un layout de forma segura para rerender."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


class CylinderChip(QFrame):
    """Chip visual simple para mostrar cilindro + diametro."""

    def __init__(self, cilindro_id: str, diametro: float, role: str = "default") -> None:
        super().__init__()
        self.setObjectName("Chip")
        self.setProperty("role", role)

        col = QVBoxLayout(self)
        col.setContentsMargins(7, 4, 7, 4)
        col.setSpacing(0)

        top = QLabel(cilindro_id)
        top.setObjectName("ChipTitle")
        bot = QLabel(f"{diametro:.1f}")
        bot.setObjectName("ChipBody")

        col.addWidget(top)
        col.addWidget(bot)


class LaneBox(QFrame):
    """Contenedor reutilizable para una zona del taller."""

    def __init__(self, title: str, role: str, clip_overflow: bool = False) -> None:
        super().__init__()
        self.setObjectName("LaneBox")
        self.setProperty("role", role)
        self._clip_overflow = clip_overflow
        self._items: list[dict] = []
        self._role = "default"
        self._first_role: Optional[str] = None
        self._chip_widgets: list[QWidget] = []

        col = QVBoxLayout(self)
        col.setContentsMargins(8, 6, 8, 6)
        col.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("LaneTitle")
        header.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("Muted")
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.meta_label.setVisible(False)
        header.addWidget(self.meta_label, 1)

        col.addLayout(header)

        if self._clip_overflow:
            self.flow_canvas = QWidget(self)
            self.flow_canvas.setObjectName("LaneCanvas")
            self.flow_canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.flow_canvas.setMinimumHeight(24)
            col.addWidget(self.flow_canvas, 1)
        else:
            self.flow_wrap = QHBoxLayout()
            self.flow_wrap.setContentsMargins(0, 0, 0, 0)
            self.flow_wrap.setSpacing(6)
            col.addLayout(self.flow_wrap)

    def set_parada(self, parada: bool) -> None:
        self.setProperty("parada", parada)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_meta(self, text: str) -> None:
        """Muestra texto auxiliar alineado a la derecha en el header de la card."""
        txt = (text or "").strip()
        self.meta_label.setText(txt)
        self.meta_label.setVisible(bool(txt))

    def set_chips(
        self,
        cilindros: Iterable[dict],
        role: str = "default",
        first_role: Optional[str] = None,
    ) -> None:
        """Renderiza chips en modo normal o en modo recorte por espacio."""
        self._items = list(cilindros)
        self._role = role
        self._first_role = first_role
        if self._clip_overflow:
            self._reflow_chips()
            return

        _clear_layout(self.flow_wrap)
        any_item = False
        for idx, item in enumerate(self._items):
            item_role = first_role if (idx == 0 and first_role is not None) else role
            chip = CylinderChip(item["id"], float(item["d"]), role=item_role)
            self.flow_wrap.addWidget(chip)
            any_item = True
        if not any_item:
            empty = QLabel("-")
            empty.setObjectName("Muted")
            self.flow_wrap.addWidget(empty)
        self.flow_wrap.addStretch(1)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._clip_overflow:
            self._reflow_chips()

    def _clear_chip_widgets(self) -> None:
        for w in self._chip_widgets:
            w.deleteLater()
        self._chip_widgets.clear()

    def _reflow_chips(self) -> None:
        if self.flow_canvas.width() <= 0 or self.flow_canvas.height() <= 0:
            return

        self._clear_chip_widgets()

        if not self._items:
            empty = QLabel("-", self.flow_canvas)
            empty.setObjectName("Muted")
            empty.move(2, 2)
            empty.show()
            self._chip_widgets.append(empty)
            return

        chip_w = 62
        chip_h = 40
        gap = 6
        avail_w = max(1, self.flow_canvas.width() - 2)
        avail_h = max(1, self.flow_canvas.height() - 2)
        cols = max(1, (avail_w + gap) // (chip_w + gap))
        rows = max(1, (avail_h + gap) // (chip_h + gap))
        max_visible = cols * rows

        for vis_idx, item in enumerate(self._items[:max_visible]):
            item_role = self._first_role if (vis_idx == 0 and self._first_role is not None) else self._role
            chip = CylinderChip(item["id"], float(item["d"]), role=item_role)
            chip.setParent(self.flow_canvas)
            chip.setFixedSize(chip_w, chip_h)
            r = vis_idx // cols
            c = vis_idx % cols
            chip.move(c * (chip_w + gap), r * (chip_h + gap))
            chip.show()
            self._chip_widgets.append(chip)


class MachineCard(QFrame):
    """Card de una rectificadora con estado y progreso."""

    def __init__(self, name: str) -> None:
        super().__init__()
        self.setObjectName("MachineCard")
        self.setMinimumHeight(74)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        col = QVBoxLayout(self)
        col.setContentsMargins(9, 7, 9, 7)
        col.setSpacing(5)

        header = QHBoxLayout()

        self.title = QLabel(name)
        self.title.setObjectName("LaneTitle")
        header.addWidget(self.title)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("Muted")
        self.meta_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        header.addWidget(self.meta_label)

        col.addLayout(header)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setObjectName("MachineProgress")
        col.addWidget(self.progress)

        self.state_label = QLabel("Libre")
        self.state_label.setObjectName("Muted")
        col.addWidget(self.state_label)

    def set_state(self, data: Optional[dict], operativa: bool = True) -> None:
        """Pinta estado de maquina: ocupada, libre operativa o fuera de turno."""
        if data:
            self.setProperty("mode", "busy")
            prog = max(0, min(100, int(data.get("progreso", 0))))
            self.progress.setValue(prog)
            self.meta_label.setText(f"{data['id']} · {float(data['d']):.1f} mm")
            self.state_label.setText(f"Rectificando · {prog}%")
            self.state_label.setObjectName("MachineBusy")
        elif operativa:
            self.setProperty("mode", "idle")
            self.progress.setValue(0)
            self.meta_label.setText("● Libre · operativa")
            self.state_label.setText("Libre · operativa")
            self.state_label.setObjectName("MachineGood")
        else:
            self.setProperty("mode", "off")
            self.progress.setValue(0)
            self.meta_label.setText("● Fuera de turno")
            self.state_label.setText("Fuera de turno")
            self.state_label.setObjectName("MachineOff")

        self.style().unpolish(self)
        self.style().polish(self)
        self.state_label.style().unpolish(self.state_label)
        self.state_label.style().polish(self.state_label)


class StockBarCard(QFrame):
    """Barra compacta de stock disponible por jaula."""

    def __init__(self, jaula_id: int) -> None:
        super().__init__()
        self.setObjectName("StockBarCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        col = QVBoxLayout(self)
        col.setContentsMargins(4, 4, 4, 4)
        col.setSpacing(6)

        self.value_label = QLabel("0")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.value_label.setObjectName("StockValue")
        col.addWidget(self.value_label)

        self.progress = QProgressBar()
        self.progress.setObjectName("StockBarProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setOrientation(Qt.Orientation.Vertical)
        self.progress.setInvertedAppearance(False)
        self.progress.setTextVisible(False)
        self.progress.setMinimumHeight(110)
        self.progress.setMinimumWidth(60)
        self.progress.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        col.addWidget(self.progress, 1)

        j = QLabel(f"J{jaula_id}")
        j.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        j.setObjectName("Muted")
        col.addWidget(j)

    def set_value(self, value: int, scale: int) -> None:
        """Actualiza valor absoluto y porcentaje relativo de la barra."""
        self.value_label.setText(str(value))
        if scale <= 0:
            self.progress.setValue(0)
            return
        pct = int(max(0.0, min(1.0, float(value) / float(scale))) * 100)
        self.progress.setValue(pct)


class RealTimeView(QWidget):
    """Vista visual de snapshots para la pestaña Vista Real."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.jaulas_boxes: Dict[int, LaneBox] = {}
        self.crc_boxes: Dict[int, LaneBox] = {}
        self.machine_cards: Dict[str, MachineCard] = {}
        self.stock_cards: Dict[int, StockBarCard] = {}
        self._num_jaulas = 0
        self._disp_scale = 1
        self._substock_by_jaula: Dict[int, str] = {}
        self.estrategia = "mayor_diametro"
        self._alertas_criticas = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        legend_row = QHBoxLayout()
        legend_row.addStretch(1)
        for txt, color in (
            ("● Trabajando", "#4A9EFF"),
            ("● CRC", "#F0A32E"),
            ("● Disponible", "#35C98A"),
        ):
            lbl = QLabel(txt)
            lbl.setStyleSheet(f"color:{color}; font-size:11px; font-weight:600;")
            legend_row.addWidget(lbl)
        root.addLayout(legend_row)

        body = QHBoxLayout()
        body.setSpacing(10)
        root.addLayout(body)

        left = QVBoxLayout()
        left.setSpacing(9)
        body.addLayout(left, 4)

        self.jaulas_title = QLabel("JAULAS")
        self.jaulas_title.setObjectName("BoardHeader")
        left.addWidget(self.jaulas_title)

        self.jaulas_grid = QGridLayout()
        self.jaulas_grid.setHorizontalSpacing(8)
        self.jaulas_grid.setVerticalSpacing(8)
        left.addLayout(self.jaulas_grid)

        self.stock_title = QLabel("STOCK DISPONIBLE POR JAULA")
        self.stock_title.setObjectName("BoardHeader")
        left.addWidget(self.stock_title)

        self.stock_row = QHBoxLayout()
        self.stock_row.setSpacing(6)
        left.addLayout(self.stock_row)

        right = QVBoxLayout()
        right.setSpacing(9)
        right.setAlignment(Qt.AlignmentFlag.AlignTop)
        body.addLayout(right, 3)

        self.machines_title = QLabel("RECTIFICADORAS")
        self.machines_title.setObjectName("BoardHeader")
        right.addWidget(self.machines_title)

        self.machines_col = QVBoxLayout()
        self.machines_col.setSpacing(8)
        self.machines_col.setAlignment(Qt.AlignmentFlag.AlignTop)
        right.addLayout(self.machines_col)

        self.queue_box = LaneBox("COLA A RECTIFICAR", role="queue", clip_overflow=True)
        self.queue_box.title_label.setObjectName("LaneTitleQueue")
        self.queue_box.set_meta(_QUEUE_HINTS.get(self.estrategia, ""))
        self.queue_box.setMinimumHeight(76)
        self.queue_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.cooling_box = LaneBox("EN ENFRIAMIENTO", role="cooling", clip_overflow=True)
        self.cooling_box.title_label.setObjectName("LaneTitleCooling")
        self.cooling_box.setMinimumHeight(76)
        self.cooling_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right.addWidget(self.queue_box, 1)
        right.addWidget(self.cooling_box, 1)

        self.footer_stats = QHBoxLayout()
        self.footer_stats.setSpacing(6)
        right.addLayout(self.footer_stats)

        self.lbl_total = QLabel("0 cilindros")
        self.lbl_total.setObjectName("StatPill")
        self.footer_stats.addWidget(self.lbl_total)

        self.lbl_paradas = QLabel("0 paradas")
        self.lbl_paradas.setObjectName("StatPill")
        self.lbl_paradas.setToolTip(
            "Paradas: cantidad de jaulas actualmente detenidas por falta de pareja en CRC/stock elegible."
        )
        self.footer_stats.addWidget(self.lbl_paradas)

        self.lbl_alertas = QLabel("0 alerta crítica")
        self.lbl_alertas.setObjectName("StatPill")
        self.lbl_alertas.setToolTip(
            "Alertas críticas: eventos severos reportados por la simulación (riesgos/errores operativos)."
        )
        self.footer_stats.addWidget(self.lbl_alertas)
        self.footer_stats.addStretch(1)

    def set_machine_names(self, names: List[str]) -> None:
        """Reconstruye cards de maquinas segun listado actual del taller."""
        _clear_layout(self.machines_col)
        self.machine_cards.clear()
        for name in names:
            card = MachineCard(name)
            self.machines_col.addWidget(card)
            self.machine_cards[name] = card
        self.machines_col.addStretch(1)

    def set_jaula_count(self, count: int) -> None:
        """Reconstruye grilla de jaulas/CRC cuando cambia cantidad de jaulas."""
        if self._num_jaulas == count and self.jaulas_boxes:
            return

        while self.jaulas_grid.count():
            item = self.jaulas_grid.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.jaulas_boxes.clear()
        self.crc_boxes.clear()
        self._num_jaulas = count

        for idx in range(1, count + 1):
            row = idx - 1
            label = QLabel(f"J{idx}")
            label.setObjectName("SectionTitle")
            self.jaulas_grid.addWidget(label, row, 0)

            j_box = LaneBox("TRABAJANDO", role="work")
            c_box = LaneBox("BUFFER CRC", role="crc")
            j_box.title_label.setObjectName("LaneTitleWork")
            c_box.title_label.setObjectName("LaneTitleCRC")
            j_box.setMinimumHeight(72)
            c_box.setMinimumHeight(72)
            self.jaulas_grid.addWidget(j_box, row, 1)
            self.jaulas_grid.addWidget(c_box, row, 2)

            self.jaulas_boxes[idx] = j_box
            self.crc_boxes[idx] = c_box

        self.jaulas_grid.setColumnStretch(1, 1)
        self.jaulas_grid.setColumnStretch(2, 1)
        self._rebuild_stock_cards(count)

    def set_strategy(self, estrategia: str) -> None:
        """Configura la estrategia para orden de cola y texto de ayuda."""
        self.estrategia = estrategia
        self.queue_box.set_meta(_QUEUE_HINTS.get(estrategia, "-"))

    def configure_disponibilidad(self, substock_by_jaula: Dict[int, str], scale_max: int) -> None:
        """Configura mapeo jaula->substock y escala maxima de barras."""
        self._substock_by_jaula = dict(substock_by_jaula)
        self._disp_scale = max(1, int(scale_max))

    def set_alertas_criticas(self, n_alertas: int) -> None:
        """Actualiza cantidad de alertas criticas para el bloque resumen."""
        self._alertas_criticas = max(0, int(n_alertas))

    def _rebuild_stock_cards(self, count: int) -> None:
        """Regenera barras de stock disponible por jaula."""
        _clear_layout(self.stock_row)
        self.stock_cards.clear()
        for idx in range(1, count + 1):
            card = StockBarCard(idx)
            self.stock_row.addWidget(card, 1)
            self.stock_cards[idx] = card

    def _ordenar_cola(self, queue: List[dict]) -> List[dict]:
        """Ordena la cola de rectificado segun estrategia seleccionada."""
        if self.estrategia == "mayor_diametro":
            return sorted(queue, key=lambda c: float(c.get("d", 0.0)), reverse=True)
        if self.estrategia == "menor_diametro":
            return sorted(queue, key=lambda c: float(c.get("d", 0.0)))
        return list(queue)

    def update_from_snapshot(self, snapshot) -> None:
        """Actualiza todos los paneles de Vista Real a partir de un snapshot."""
        # 1) Jaulas/CRC y estados de parada.
        paradas = set(getattr(snapshot, "jaulas_paradas", []))
        jaulas = getattr(snapshot, "detalle_jaulas", {})
        crcs = getattr(snapshot, "detalle_crc", {})

        for idx, box in self.jaulas_boxes.items():
            box.set_chips(jaulas.get(idx, []), role="work")
            box.set_parada(idx in paradas)

        for idx, box in self.crc_boxes.items():
            box.set_chips(crcs.get(idx, []), role="crc")

        # 2) Cola y enfriamiento.
        queue = self._ordenar_cola(getattr(snapshot, "detalle_cola_rectificado", []))
        cooling = getattr(snapshot, "detalle_enfriando", [])
        self.queue_box.set_chips(queue, role="queue", first_role="queue_next")
        self.cooling_box.set_chips(cooling, role="cooling")

        # 3) Disponibles por SubStock (mapeados a barra por jaula).
        disp = getattr(snapshot, "disponibles_por_substock", {})
        for idx, card in self.stock_cards.items():
            ss = self._substock_by_jaula.get(idx)
            value = int(disp.get(ss, 0)) if ss else 0
            card.set_value(value, self._disp_scale)

        # 4) Estado puntual de rectificadoras.
        operativas = getattr(snapshot, "detalle_maquinas_operativa", {})
        details = getattr(snapshot, "detalle_maquinas", {})
        for name, card in self.machine_cards.items():
            card.set_state(details.get(name), bool(operativas.get(name, True)))

        conteos = getattr(snapshot, "conteo_por_estado", {})
        total = sum(int(v) for v in conteos.values()) if conteos else 0
        self.lbl_total.setText(f"{total} cilindros")
        self.lbl_paradas.setText(f"{len(paradas)} paradas")
        self.lbl_alertas.setText(f"{self._alertas_criticas} alerta crítica")
        if self._alertas_criticas > 0:
            self.lbl_alertas.setObjectName("StatPillAlert")
        else:
            self.lbl_alertas.setObjectName("StatPill")
        self.lbl_alertas.style().unpolish(self.lbl_alertas)
        self.lbl_alertas.style().polish(self.lbl_alertas)

    def set_placeholder(self, text: str) -> None:
        """Deja la vista en estado vacio previo a cargar/simular."""
        self.queue_box.set_chips([], role="queue")
        self.cooling_box.set_chips([], role="cooling")
        for card in self.stock_cards.values():
            card.set_value(0, 1)
