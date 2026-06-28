"""
Model representing a physical cylinder in the workshop.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from .enums import CylinderState, GrindingType


class Cylinder:
    """
    Represents a cylinder with its diameter, state and location in the workshop.

    Main attributes:
      id                    Unique cylinder identifier.
      diameter              Current diameter in mm (decreases with each grind).
      original_diameter     Diameter it entered the system with.
      state                 Current state (CylinderState).
      stand                 Assigned stand number, or None if not in a stand.
      position              Position inside the stand (optional).
      mm_to_grind           Millimeters to remove on the next grind.
      current_grinding_type Pending or in-progress grinding type.
      history               List of recorded events for traceability.
    """

    def __init__(
        self,
        cylinder_id: str,
        diameter: float,
        state: CylinderState = CylinderState.AVAILABLE,
        stand: Optional[int] = None,
        position: Optional[int] = None
    ):
        self.id: str = cylinder_id
        self.diameter: float = diameter
        self.original_diameter: float = diameter
        self.state: CylinderState = state
        self.stand: Optional[int] = stand
        self.position: Optional[int] = position

        # In-progress grinding information
        self.current_machine: Optional[str] = None
        self.grinding_start: Optional[datetime] = None
        self.grinding_end: Optional[datetime] = None
        self.current_grinding_type: Optional[GrindingType] = None
        self.mm_to_grind: float = 0.0

        # Physical profile (convexity) of the cylinder: a "sticky" property that
        # only changes when ground (= profile of the chosen target stand). None =
        # no profile defined. target_stand marks the stand it was destined to when
        # grinding started (None = stock with no destination, e.g. the initial one).
        self.profile: Optional[str] = None
        self.target_stand: Optional[int] = None

        # Event history for traceability
        self.history: List[Dict[str, Any]] = []

    def record_event(self, time: datetime, event: str, detail: str = "") -> None:
        """Append an entry to the cylinder history."""
        self.history.append({
            "time": time,
            "event": event,
            "state": self.state.value,
            "diameter": self.diameter,
            "detail": detail
        })

    def grind(self, millimeters: float) -> None:
        """Reduce the cylinder diameter by the given amount."""
        if millimeters < 0:
            raise ValueError(f"millimeters must be >= 0, got: {millimeters}")
        self.diameter = round(self.diameter - millimeters, 2)

    def __repr__(self) -> str:
        return f"Cylinder({self.id}, D={self.diameter}, St={self.state.value})"
