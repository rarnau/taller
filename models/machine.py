"""
Model of a cylinder grinding machine.
"""
from bisect import bisect_right
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from .enums import CylinderState, GrindingType
from .cylinder import Cylinder


class GrindingMachine:
    """
    Simulates the behavior of a grinder: capacity, process times and a history
    of the jobs performed.

    Grinding rates:
      Each pass type (produccion/desbaste) has its own rate in mm/min. If the
      rate is 0 or the type is not configured, compute_process_time returns
      float('inf'), meaning that pass type is not possible.
    """

    def __init__(self, name: str):
        self.name: str = name
        self.busy: bool = False
        self.current_cylinder: Optional[Cylinder] = None
        self.grinding_end_time: Optional[datetime] = None

        # {type_str: {"mm": float, "t_min": float, "rate": float}}
        self.grinding_rates: Dict[str, Dict[str, float]] = {}
        self.default_priority: GrindingType = GrindingType.PRODUCTION

        self.work_history: List[Dict[str, Any]] = []
        self.total_busy_min: float = 0.0

        # Work schedule: weekly 7×24 boolean grid (grid[weekday][hour]). None =
        # always operative (24/7), which reproduces the historical behavior
        # exactly. See models/shifts.py.
        self.operating_grid: Optional[List[List[bool]]] = None
        # Work minutes (operative time) of the in-progress grind; used as the
        # denominator for the snapshot progress.
        self.current_work_minutes: float = 0.0
        # Flag to avoid duplicating wake-up events (REANUDAR_MAQUINA).
        self._wakeup_scheduled: bool = False

        # Progress of the in-progress grind. With shifts the milestones
        # (hour_boundary, accumulated_operative_minutes) are precomputed once in
        # start_grinding and per-snapshot progress is resolved by bisect
        # (O(log h)) instead of walking the grid each time. With a 24/7 grid the
        # milestones stay None and progress is plain wall-clock.
        self._grinding_start: Optional[datetime] = None
        self._milestones_t: Optional[List[datetime]] = None
        self._milestones_min: Optional[List[float]] = None

    def configure_rate(self, pass_type: str, mm_removed: float, time_minutes: float) -> None:
        """Register the grinding speed for a pass type."""
        rate = mm_removed / time_minutes if time_minutes > 0 else 0.0
        self.grinding_rates[pass_type] = {
            "mm": mm_removed,
            "t_min": time_minutes,
            "rate": rate
        }

    def can_grind(self, pass_type: str) -> bool:
        """True if the machine has a usable rate (rate > 0) for that pass type.

        It is the predicate backing the ``inf`` sentinel of
        :meth:`compute_process_time`: the assignment uses it to avoid handing a
        machine a job whose type it cannot run.
        """
        cfg = self.grinding_rates.get(pass_type)
        return cfg is not None and cfg["rate"] > 0

    def compute_process_time(self, mm_to_grind: float, pass_type: str) -> float:
        """
        Compute how many minutes grinding the given amount will take.

        Returns float('inf') if the type is not configured or its rate is 0,
        which will exclude this job from the assignment.
        """
        if not self.can_grind(pass_type):
            return float("inf")
        return mm_to_grind / self.grinding_rates[pass_type]["rate"]

    # ── Work schedule (shifts) ──────────────────────────────────────────────

    def is_operative(self, dt: datetime) -> bool:
        """Whether the machine is in an operative shift at the given instant."""
        if self.operating_grid is None:
            return True
        return self.operating_grid[dt.weekday()][dt.hour]

    def operative_minutes_between(self, t0: datetime, t1: datetime) -> float:
        """Operative minutes accumulated over the interval [t0, t1).

        With grid None (24/7) it returns the wall-clock minutes, identical to the
        historical behavior.
        """
        if t1 <= t0:
            return 0.0
        if self.operating_grid is None:
            return (t1 - t0).total_seconds() / 60.0

        total = 0.0
        t = t0
        while t < t1:
            hour_end = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            segment_end = min(hour_end, t1)
            if self.operating_grid[t.weekday()][t.hour]:
                total += (segment_end - t).total_seconds() / 60.0
            t = segment_end
        return total

    def _build_progress_milestones(
        self, start: datetime, total_min: float
    ) -> Tuple[List[datetime], List[float]]:
        """Milestone table (hour_boundary, accumulated_operative_minutes).

        Walks ``start → end`` hour by hour consuming only operative hours,
        returning two parallel lists: the hour boundaries and the operative
        minutes accumulated *up to* each boundary. The first entry is
        ``(start, 0.0)`` and the last ``(end, total_min)``, where ``end`` is the
        wall-clock instant at which ``total_min`` of operative time is completed.
        Each segment ``[milestones_t[i], milestones_t[i+1])`` falls entirely
        within one grid hour, so its operativity is constant. It is the single
        source of the operative end (see ``compute_operative_end``). Only
        meaningful with ``operating_grid is not None`` and ``total_min > 0``.
        """
        milestones_t: List[datetime] = [start]
        milestones_min: List[float] = [0.0]
        remaining = total_min
        accumulated = 0.0
        t = start
        limit = start + timedelta(days=366)  # anti-loop safety bound
        while remaining > 0 and t < limit:
            hour_end = t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            if self.operating_grid[t.weekday()][t.hour]:
                avail = (hour_end - t).total_seconds() / 60.0
                if avail >= remaining:
                    accumulated += remaining
                    milestones_t.append(t + timedelta(minutes=remaining))
                    milestones_min.append(accumulated)
                    return milestones_t, milestones_min
                accumulated += avail
                remaining -= avail
            milestones_t.append(hour_end)
            milestones_min.append(accumulated)
            t = hour_end
        return milestones_t, milestones_min

    def compute_operative_end(self, start: datetime, op_minutes: float) -> datetime:
        """Wall-clock instant at which ``op_minutes`` of operative time complete.

        Advances from ``start`` consuming only operative hours and skipping the
        non-operative gaps (the cylinder stays mounted and resumes where it
        stopped). With grid None it returns ``start + op_minutes`` (historical
        behavior). The machine is assumed to be operative at ``start`` (work is
        only assigned in that case), so it always makes progress.
        """
        if self.operating_grid is None or op_minutes <= 0:
            return start + timedelta(minutes=op_minutes)
        return self._build_progress_milestones(start, op_minutes)[0][-1]

    def operative_progress(self, time: datetime) -> float:
        """Operative minutes consumed of the in-progress grind up to ``time``.

        O(1) with no work or with a 24/7 grid (plain wall-clock); O(log h) with
        shifts, resolved by bisect over the milestones precomputed in start_grinding.
        """
        if self._grinding_start is None:
            return 0.0
        if self.operating_grid is None or self._milestones_t is None:
            return max(0.0, (time - self._grinding_start).total_seconds() / 60.0)

        idx = bisect_right(self._milestones_t, time) - 1
        if idx < 0:
            return 0.0
        consumed = self._milestones_min[idx]
        base = self._milestones_t[idx]
        if time > base and self.operating_grid[base.weekday()][base.hour]:
            consumed += (time - base).total_seconds() / 60.0
        return min(consumed, self._milestones_min[-1])

    def next_opening(self, since: datetime) -> Optional[datetime]:
        """Next operative instant from ``since`` (None if never operative)."""
        if self.operating_grid is None or self.is_operative(since):
            return since
        t = since.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        limit = since + timedelta(days=8)  # a week is enough to cover the cycle
        while t < limit:
            if self.operating_grid[t.weekday()][t.hour]:
                return t
            t += timedelta(hours=1)
        return None

    def start_grinding(
        self,
        cylinder: Cylinder,
        current_time: datetime,
        grinding_type: GrindingType,
        mm: float,
        profile: Optional[str] = None
    ) -> None:
        """Start the grinding process for a cylinder.

        ``profile`` is the profile (convexity) to cut, decided by the engine (the
        machine only applies it physically). ``None`` ⇒ the profile is unchanged.
        """
        duration_minutes = self.compute_process_time(mm, grinding_type.value)
        self.busy = True
        self.current_cylinder = cylinder
        self.current_work_minutes = duration_minutes
        self._grinding_start = current_time
        # The end accounts for non-operative shifts: if the machine stops mid-job,
        # the cylinder resumes where it stopped when the shift reopens. With shifts
        # the milestones are precomputed once (single source of the end); with a
        # 24/7 grid the end is the plain sum and progress is plain wall-clock.
        if self.operating_grid is None or duration_minutes <= 0:
            self._milestones_t = None
            self._milestones_min = None
            self.grinding_end_time = current_time + timedelta(minutes=duration_minutes)
        else:
            self._milestones_t, self._milestones_min = self._build_progress_milestones(
                current_time, duration_minutes)
            self.grinding_end_time = self._milestones_t[-1]

        cylinder.state = CylinderState.GRINDING
        cylinder.current_machine = self.name
        cylinder.grinding_start = current_time
        cylinder.grinding_end = self.grinding_end_time
        cylinder.current_grinding_type = grinding_type
        cylinder.mm_to_grind = mm
        if profile is not None:
            cylinder.profile = profile  # the machine physically cuts the decided profile

        cylinder.record_event(
            current_time,
            f"Inicio rectificado {grinding_type.value} en {self.name}",
            f"D{cylinder.diameter}->{round(cylinder.diameter - mm, 2)} ({duration_minutes:.0f} min)"
        )

        self.work_history.append({
            "cylinder_id": cylinder.id,
            "start": current_time,
            "end": self.grinding_end_time,
            "type": grinding_type.value,
            "mm": mm,
            "duration": duration_minutes
        })
        self.total_busy_min += duration_minutes

    def finish_grinding(self, current_time: datetime) -> Optional[Cylinder]:
        """Finish the current process, update the cylinder and free the machine."""
        if not self.busy or not self.current_cylinder:
            return None

        cylinder = self.current_cylinder
        cylinder.grind(cylinder.mm_to_grind)
        cylinder.state = CylinderState.AVAILABLE
        cylinder.current_machine = None

        # The grind was already applied above; the pending type/mm are cleared so
        # the AVAILABLE cylinder does not carry over data from the previous pass.
        # The next CAMBIO reassigns them before it is ground again, so this alters
        # no logic (it is only state hygiene).
        cylinder.current_grinding_type = None
        cylinder.mm_to_grind = 0.0

        cylinder.record_event(
            current_time,
            f"Fin rectificado en {self.name}",
            f"Nuevo diámetro: {cylinder.diameter} mm"
        )

        self.busy = False
        self.current_cylinder = None
        self.grinding_end_time = None
        self._grinding_start = None
        self._milestones_t = None
        self._milestones_min = None

        return cylinder
