from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from datetime import datetime
from typing import Dict, List, Optional
import json
import asyncio

class RoomAssignment:
    def __init__(self, subject_name: str, satisfaction: int):
        self.subject_name = subject_name
        self.satisfaction = satisfaction

    def to_dict(self):
        return {
            "subject_name": self.subject_name,
            "satisfaction": self.satisfaction
        }

class RoomAgent(Agent):
    DAYS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]
    
    class RoomState:
        def __init__(self):
            self.code: str = ""
            self.capacity: int = 0
            self.schedule: Dict[str, List[Optional[RoomAssignment]]] = {}
            
        def initialize_schedule(self):
            for day in RoomAgent.DAYS:
                self.schedule[day] = [None] * 5  # 5 blocks per day

    async def setup(self):
        # Initialize room state
        self.state = self.RoomState()
        
        # Parse initial JSON configuration
        if self.json_data:
            self.state.code = self.json_data.get("Codigo")
            self.state.capacity = self.json_data.get("Capacidad")
            self.state.initialize_schedule()
        
        print(f"Room {self.state.code} started. Capacity: {self.state.capacity}")
        
        # Add behaviors for handling different types of messages
        template_cfp = Template()
        template_cfp.set_metadata("performative", "cfp")
        self.add_behaviour(self.HandleRequestsBehaviour(), template_cfp)
        
        template_accept = Template()
        template_accept.set_metadata("performative", "accept-proposal")
        self.add_behaviour(self.HandleAcceptanceBehaviour(), template_accept)

    class HandleRequestsBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                # Parse request
                subject_name, vacancies = msg.body.split(",")
                vacancies = int(vacancies)
                
                # Calculate satisfaction based on capacity vs vacancies
                satisfaction = self.calculate_satisfaction(
                    self.agent.state.capacity, 
                    vacancies
                )
                
                proposal_sent = False
                
                # Check each time slot
                for day in self.agent.DAYS:
                    schedule_day = self.agent.state.schedule[day]
                    for block in range(5):
                        if schedule_day[block] is None:  # Time slot is available
                            # Create proposal
                            reply = Message(
                                to=str(msg.sender),
                                metadata={"performative": "propose"}
                            )
                            
                            # Format: day,block,room_code,capacity,satisfaction
                            reply.body = f"{day},{block + 1},{self.agent.state.code}," \
                                       f"{self.agent.state.capacity},{satisfaction}"
                            
                            await self.send(reply)
                            proposal_sent = True
                            
                            print(f"Room {self.agent.state.code} proposes for {subject_name}: "
                                  f"day {day}, block {block + 1}, satisfaction {satisfaction}")
                
                if not proposal_sent:
                    # Send refuse message if no slots available
                    reply = Message(
                        to=str(msg.sender),
                        metadata={"performative": "refuse"}
                    )
                    await self.send(reply)
                    print(f"Room {self.agent.state.code} has no available blocks for {subject_name}")
                    
            except Exception as e:
                print(f"Error processing request in room {self.agent.state.code}: {str(e)}")

        @staticmethod
        def calculate_satisfaction(capacity: int, vacancies: int) -> int:
            """Calculate satisfaction score based on room capacity vs needed vacancies"""
            if capacity == vacancies:
                return 10  # High satisfaction
            elif capacity > vacancies:
                return 5   # Medium satisfaction
            return 3       # Low satisfaction

    class HandleAcceptanceBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                # Parse acceptance message
                # Format: day,block,subject_name,satisfaction,room_code
                data = msg.body.split(",")
                if len(data) < 5:
                    print(f"Error: Invalid message format in confirmation for room {self.agent.state.code}")
                    return

                day = data[0]
                block = int(data[1]) - 1  # Convert to 0-based index
                subject_name = data[2]
                satisfaction = int(data[3])
                room_code = data[4]

                # Verify this is the correct room
                if room_code != self.agent.state.code:
                    print(f"Error: Confirmation received for incorrect room")
                    return

                # Verify slot is still available
                schedule_day = self.agent.state.schedule[day]
                if (schedule_day is not None and 
                    0 <= block < len(schedule_day) and 
                    schedule_day[block] is None):
                    
                    # Create new assignment
                    new_assignment = RoomAssignment(subject_name, satisfaction)
                    schedule_day[block] = new_assignment

                    # Update schedule in persistent storage
                    await self.update_schedule_json()

                    # Send confirmation
                    reply = Message(
                        to=str(msg.sender),
                        metadata={"performative": "inform"},
                        body="CONFIRM"
                    )
                    await self.send(reply)

                    print(f"Room {self.agent.state.code}: Assigned {subject_name} on {day}, "
                          f"block {block + 1}, satisfaction {satisfaction}")
                else:
                    print(f"Error: Block {block + 1} not available in room "
                          f"{self.agent.state.code} for day {day}")

            except Exception as e:
                print(f"Error processing confirmation in room {self.agent.state.code}: {str(e)}")

        async def update_schedule_json(self):
            """Update the persistent storage with current schedule"""
            schedule_data = {}
            for day, assignments in self.agent.state.schedule.items():
                schedule_data[day] = [
                    assignment.to_dict() if assignment else None 
                    for assignment in assignments
                ]
            
            # Here you would implement the actual persistence
            # For example, using your JSON helper class:
            try:
                await self.agent.schedule_handler.update_room_schedule(
                    self.agent.state.code,
                    schedule_data
                )
            except Exception as e:
                print(f"Error updating schedule JSON: {str(e)}")

    def __init__(self, jid: str, password: str, json_data: dict, schedule_handler=None):
        super().__init__(jid, password)
        self.json_data = json_data
        self.schedule_handler = schedule_handler

class RoomScheduleHandler:
    """Handler for room schedule persistence"""
    
    def __init__(self, filename="room_schedules.json"):
        self.filename = filename
        self.schedules = {}
        self.load_schedules()

    def load_schedules(self):
        """Load existing schedules from file"""
        try:
            with open(self.filename, 'r') as f:
                self.schedules = json.load(f)
        except FileNotFoundError:
            self.schedules = {}

    async def update_room_schedule(self, room_code: str, schedule_data: dict):
        """Update schedule for a specific room"""
        self.schedules[room_code] = schedule_data
        await self.save_schedules()

    async def save_schedules(self):
        """Save all schedules to file"""
        with open(self.filename, 'w') as f:
            json.dump(self.schedules, f, indent=2)