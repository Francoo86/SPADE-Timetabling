from dataclasses import dataclass
from typing import List
from ..static.agent_enums import Day

@dataclass
class AssignmentRequest:
    """
    A request for assigning a subject to a specific day/block/classroom.
    
    Attributes:
        day (Day): The day of the assignment
        block (int): The time block number
        subject_name (str): Name of the subject
        satisfaction (int): Satisfaction score for this assignment
        classroom_code (str): Code of the assigned classroom
        vacancy (int): Number of vacant spots needed
    """
    day: Day
    block: int
    subject_name: str
    satisfaction: int
    classroom_code: str
    vacancy: int

    def to_dict(self) -> dict:
        """Convert the request to a dictionary for serialization."""
        return {
            "day": self.day.name,
            "block": self.block,
            "subject_name": self.subject_name,
            "satisfaction": self.satisfaction,
            "classroom_code": self.classroom_code,
            "vacancy": self.vacancy
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AssignmentRequest":
        """Create an AssignmentRequest instance from a dictionary."""
        return cls(
            day=Day[data["day"]],
            block=data["block"],
            subject_name=data["subject_name"],
            satisfaction=data["satisfaction"],
            classroom_code=data["classroom_code"],
            vacancy=data["vacancy"]
        )

class BatchAssignmentRequest:
    """
    A container for multiple assignment requests.
    """
    def __init__(self, assignments: List[AssignmentRequest]):
        """
        Initialize a BatchAssignmentRequest.
        
        Args:
            assignments: List of AssignmentRequest objects
        """
        self.assignments = assignments

    def get_assignments(self) -> List[AssignmentRequest]:
        """Get the list of assignment requests."""
        return self.assignments

    def to_dict(self) -> dict:
        """Convert the batch request to a dictionary for serialization."""
        return {
            "assignments": [
                assignment.to_dict() 
                for assignment in self.assignments
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BatchAssignmentRequest":
        """Create a BatchAssignmentRequest instance from a dictionary."""
        assignments = [
            AssignmentRequest.from_dict(assignment_data)
            for assignment_data in data["assignments"]
        ]
        return cls(assignments)