from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum
from spade.message import Message
from collections import defaultdict
from ..static.agent_enums import Day
from .classroom_availability import ClassroomAvailability
import msgspec

class BlockProposal(msgspec.Struct):
    block: int
    day: Day

    def to_dict(self) -> dict:
        return {
            "block": self.block,
            "day": self.day.name
        }
        
    def get_block(self) -> int:
        return self.block
    
    def get_day(self) -> Day:
        return self.day

    @classmethod
    def from_dict(cls, data: dict) -> "BlockProposal":
        return cls(
            block=data["block"],
            day=Day[data["day"]]
        )

class BatchProposal(msgspec.Struct, kw_only=True):
    room_code: str
    campus: str
    capacity: int
    satisfaction_score: int = 0
    original_message: Message
    day_proposals: Dict[Day, List[BlockProposal]]

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
    
    @classmethod
    def from_availability(cls, availability: ClassroomAvailability, message: Message):
        # return cls(availability, message)
        # now this is a struct
        # create a minimal ClassroomAvailability for initialization
        return BatchProposal(
            room_code=availability.codigo,
            campus=availability.campus,
            capacity=availability.capacidad,
            satisfaction_score=0,
            original_message=message,
            day_proposals={
                day: [BlockProposal(block=block, day=day) for block in blocks]
                for day, blocks in availability.available_blocks.items()
            }
        )
    
    # create the same method but consider the availability as a dictionary
    @classmethod
    def from_availability_dict(cls, availability: Dict, message: Message):
        availability_obj = ClassroomAvailability(
            codigo=availability["codigo"],
            campus=availability["campus"],
            capacidad=availability["capacidad"],
            available_blocks=availability["available_blocks"]
        )
        return cls(availability_obj, message)