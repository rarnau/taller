"""Selection strategies for the grinding queue.

Each strategy is an object with: `key` (id for GUI/CLI/persistence), `label`
(text to display) and `select(queue, machine)`, which receives the queue ALREADY
filtered by the machine priority and returns the cylinder to grind. To add a new
strategy: subclass SelectionStrategy and register it in SELECTION_STRATEGIES; the
GUI and the CLI read it from there.

Note: the `key` values (registry keys) stay in Spanish on purpose — they are
persisted config values / CLI choices.
"""
from typing import Dict, List, Optional

from .cylinder import Cylinder
from .enums import CylinderState, GrindingType
from .machine import GrindingMachine


class SelectionStrategy:
    """Strategy to pick a cylinder from the grinding queue."""

    key: str = ""
    label: str = ""

    def select(self, queue: List[Cylinder], machine: Optional[GrindingMachine]) -> Cylinder:
        raise NotImplementedError


class _LargestDiameter(SelectionStrategy):
    key, label = "mayor_diametro", "Mayor diámetro"

    def select(self, queue, machine):
        return max(queue, key=lambda c: c.diameter)


class _SmallestDiameter(SelectionStrategy):
    key, label = "menor_diametro", "Menor diámetro"

    def select(self, queue, machine):
        return min(queue, key=lambda c: c.diameter)


class _Fifo(SelectionStrategy):
    key, label = "fifo", "FIFO (orden de llegada)"

    def select(self, queue, machine):
        return queue[0]


class _LeastRoughingMmFifoProduction(SelectionStrategy):
    """Least mm to grind when the machine prioritizes roughing; FIFO otherwise."""

    key = "menor_mm_desb_fifo_prod"
    label = "Menor mm desbaste / FIFO producción"

    def select(self, queue, machine):
        if machine is not None and machine.default_priority == GrindingType.ROUGHING:
            return min(queue, key=lambda c: c.mm_to_grind)
        return queue[0]


SELECTION_STRATEGIES: Dict[str, SelectionStrategy] = {
    e.key: e for e in (
        _LargestDiameter(),
        _SmallestDiameter(),
        _Fifo(),
        _LeastRoughingMmFifoProduction(),
    )
}
DEFAULT_STRATEGY = "fifo"


# ── Target-stand assignment strategies ───────────────────────────────────────
#
# When a grind starts the engine decides which stand the cylinder is destined to
# (and therefore which profile is cut). The strategy receives the stands ALREADY
# filtered by admissible diameter (hard pre-filter) and picks one of them. To add
# a new strategy: subclass AssignmentStrategy and register it in
# ASSIGNMENT_STRATEGIES; the GUI and the CLI read it from there.

# States of a cylinder "en route" to a stand (committed but not yet installed).
_EN_ROUTE_STATES = (
    CylinderState.COOLING,
    CylinderState.TO_GRIND,
    CylinderState.GRINDING,
    CylinderState.AVAILABLE,
    CylinderState.CRC,
)


class AssignmentStrategy:
    """Strategy to assign the target stand when a grind starts."""

    key: str = ""
    label: str = ""

    def assign(self, cylinder: Cylinder, candidate_stands: List[int], workshop) -> int:
        raise NotImplementedError


class _MostNeededStand(AssignmentStrategy):
    """Among the candidates (already admissible by diameter), the most deficient.

    Prioritizes stopped stands; then the largest stock deficit
    (``_BUFFER_CRC_SIZE`` − CRC − cylinders already en route);
    ties broken by stand number (lowest first) to stay deterministic.
    """

    key, label = "jaula_mas_necesitada", "Jaula más necesitada"

    def assign(self, cylinder, candidate_stands, workshop):
        # The deficit is buffer − (CRC + en_route); the "buffer" term is the same
        # for all candidates, so sorting by lowest (CRC + en_route) is equivalent
        # to the largest deficit (the most needed), independent of the buffer.
        def _order(j: int):
            stand = workshop.stands[j]
            stopped = 0 if getattr(stand, "stopped", False) else 1  # stopped first
            en_route = sum(
                1 for c in workshop.cylinders.values()
                if c.target_stand == j and c.state in _EN_ROUTE_STATES
            )
            committed = len(stand.crc_cylinders) + en_route
            return (stopped, committed, j)  # smallest tuple = most needed

        return min(candidate_stands, key=_order)


ASSIGNMENT_STRATEGIES: Dict[str, AssignmentStrategy] = {
    e.key: e for e in (
        _MostNeededStand(),
    )
}
DEFAULT_ASSIGNMENT_STRATEGY = "jaula_mas_necesitada"
