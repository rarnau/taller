"""
Represents a rolling-mill stand.
"""
from datetime import datetime
from typing import List, Optional
from .cylinder import Cylinder


class Stand:
    """
    A stand that holds working cylinders and cylinders in the CRC buffer.

    A stand always operates with a complete pair of cylinders. If at a change
    there is no stock to form the pair, the stand becomes STOPPED (the line
    halts) until there is stock available to rebuild it.
    """

    def __init__(self, number: int):
        self.number = number
        self.working_cylinders: List[Cylinder] = []
        self.crc_cylinders: List[Cylinder] = []
        self.stopped: bool = False
        self.stopped_since: Optional[datetime] = None

    def __repr__(self):
        state = " STOPPED" if self.stopped else ""
        return f"Stand(J{self.number}, Work={len(self.working_cylinders)}, CRC={len(self.crc_cylinders)}{state})"
