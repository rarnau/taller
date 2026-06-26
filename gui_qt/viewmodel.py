"""Adaptadores: ``TallerCilindros`` + índice de snapshot → dicts por vista.

Espejo de la lógica ``_sn2interno`` / ``renderVals`` del HTML, pero leyendo los
``Snapshot`` reales del motor (``modelos/eventos.py``). Centraliza el mapeo de
estado→color para que las vistas sean puramente de presentación.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from modelos.enums import EstadoCilindro

from . import theme as T


def _fmt_reloj(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")


def _chip(cid: str, d: Any, estado: str) -> Dict[str, Any]:
    """Dict de chip {id, sub, color, txt} para un cilindro en cierto estado."""
    try:
        sub = f"{float(d):.1f}"
    except (TypeError, ValueError):
        sub = str(d)
    return {"id": cid, "sub": sub,
            "color": T.COL_ESTADO.get(estado, T.TEXT_MUTE),
            "txt": T.TXT_ESTADO.get(estado, "#fff")}


class TallerVM:
    """Vista-modelo de una simulación: precomputa lo estático y sirve por snapshot."""

    def __init__(self, taller, estrategia_label: str = "Mayor diámetro"):
        self.taller = taller
        self.estrategia_label = estrategia_label
        self.snaps = taller.snapshots if taller is not None else []
        self.N = len(self.snaps)

        # Orden de máquinas y jaulas
        self.maq_nombres: List[str] = list(taller.maquinas.keys()) if taller else []
        self.ss_por_jaula: List[tuple] = []   # [(jaula_num, nombre_ss)]
        if taller is not None:
            for ss in sorted(taller.lista_substocks, key=lambda s: s.jaula_asignada):
                self.ss_por_jaula.append((ss.jaula_asignada, ss.nombre))

        # Máximo de disponibles (para escalar las barras), e índices de inicio de PARADA
        self.max_disp = 1
        self.parada_marks: List[int] = []
        prev_parada = 0
        for i, s in enumerate(self.snaps):
            disp_total = sum(s.disponibles_por_substock.values())
            self.max_disp = max(self.max_disp, max([1] + list(s.disponibles_por_substock.values())))
            np = len(s.jaulas_paradas)
            if np > 0 and prev_parada == 0:
                self.parada_marks.append(i)
            prev_parada = np

    # ── Acceso por snapshot ───────────────────────────────────────────────────
    def reloj(self, i: int) -> str:
        if not self.snaps:
            return "--:--"
        return _fmt_reloj(self.snaps[max(0, min(i, self.N - 1))].tiempo)

    def horizonte_h(self, i: int) -> float:
        if not self.snaps:
            return 0.0
        t0 = self.snaps[0].tiempo
        t = self.snaps[max(0, min(i, self.N - 1))].tiempo
        return (t - t0).total_seconds() / 3600

    def jaulas(self, i: int) -> List[Dict[str, Any]]:
        s = self.snaps[i]
        out = []
        for jid in sorted(s.detalle_jaulas.keys()):
            parada = jid in s.jaulas_paradas
            trab = [_chip(c["id"], c.get("d", ""), "Trabajando")
                    for c in s.detalle_jaulas.get(jid, [])]
            crc = [_chip(c["id"], c.get("d", ""), "CRC")
                   for c in s.detalle_crc.get(jid, [])]
            out.append({
                "n": f"J{jid}", "num": jid, "trab": trab, "crc": crc,
                "parada": parada,
                "trab_border": T.RED if parada else T.BORDER,
                "trab_bw": 2 if parada else 1,
                "trab_label": "⚠ PARADA" if parada else "TRABAJANDO",
                "trab_label_color": T.RED if parada else T.BLUE,
            })
        return out

    def machines(self, i: int) -> List[Dict[str, Any]]:
        s = self.snaps[i]
        out = []
        for nombre in self.maq_nombres:
            det = s.detalle_maquinas.get(nombre)
            operativa = s.detalle_maquinas_operativa.get(nombre, True)
            busy = det is not None
            if busy:
                pct = round(float(det.get("progreso", 0)))
                sub = f"{det.get('id', '')} · {float(det.get('d', 0)):.1f} mm"
                color = T.PURPLE
                status = f"Rectificando · {pct}%"
            else:
                pct = 0
                if operativa:
                    sub, color, status = "● Libre · operativa", T.GREEN, "Libre · operativa"
                else:
                    sub, color, status = "⏸ Fuera de turno", T.RED, "Fuera de turno"
            out.append({"name": nombre, "sub": sub, "sub_color": color,
                        "pct": pct, "bar_color": color, "border": color,
                        "status": status, "busy": busy, "operativa": operativa})
        return out

    def cola(self, i: int) -> List[Dict[str, Any]]:
        s = self.snaps[i]
        cola = [_chip(c["id"], c.get("d", ""), "A rectificar")
                for c in s.detalle_cola_rectificado]
        if cola:
            cola[0] = {**cola[0], "color": T.ORANGE, "txt": "#1a1206"}
        return cola

    def enfriando(self, i: int) -> List[Dict[str, Any]]:
        s = self.snaps[i]
        return [_chip(c["id"], c.get("d", ""), "Enfriando")
                for c in s.detalle_enfriando]

    def disp_bars(self, i: int) -> List[Dict[str, Any]]:
        s = self.snaps[i]
        out = []
        for jnum, ssname in self.ss_por_jaula:
            v = s.disponibles_por_substock.get(ssname, 0)
            out.append({"n": f"J{jnum}", "val": v,
                        "hpct": round(v / self.max_disp * 100) if self.max_disp else 0,
                        "color": T.RED if v < 4 else T.GREEN})
        return out

    def parada_count(self, i: int) -> int:
        return len(self.snaps[i].jaulas_paradas)

    def total_cil(self) -> int:
        return len(self.taller.cilindros) if self.taller else 0

    def alertas_count(self, i: int) -> int:
        return 1 if self.snaps[i].jaulas_paradas else 0
