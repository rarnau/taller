"""Pestaña Configuración: parámetros globales, rangos de SubStock y máquinas.

Lee/escribe ``app.cfg`` mediante los mutadores de ``config.persistencia`` (la
misma capa CRUD que usan el CLI y la GUI Tk). "Guardar" valida coherencia,
persiste y re-aplica.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLineEdit, QPushButton, QVBoxLayout, QWidget)

from config import persistencia as cfgmod
from config.persistencia import (obtener_config_global, obtener_estrategia_asignacion,
                                  obtener_estrategia_seleccion, obtener_max_iteraciones,
                                  obtener_maquinas, obtener_rangos, obtener_tiempo_enfriado)
from modelos.estrategias import ESTRATEGIAS_ASIGNACION, ESTRATEGIAS_SELECCION

from .. import theme as T
from ..widgets import label, marco, panel, titulo_seccion


def _input(value: str, width: int = 88) -> QLineEdit:
    e = QLineEdit(str(value))
    if width:
        e.setFixedWidth(width)
    else:
        e.setMinimumWidth(70)  # 0 ⇒ expandible (ocupa el espacio de la columna)
    e.setAlignment(Qt.AlignCenter)
    e.setStyleSheet(
        f"QLineEdit{{background:{T.HOLE}; border:1px solid {T.BORDER_IN}; border-radius:7px;"
        f" padding:6px 10px; color:{T.TEXT}; font-family:{T.FONT_MONO}; font-size:12.5px;}}"
        f"QLineEdit:focus{{border-color:{T.ORANGE};}}")
    return e


def _combo(opciones, actual, width=206) -> QComboBox:
    c = QComboBox()
    c.setFixedWidth(width)
    for clave, etiqueta in opciones:
        c.addItem(etiqueta, clave)
    idx = max(0, [o[0] for o in opciones].index(actual)) if actual in [o[0] for o in opciones] else 0
    c.setCurrentIndex(idx)
    c.setStyleSheet(
        f"QComboBox{{background:{T.HOLE}; border:1px solid {T.BORDER_IN}; border-radius:7px;"
        f" padding:6px 10px; color:{T.TEXT}; font-size:12px;}}"
        f"QComboBox::drop-down{{border:none;}} QComboBox QAbstractItemView{{background:{T.PANEL};"
        f" color:{T.TEXT}; selection-background-color:{T.tint(T.ORANGE, '33')};}}")
    return c


class VistaConfig(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setStyleSheet("background:transparent;")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(18)
        self._inputs = {}
        self._rango_inputs = []
        self._build()

    def _build(self):
        cfg = self.app.cfg
        cg = obtener_config_global(cfg)

        top = QHBoxLayout()
        top.setSpacing(18)
        top.addWidget(self._panel_globales(cfg, cg), 1)
        top.addWidget(self._panel_rangos(cfg), 1)
        self.lay.addLayout(top)
        self.lay.addWidget(self._panel_maquinas(cfg))
        self.lay.addLayout(self._panel_sim_guardar(cfg))
        self.lay.addStretch()

    # ── Globales ───────────────────────────────────────────────────────────────
    def _panel_globales(self, cfg, cg):
        p = panel(18)
        p.layout().addWidget(titulo_seccion("Parámetros globales del taller", T.ORANGE, size=14))
        p.layout().addWidget(label("Rango de diámetro útil, traslado al CRC, jaulas, enfriado y estrategias.",
                                   color=T.TEXT_MUTE, size=11))
        campos = [
            ("diametro_maximo", "Diámetro máximo (mm)", cg["diametro_maximo"], ""),
            ("diametro_minimo", "Diámetro mínimo (mm)", cg["diametro_minimo"], "bajo este ⇒ BAJA"),
            ("tiempo_traslado_crc_min", "Traslado Disp.→CRC (min)", cg["tiempo_traslado_crc_min"], ""),
            ("cantidad_jaulas", "Cantidad de jaulas", cg["cantidad_jaulas"], ""),
            ("tiempo_enfriado_h", "Tiempo de enfriado (h)", obtener_tiempo_enfriado(cfg), "0 = sin enfriado"),
        ]
        for key, lbl, val, hint in campos:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(label(lbl, color=T.TEXT_2, size=12.5), 1)
            inp = _input(val)
            self._inputs[key] = inp
            row.addWidget(inp)
            h = label(hint, color=T.TEXT_DIM, size=10)
            h.setFixedWidth(108)
            row.addWidget(h)
            p.layout().addLayout(row)
        # Estrategias
        sel_opts = [(k, e.etiqueta) for k, e in ESTRATEGIAS_SELECCION.items()]
        asg_opts = [(k, e.etiqueta) for k, e in ESTRATEGIAS_ASIGNACION.items()]
        self._combo_sel = _combo(sel_opts, obtener_estrategia_seleccion(cfg))
        self._combo_asg = _combo(asg_opts, obtener_estrategia_asignacion(cfg))
        for lbl, combo in (("Estrategia de rectificado", self._combo_sel),
                           ("Estrategia de asignación", self._combo_asg)):
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(label(lbl, color=T.TEXT_2, size=12.5), 1)
            row.addWidget(combo)
            p.layout().addLayout(row)
        return p

    # ── Rangos de SubStock ─────────────────────────────────────────────────────
    def _panel_rangos(self, cfg):
        p = panel(18)
        p.layout().addWidget(titulo_seccion("Rangos de SubStock por jaula", T.ORANGE, size=14))
        p.layout().addWidget(label("Cada jaula admite cilindros con  Desde (mín) < diámetro ≤ Hasta (máx).",
                                   color=T.TEXT_MUTE, size=11))
        hdr = QHBoxLayout()
        for txt, w in (("JAULA", 60), ("DESDE (mín)", 0), ("HASTA (máx)", 0), ("PERFIL", 70)):
            lb = label(txt, color=T.TEXT_MUTE, size=10, weight=700)
            if w:
                lb.setFixedWidth(w)
            hdr.addWidget(lb, 0 if w else 1)
        p.layout().addLayout(hdr)
        self._rango_inputs = []
        for r in obtener_rangos(cfg):
            row = QHBoxLayout()
            row.setSpacing(8)
            jnum = int(r["jaula"])
            col = T.JAULA_COLORS[(jnum - 1) % len(T.JAULA_COLORS)]
            jl = label(f"■ J{jnum}", color=col, size=12, weight=700, family=T.FONT_DISPLAY)
            jl.setFixedWidth(60)
            row.addWidget(jl)
            e_desde = _input(r["desde"], 0)
            e_hasta = _input(r["hasta"], 0)
            e_perf = _input(r.get("perfil") or "—", 70)
            row.addWidget(e_desde, 1)
            row.addWidget(e_hasta, 1)
            row.addWidget(e_perf)
            p.layout().addLayout(row)
            self._rango_inputs.append((jnum, e_desde, e_hasta, e_perf))
        p.layout().addWidget(label("Las jaulas se crean/eliminan al cambiar «Cantidad de jaulas».",
                                   color=T.TEXT_DIM, size=10.5))
        return p

    # ── Máquinas ───────────────────────────────────────────────────────────────
    def _panel_maquinas(self, cfg):
        p = panel(18)
        head = QHBoxLayout()
        head.addWidget(titulo_seccion("Máquinas rectificadoras", T.ORANGE, size=14))
        head.addStretch()
        p.layout().addLayout(head)
        p.layout().addWidget(label("Tasas por tipo (mm removidos y minutos), prioridad y turnos.",
                                   color=T.TEXT_MUTE, size=11))
        cols = ["NOMBRE", "PROD mm", "PROD min", "DESB mm", "DESB min", "PRIORIDAD", "TURNOS"]
        hdr = QHBoxLayout()
        for c in cols:
            hdr.addWidget(label(c, color=T.TEXT_MUTE, size=9.5, weight=700), 1)
        p.layout().addLayout(hdr)
        for m in obtener_maquinas(cfg):
            tasas = m.get("tasas", {})
            prod = tasas.get("produccion", {})
            desb = tasas.get("desbaste", {})
            turnos = "24/7" if not m.get("turnos") else "personalizado"
            vals = [m["nombre"], prod.get("mm", ""), prod.get("tiempo_min", ""),
                    desb.get("mm", ""), desb.get("tiempo_min", ""),
                    m.get("prioridad", ""), turnos]
            row = QHBoxLayout()
            for i, v in enumerate(vals):
                cell = marco(QFrame(), bg=T.HOLE, border=T.BORDER_IN, radius=6)
                cl = QHBoxLayout(cell)
                cl.setContentsMargins(8, 6, 8, 6)
                color = T.TEXT if i == 0 else T.TEXT_2
                cl.addWidget(label(str(v), color=color, size=11.5,
                                   family=T.FONT_MONO if i != 5 else T.FONT_UI))
                row.addWidget(cell, 1)
            p.layout().addLayout(row)
        return p

    # ── Simulación + Guardar ───────────────────────────────────────────────────
    def _panel_sim_guardar(self, cfg):
        outer = QHBoxLayout()
        outer.setSpacing(18)
        p = panel(18)
        p.layout().addWidget(titulo_seccion("Parámetros de simulación", T.ORANGE, size=14))
        row = QHBoxLayout()
        row.addWidget(label("Máximo de iteraciones", color=T.TEXT_2, size=12.5), 1)
        self._inputs["max_iteraciones"] = _input(obtener_max_iteraciones(cfg), 120)
        row.addWidget(self._inputs["max_iteraciones"])
        p.layout().addLayout(row)
        outer.addWidget(p, 1)

        right = QHBoxLayout()
        right.setSpacing(14)
        btn = QPushButton("⤓ Guardar configuración")
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton{{background:{T.BLUE_BTN}; border:none; color:#fff; border-radius:9px;"
            f" padding:11px 20px; font-size:13px; font-weight:700;}} QPushButton:hover{{background:#1d4fd0;}}")
        btn.clicked.connect(self._guardar)
        right.addWidget(btn)
        self.feedback = label("✓ Configuración coherente", color=T.GREEN, size=12.5)
        right.addWidget(self.feedback)
        right.addStretch()
        rw = QWidget()
        rw.setStyleSheet("background:transparent;")
        rw.setLayout(right)
        outer.addWidget(rw, 1)
        return outer

    # ── Guardar ────────────────────────────────────────────────────────────────
    def _guardar(self):
        cfg = self.app.cfg
        try:
            cfgmod.set_config_global(
                cfg,
                diametro_maximo=float(self._inputs["diametro_maximo"].text()),
                diametro_minimo=float(self._inputs["diametro_minimo"].text()),
                tiempo_traslado_crc_min=float(self._inputs["tiempo_traslado_crc_min"].text()),
                cantidad_jaulas=int(self._inputs["cantidad_jaulas"].text()))
            cfgmod.set_sim(
                cfg,
                tiempo_enfriado=float(self._inputs["tiempo_enfriado_h"].text()),
                max_iteraciones=int(self._inputs["max_iteraciones"].text()),
                estrategia_seleccion=self._combo_sel.currentData(),
                estrategia_asignacion=self._combo_asg.currentData())
            for jnum, e_desde, e_hasta, e_perf in self._rango_inputs:
                perfil = e_perf.text().strip()
                perfil = None if perfil in ("—", "", "-") else perfil
                cfgmod.set_rango(cfg, jnum, float(e_desde.text()), float(e_hasta.text()), perfil)
            problemas = cfgmod.problemas_coherencia(cfg)
            if problemas:
                self.feedback.setText("⚠ " + problemas[0])
                self.feedback.setStyleSheet(
                    f"color:{T.RED}; font-size:12.5px; background:transparent;")
                return
            cfgmod.guardar_config(cfg)
            self.app.estrategia = self._combo_sel.currentData()
            self.feedback.setText("✓ Configuración guardada")
            self.feedback.setStyleSheet(f"color:{T.GREEN}; font-size:12.5px; background:transparent;")
        except Exception as e:  # noqa: BLE001
            self.feedback.setText(f"⚠ {e}")
            self.feedback.setStyleSheet(f"color:{T.RED}; font-size:12.5px; background:transparent;")
