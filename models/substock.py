"""
Represents a group of cylinders within a specific diameter range.

Naming convention:
  - 'upper' = upper bound of the range (larger value, e.g. 533 mm)
  - 'lower' = lower bound of the range (smaller value, e.g. 520 mm)
  A cylinder belongs to the SubStock if: lower < diameter <= upper
"""


class SubStock:
    """
    Defines a diameter range (SubStock) assigned to a stand.

    'upper' must be greater than or equal to 'lower'. A diameter `d` belongs to
    this SubStock if: lower < d <= upper.
    """

    def __init__(self, name: str, substock_id: int, upper: float, lower: float,
                 assigned_stand: int = 0, profile=None):
        if upper < lower:
            raise ValueError(
                f"SubStock '{name}': 'upper' ({upper}) must be >= 'lower' ({lower}). "
                "'upper' is the upper bound and 'lower' the lower bound."
            )
        self.name = name
        self.substock_id = substock_id
        self.upper = upper      # upper bound (larger diameter, inclusive)
        self.lower = lower      # lower bound (smaller diameter, exclusive)
        self.assigned_stand = assigned_stand
        self.profile = profile  # profile (convexity) required by the stand; None = any

    def contains_diameter(self, diameter: float) -> bool:
        """Return True if the diameter belongs to the range (lower, upper]."""
        return self.lower < diameter <= self.upper

    def __repr__(self) -> str:
        return f"SubStock({self.name}, {self.lower}-{self.upper} mm)"
