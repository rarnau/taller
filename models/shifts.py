"""
Work-shift schedule of the grinding machines.

A **pure** domain module (no simulation state, no GUI dependencies): it defines
the daily shifts, their expansion into a weekly hourly grid and the preset/parse
utilities shared by the engine, the CLI and the GUI.

Shift convention (3 shifts of 8 h):
  - T1: 06–14
  - T2: 14–22
  - T3: 22–06 next day

The night shift (T3) **belongs to the day it starts on**: "Saturday T3" covers
Saturday 22:00 → Sunday 06:00. So, when expanding, T3 writes hours 22–23 of the
day and 00–05 of the next day (with week wraparound: Sunday T3 → Monday 00–05).

Persisted representation (``turnos``): a dict keyed by weekday with a list of 3
booleans [T1, T2, T3]::

    {"lun": [True, True, True], ..., "sab": [True, True, False], "dom": [...]}

An absent / ``None`` ``turnos`` means **always operative** (24/7); the engine
leaves the grid at ``None`` and never calls ``expand``.

The expanded grid (``expand``) is a 7×24 boolean matrix indexed by
``[day][hour]`` with ``day`` = ``datetime.weekday()`` (0 = Monday). It is the
basis on which a random fraction of hours could later be turned off to model the
machine failure rate.

Note: the day keys ``"lun".."dom"`` and the preset keys (``"24x7"`` …) stay in
Spanish/compact form on purpose — they are persisted config keys / CLI choices.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# Hours [start, end) of each shift; end <= start means it crosses midnight.
SHIFTS = [(6, 14), (14, 22), (22, 6)]
SHIFT_LABELS = ("T1 06–14", "T2 14–22", "T3 22–06")
NUM_SHIFTS = len(SHIFTS)

# Index 0 = Monday, to align with datetime.weekday(). Keys stay Spanish (persisted).
DAYS = ["lun", "mar", "mie", "jue", "vie", "sab", "dom"]
DAY_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

Shifts = Dict[str, List[bool]]
Grid = List[List[bool]]


def _rows(rows: List[List[bool]]) -> Shifts:
    """Build a shifts dict from 7 rows of 3 booleans."""
    return {DAYS[i]: list(rows[i]) for i in range(7)}


PRESETS: Dict[str, Shifts] = {
    "24x7": _rows([[True] * 3 for _ in range(7)]),
    "off": _rows([[False] * 3 for _ in range(7)]),
    "lv3": _rows([[True] * 3 if i < 5 else [False] * 3 for i in range(7)]),
    # 3 squads: all shifts except Saturday T3 and the whole Sunday.
    "3escuadras": _rows([[True, True, True]] * 5 + [[True, True, False], [False, False, False]]),
}
PRESET_LABELS = {"24x7": "24/7", "off": "Apagada", "lv3": "L–V 3 turnos",
                 "3escuadras": "3 escuadras"}


def normalize(shifts: Optional[Shifts]) -> Shifts:
    """Return a complete dict (7 days × 3 booleans), tolerating partial inputs.

    ``None`` is interpreted as 24/7 (all shifts active).
    """
    if shifts is None:
        return _rows([[True] * NUM_SHIFTS for _ in range(7)])
    out: Shifts = {}
    for day in DAYS:
        values = shifts.get(day) or []
        row = [bool(values[i]) if i < len(values) else False for i in range(NUM_SHIFTS)]
        out[day] = row
    return out


def expand(shifts: Optional[Shifts]) -> Grid:
    """Expand the shift config into a 7×24 weekly hourly boolean grid.

    ``grid[day][hour]`` is ``True`` if the machine is operative that hour. The
    shift crossing midnight writes the final hours into the next day.
    """
    t = normalize(shifts)
    grid: Grid = [[False] * 24 for _ in range(7)]
    for d, day in enumerate(DAYS):
        for si, active in enumerate(t[day]):
            if not active:
                continue
            start, end = SHIFTS[si]
            if end > start:
                for h in range(start, end):
                    grid[d][h] = True
            else:  # crosses midnight: rest of the day + early hours of the next
                for h in range(start, 24):
                    grid[d][h] = True
                for h in range(0, end):
                    grid[(d + 1) % 7][h] = True
    return grid


def is_full(shifts: Optional[Shifts]) -> bool:
    """``True`` if the schedule is equivalent to 24/7 (all shifts active)."""
    t = normalize(shifts)
    return all(all(t[d]) for d in DAYS)


def parse_compact(s: str) -> Shifts:
    """Parse the compact shift representation used by the CLI.

    Accepts 7 groups of 3 digits 0/1 (lun→dom), separated by spaces or commas,
    or a single contiguous string of 21 digits. E.g. ``"111 111 111 111 111 110 000"``.
    """
    s = (s or "").strip()
    tokens = re.split(r"[\s,]+", s) if s else []
    if len(tokens) == 1 and len(tokens[0]) == 21:
        bits = tokens[0]
        tokens = [bits[i:i + 3] for i in range(0, 21, 3)]
    if len(tokens) != 7:
        raise ValueError("Se esperaban 7 grupos de turnos (lun..dom), p. ej. "
                         "'111 111 111 111 111 110 000'.")
    shifts: Shifts = {}
    for d, tok in enumerate(tokens):
        if len(tok) != NUM_SHIFTS or any(c not in "01" for c in tok):
            raise ValueError(f"Grupo de turno inválido: '{tok}' (deben ser 3 dígitos 0/1).")
        shifts[DAYS[d]] = [c == "1" for c in tok]
    return shifts


def format_compact(shifts: Optional[Shifts]) -> str:
    """Serialize the shifts to the compact format of :func:`parse_compact`."""
    t = normalize(shifts)
    return " ".join("".join("1" if x else "0" for x in t[d]) for d in DAYS)


# ── Shift boundaries (for the change generator) ──────────────────────────────
#
# The full teardown/change of a pair coincides with the **end of a shift**, and
# the mount of the new pair with the **first hour of the next operative shift**.
# These two functions are pure (they operate on the grid, with no machine state)
# and are shared by the ``Programa_Cambios`` generator.

_BOUNDARIES_SET = {start for start, _ in SHIFTS}  # {6, 14, 22}: shift start hours


def next_shift_boundary(dt: datetime) -> datetime:
    """Lowest shift boundary (06/14/22) ``>= dt`` → teardown instant.

    If ``dt`` already lands exactly on a boundary (hour 06/14/22 with no
    minutes), it is returned as-is; otherwise it is rounded up to the next one.
    """
    if (dt.hour in _BOUNDARIES_SET and dt.minute == 0
            and dt.second == 0 and dt.microsecond == 0):
        return dt
    t = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while t.hour not in _BOUNDARIES_SET:
        t += timedelta(hours=1)
    return t


def next_operative_start(grid: Optional[Grid], dt: datetime) -> Optional[datetime]:
    """First **operative** hour of the regime ``>= dt`` → mount instant.

    Same logic as ``GrindingMachine.next_opening`` but as a pure function over
    the grid. With ``grid is None`` (24/7) it returns ``dt`` unchanged; returns
    ``None`` if the regime is never operative.
    """
    if grid is None or grid[dt.weekday()][dt.hour]:
        return dt
    t = dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    limit = dt + timedelta(days=8)  # a week covers the full cycle
    while t < limit:
        if grid[t.weekday()][t.hour]:
            return t
        t += timedelta(hours=1)
    return None


def summary(shifts: Optional[Shifts]) -> str:
    """Short human-readable label of the shift schedule (for GUI/CLI)."""
    if shifts is None or is_full(shifts):
        return "24/7"
    t = normalize(shifts)
    total = sum(sum(1 for x in t[d] if x) for d in DAYS)
    if total == 0:
        return "Apagada"
    active_days = [d for d in DAYS if any(t[d])]
    patterns = {tuple(t[d]) for d in active_days}
    if len(patterns) == 1:  # all active days share the same pattern
        per_day = sum(patterns.pop())
        return f"{len(active_days)}d × {per_day}t"
    return f"{total}/21 turnos"
