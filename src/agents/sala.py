from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import Dict, List, Optional
import json

class RoomAssignment:
    def __init__(self, subject_name: str, satisfaction: int):
        self.subject_name = subject_name
        self.satisfaction = satisfaction

    def to_dict(self):
        return {
            "subject_name": self.subject_name,
            "satisfaction": self.satisfaction
        }

class RoomScheduleHandler:
    def __init__(self, filename="room_schedules.json"):
        self.filename = filename
        self.schedules = {}
        self.load_schedules()

    def load_schedules(self):
        try:
            with open(self.filename, 'r') as f:
                self.schedules = json.load(f)
        except FileNotFoundError:
            self.schedules = {}

    async def update_room_schedule(self, room_code: str, schedule_data: dict):
        self.schedules[room_code] = schedule_data
        await self.save_schedules()

    async def save_schedules(self):
        with open(self.filename, 'w') as f:
            json.dump(self.schedules, f, indent=2)

class RoomState:
    def __init__(self):
        self.schedule: Dict[str, List[Optional[RoomAssignment]]] = {}
        
    def initialize_schedule(self, days):
        for day in days:
            self.schedule[day] = [None] * 5  # 5 blocks per day

class RoomAgent(Agent):
    DAYS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]

    def __init__(self, jid: str, password: str, json_data: dict, schedule_handler=None):
        super().__init__(jid, password)
        self._code = json_data.get("Codigo")
        self._capacity = json_data.get("Capacidad")
        self._schedule_handler = schedule_handler
        self.state = RoomState()

    async def setup(self):
        """Initialize the room agent"""
        self.state.initialize_schedule(self.DAYS)
        
        print(f"Room {self._code} started. Capacity: {self._capacity}")
        
        # Add behaviors for handling different types of messages
        cfp_template = Template()
        cfp_template.set_metadata("performative", "cfp")
        self.add_behaviour(self.HandleRequestsBehaviour(), cfp_template)
        
        accept_template = Template()
        accept_template.set_metadata("performative", "accept-proposal")
        self.add_behaviour(self.HandleAcceptanceBehaviour(), accept_template)

        # Add status response behavior
        status_template = Template()
        status_template.set_metadata("performative", "query-ref")
        status_template.set_metadata("ontology", "agent-status")
        self.add_behaviour(self.StatusResponseBehaviour(), status_template)

    @property
    def code(self) -> str:
        return self._code

    @property
    def capacity(self) -> int:
        return self._capacity

    class HandleRequestsBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                subject_name, vacancies = msg.body.split(",")
                vacancies = int(vacancies)
                satisfaction = self.calculate_satisfaction(self.agent.capacity, vacancies)
                
                proposal_sent = False
                
                for day in self.agent.DAYS:
                    schedule_day = self.agent.state.schedule[day]
                    for block in range(5):
                        if schedule_day[block] is None:  # Time slot is available
                            reply = Message(
                                to=str(msg.sender),
                                metadata={"performative": "propose"}
                            )
                            reply.body = f"{day},{block + 1},{self.agent.code},{self.agent.capacity},{satisfaction}"
                            await self.send(reply)
                            proposal_sent = True
                            
                            print(f"Room {self.agent.code} proposes for {subject_name}: "
                                  f"day {day}, block {block + 1}, satisfaction {satisfaction}")
                
                if not proposal_sent:
                    reply = Message(
                        to=str(msg.sender),
                        metadata={"performative": "refuse"}
                    )
                    await self.send(reply)
                    print(f"Room {self.agent.code} has no available blocks for {subject_name}")
                    
            except Exception as e:
                print(f"Error processing request in room {self.agent.code}: {str(e)}")

        @staticmethod
        def calculate_satisfaction(capacity: int, vacancies: int) -> int:
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
                data = msg.body.split(",")
                if len(data) < 5:
                    print(f"Error: Invalid message format in confirmation for room {self.agent.code}")
                    return

                day = data[0]
                block = int(data[1]) - 1
                subject_name = data[2]
                satisfaction = int(data[3])
                room_code = data[4]

                if room_code != self.agent.code:
                    print(f"Error: Confirmation received for incorrect room")
                    return

                schedule_day = self.agent.state.schedule[day]
                if (schedule_day is not None and 
                    0 <= block < len(schedule_day) and 
                    schedule_day[block] is None):
                    
                    new_assignment = RoomAssignment(subject_name, satisfaction)
                    schedule_day[block] = new_assignment

                    if self.agent._schedule_handler:
                        await self.agent._schedule_handler.update_room_schedule(
                            self.agent.code,
                            {day: [a.to_dict() if a else None for a in schedule_day]}
                        )

                    reply = Message(
                        to=str(msg.sender),
                        metadata={"performative": "inform"},
                        body="CONFIRM"
                    )
                    await self.send(reply)

                    print(f"Room {self.agent.code}: Assigned {subject_name} on {day}, "
                          f"block {block + 1}, satisfaction {satisfaction}")
                else:
                    print(f"Error: Block {block + 1} not available in room "
                          f"{self.agent.code} for day {day}")

            except Exception as e:
                print(f"Error processing confirmation in room {self.agent.code}: {str(e)}")

    class StatusResponseBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                reply = Message(
                    to=str(msg.sender),
                    metadata={"performative": "inform"}
                )
                reply.body = "ACTIVE"  # or other appropriate status
                await self.send(reply)
            except Exception as e:
                print(f"Error sending status for room {self.agent.code}: {str(e)}")