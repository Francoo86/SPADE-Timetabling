from dataclasses import dataclass
from typing import List, Dict

from ..static.agent_enums import Day

@dataclass
class ConfirmedAssignment:
    """Represents a confirmed classroom assignment."""
    day: Day
    block: int
    classroom_code: str
    satisfaction: int
    
    def get_block(self) -> int:
        """Get the assigned block number."""
        return self.block
    
    def get_day(self) -> Day:
        """Get the assigned day."""
        return self.day
    
    def get_classroom_code(self) -> str:
        """Get the assigned classroom code."""
        return self.classroom_code
    
    def get_satisfaction(self) -> int:
        """Get the satisfaction score for the assignment."""
        return self.satisfaction

    def to_dict(self) -> Dict:
        """Convert the assignment to a dictionary for serialization."""
        return {
            "day": self.day.name,
            "block": self.block,
            "classroom_code": self.classroom_code,
            "satisfaction": self.satisfaction
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ConfirmedAssignment":
        """Create a ConfirmedAssignment instance from a dictionary."""
        return cls(
            day=Day[data["day"]],
            block=data["block"],
            classroom_code=data["classroom_code"],
            satisfaction=data["satisfaction"]
        )

class BatchAssignmentConfirmation:
    """Represents a batch of confirmed classroom assignments."""

    def __init__(self, confirmed_assignments: List[ConfirmedAssignment]):
        """
        Initialize a BatchAssignmentConfirmation.

        Args:
            confirmed_assignments: List of ConfirmedAssignment objects
        """
        self.confirmed_assignments = confirmed_assignments

    def get_confirmed_assignments(self) -> List[ConfirmedAssignment]:
        """Get the list of confirmed assignments."""
        return self.confirmed_assignments

    def to_dict(self) -> Dict:
        """Convert the batch confirmation to a dictionary for serialization."""
        return {
            "confirmed_assignments": [
                assignment.to_dict() 
                for assignment in self.confirmed_assignments
            ]
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BatchAssignmentConfirmation":
        """Create a BatchAssignmentConfirmation instance from a dictionary."""
        confirmed_assignments = [
            ConfirmedAssignment.from_dict(assignment_data)
            for assignment_data in data["confirmed_assignments"]
        ]
        return cls(confirmed_assignments)