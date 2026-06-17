"""
Esquema de trabajo por turnos de las máquinas rectificadoras.

Módulo de dominio **puro** (sin estado de simulación ni dependencias de GUI):
define los turnos diarios, su expansión a una grilla horaria semanal y las
utilidades de presets/parseo que comparten el motor, la CLI y la GUI.

Convención de turnos (3 turnos de 8 h):
  - T1: 06–14
  - T2: 14–22
  - T3: 22–06 del día siguiente

El turno nocturno (T3) **pertenece al día en que arranca**: "sábado T3" cubre
sábado 22:00 → domingo 06:00. Por eso, al expandir, T3 escribe las horas 22–23
del día y 00–05 del día siguiente (con wraparound de semana: domingo T3 → lunes
00–05).

Representación persistida (``turnos``): dict por día de semana con una lista de
3 booleanos [T1, T2, T3]::

    {"lun": [True, True, True], ..., "sab": [True, True, False], "dom": [...]}

``turnos`` ausente / ``None`` significa **siempre operativa** (24/7); el motor
deja la grilla en ``None`` y no llama a ``expandir``.

La grilla expandida (``expandir``) es una matriz 7×24 de booleanos indexada por
``[dia][hora]`` con ``dia`` = ``datetime.weekday()`` (0 = lunes). Es la base
sobre la que en el futuro se podrá apagar un porcentaje aleatorio de horas para
modelar la tasa de falla de las máquinas.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# Horas [inicio, fin) de cada turno; fin <= inicio indica cruce de medianoche.
TURNOS = [(6, 14), (14, 22), (22, 6)]
TURNO_LABELS = ("T1 06–14", "T2 14–22", "T3 22–06")
NUM_TURNOS = len(TURNOS)

# Índice 0 = lunes, para alinear con datetime.weekday().
DIAS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
DIAS_NOMBRES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

Turnos = Dict[str, List[bool]]
Grilla = List[List[bool]]


def _filas(rows: List[List[bool]]) -> Turnos:
    """Construye un dict de turnos a partir de 7 filas de 3 booleanos."""
    return {DIAS[i]: list(rows[i]) for i in range(7)}


PRESETS: Dict[str, Turnos] = {
    "24x7": _filas([[True] * 3 for _ in range(7)]),
    "off": _filas([[False] * 3 for _ in range(7)]),
    "lv3": _filas([[True] * 3 if i < 5 else [False] * 3 for i in range(7)]),
}
PRESET_LABELS = {"24x7": "24/7", "off": "Apagada", "lv3": "L–V 3 turnos"}


def normalizar(turnos: Optional[Turnos]) -> Turnos:
    """Devuelve un dict completo (7 días × 3 booleanos), tolerando entradas parciales.

    ``None`` se interpreta como 24/7 (todos los turnos activos).
    """
    if turnos is None:
        return _filas([[True] * NUM_TURNOS for _ in range(7)])
    out: Turnos = {}
    for dia in DIAS:
        valores = turnos.get(dia) or []
        fila = [bool(valores[i]) if i < len(valores) else False for i in range(NUM_TURNOS)]
        out[dia] = fila
    return out


def expandir(turnos: Optional[Turnos]) -> Grilla:
    """Expande la config de turnos a una grilla horaria semanal 7×24 de booleanos.

    ``grilla[dia][hora]`` es ``True`` si la máquina está operativa esa hora.
    El turno que cruza medianoche escribe las horas finales en el día siguiente.
    """
    t = normalizar(turnos)
    grilla: Grilla = [[False] * 24 for _ in range(7)]
    for d, dia in enumerate(DIAS):
        for si, activo in enumerate(t[dia]):
            if not activo:
                continue
            ini, fin = TURNOS[si]
            if fin > ini:
                for h in range(ini, fin):
                    grilla[d][h] = True
            else:  # cruza medianoche: resto del día + madrugada del siguiente
                for h in range(ini, 24):
                    grilla[d][h] = True
                for h in range(0, fin):
                    grilla[(d + 1) % 7][h] = True
    return grilla


def es_completo(turnos: Optional[Turnos]) -> bool:
    """``True`` si el esquema equivale a 24/7 (todos los turnos activos)."""
    t = normalizar(turnos)
    return all(all(t[d]) for d in DIAS)


def parse_compacto(s: str) -> Turnos:
    """Parsea la representación compacta de turnos usada por la CLI.

    Acepta 7 grupos de 3 dígitos 0/1 (lun→dom), separados por espacios o comas,
    o una única cadena contigua de 21 dígitos. Ej: ``"111 111 111 111 111 110 000"``.
    """
    s = (s or "").strip()
    tokens = re.split(r"[\s,]+", s) if s else []
    if len(tokens) == 1 and len(tokens[0]) == 21:
        bits = tokens[0]
        tokens = [bits[i:i + 3] for i in range(0, 21, 3)]
    if len(tokens) != 7:
        raise ValueError("Se esperaban 7 grupos de turnos (lun..dom), p. ej. "
                         "'111 111 111 111 111 110 000'.")
    turnos: Turnos = {}
    for d, tok in enumerate(tokens):
        if len(tok) != NUM_TURNOS or any(c not in "01" for c in tok):
            raise ValueError(f"Grupo de turno inválido: '{tok}' (deben ser 3 dígitos 0/1).")
        turnos[DIAS[d]] = [c == "1" for c in tok]
    return turnos


def format_compacto(turnos: Optional[Turnos]) -> str:
    """Serializa los turnos al formato compacto de :func:`parse_compacto`."""
    t = normalizar(turnos)
    return " ".join("".join("1" if x else "0" for x in t[d]) for d in DIAS)


def resumen(turnos: Optional[Turnos]) -> str:
    """Etiqueta corta legible del esquema de turnos (para GUI/CLI)."""
    if turnos is None or es_completo(turnos):
        return "24/7"
    t = normalizar(turnos)
    total = sum(sum(1 for x in t[d] if x) for d in DIAS)
    if total == 0:
        return "Apagada"
    dias_activos = [d for d in DIAS if any(t[d])]
    patrones = {tuple(t[d]) for d in dias_activos}
    if len(patrones) == 1:  # todos los días activos comparten el mismo patrón
        por_dia = sum(patrones.pop())
        return f"{len(dias_activos)}d × {por_dia}t"
    return f"{total}/21 turnos"
