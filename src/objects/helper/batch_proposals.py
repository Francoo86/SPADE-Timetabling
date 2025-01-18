from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
from spade.message import Message
from collections import defaultdict
from static.agent_enums import Day
from classroom_availability import ClassroomAvailability

@dataclass
class BlockProposal:
    block: int
    day: Day

    def to_dict(self) -> dict:
        return {
            "block": self.block,
            "day": self.day.name
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BlockProposal":
        return cls(
            block=data["block"],
            day=Day[data["day"]]
        )

class BatchProposal:
    def __init__(self, availability: "ClassroomAvailability", message: Message):
        """
        Initialize a BatchProposal object.
        
        Args:
            availability: ClassroomAvailability object containing room info
            message: SPADE Message object representing the original message
        """
        self.room_code: str = availability.codigo
        self.campus: str = availability.campus
        self.capacity: int = availability.capacidad
        self.satisfaction_score: int = 0
        self.original_message: Message = message
        self.day_proposals: Dict[Day, List[BlockProposal]] = defaultdict(list)

        # Convert string-based map to proper Day enum map
        for day_str, blocks in availability.available_blocks.items():
            day = Day.from_string(day_str)
            self.day_proposals[day] = [
                BlockProposal(block=block, day=day)
                for block in blocks
            ]

    def get_day_proposals(self) -> Dict[Day, List[BlockProposal]]:
        return dict(self.day_proposals)

    def get_room_code(self) -> str:
        return self.room_code

    def get_campus(self) -> str:
        return self.campus

    def get_capacity(self) -> int:
        return self.capacity

    def get_satisfaction_score(self) -> int:
        return self.satisfaction_score

    def get_original_message(self) -> Message:
        return self.original_message

    def set_satisfaction_score(self, score: int) -> None:
        self.satisfaction_score = score

    def to_dict(self) -> dict:
        """Convert the BatchProposal to a dictionary for serialization"""
        return {
            "room_code": self.room_code,
            "campus": self.campus,
            "capacity": self.capacity,
            "satisfaction_score": self.satisfaction_score,
            "day_proposals": {
                day.name: [block.to_dict() for block in blocks]
                for day, blocks in self.day_proposals.items()
            }
        }

    @classmethod
    def from_dict(cls, data: dict, message: Message) -> "BatchProposal":
        """Create a BatchProposal from a dictionary and message"""
        # Create a minimal ClassroomAvailability for initialization
        availability = type("ClassroomAvailability", (), {
            "codigo": data["room_code"],
            "campus": data["campus"],
            "capacidad": data["capacity"],
            "available_blocks": {
                day_str: [b["block"] for b in blocks]
                for day_str, blocks in data["day_proposals"].items()
            }
        })

        proposal = cls(availability, message)
        proposal.satisfaction_score = data["satisfaction_score"]
        return proposal