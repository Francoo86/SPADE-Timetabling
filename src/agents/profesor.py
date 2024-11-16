from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from spade.template import Template
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import json
import asyncio

class ProfesorState:
    def __init__(self):
        self.current_subject = 0
        self.proposals = []
        self.negotiation_started = False
        self.is_cleaning_up = False
        self.occupied_schedule: Dict[str, set] = {}  # day -> set of blocks
        self.schedule_json = {
            "Asignaturas": []
        }

class ProfesorAgent(Agent):
    DAYS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]
    TIMEOUT_PROPOSAL = 5  # seconds

    def __init__(self, jid: str, password: str, json_data: dict, order: int, room_jids: List[str]):
        super().__init__(jid, password)
        # Store initialization data
        self._order = order
        self._name = json_data.get("Nombre")
        self._rut = json_data.get("RUT")
        self._subjects = []
        self._room_jids = room_jids  # Store room JIDs
        
        # Process subjects from JSON
        for subject in json_data.get("Asignaturas", []):
            self._subjects.append({
                "nombre": subject["Nombre"],
                "horas": subject["Horas"],
                "vacantes": subject["Vacantes"]
            })
            
        self.state = None

    async def setup(self):
        """Initialize the professor agent"""
        self.state = ProfesorState()
        print(f"Professor {self._name} (order {self._order}) started")

        # Add behaviors based on order
        if self._order == 0:
            self.add_behaviour(self.NegotiationBehaviour())
        else:
            start_template = Template()
            start_template.set_metadata("performative", "inform")
            self.add_behaviour(self.WaitTurnBehaviour(), start_template)

        # Add status response behavior
        status_template = Template()
        status_template.set_metadata("performative", "query-ref")
        status_template.set_metadata("ontology", "agent-status")
        self.add_behaviour(self.StatusResponseBehaviour(), status_template)

        # Add schedule query behavior
        schedule_template = Template()
        schedule_template.set_metadata("performative", "query-ref")
        schedule_template.set_metadata("ontology", "schedule-data")
        self.add_behaviour(self.ScheduleQueryBehaviour(), schedule_template)

    @property
    def name(self) -> str:
        return self._name

    @property
    def rut(self) -> str:
        return self._rut

    @property
    def order(self) -> int:
        return self._order

    @property
    def subjects(self) -> List[dict]:
        return self._subjects

    class WaitTurnBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            if msg.body == "START":
                next_order = int(msg.get_metadata("next_order", -1))
                if next_order == self.agent.order:
                    print(f"Professor {self.agent.name} (order {self.agent.order}) activating on START signal")
                    self.agent.add_behaviour(self.agent.NegotiationBehaviour())
                    self.kill()
                else:
                    print(f"[DEBUG] Ignoring START message (not for me)")

    class NegotiationBehaviour(CyclicBehaviour):
        async def run(self):
            if self.agent.state.current_subject >= len(self.agent.subjects):
                await self.finish_negotiation()
                self.kill()
                return

            current_subject = self.agent.subjects[self.agent.state.current_subject]
            
            # Request proposals from all known rooms
            try:
                for room_jid in self.agent._room_jids:
                    print(f"Professor {self.agent.name}: Requesting proposals for {current_subject['nombre']} to {room_jid}")
                    print(f"JID data: ", str(room_jid))
                    msg = Message(
                        to=room_jid,
                        body=f"{current_subject['nombre']},{current_subject['vacantes']}",
                        metadata={"performative": "cfp"}
                    )
                    await self.send(msg)

                # Wait for proposals
                start_time = datetime.now()
                self.agent.state.proposals = []
                
                while (datetime.now() - start_time).total_seconds() < self.agent.TIMEOUT_PROPOSAL:
                    msg = await self.receive(timeout=0.1)
                    if msg and msg.get_metadata("performative") == "propose":
                        proposal = self.parse_proposal(msg.body)
                        proposal["message"] = msg
                        self.agent.state.proposals.append(proposal)

                # Evaluate proposals
                if self.agent.state.proposals:
                    if await self.evaluate_proposals():
                        self.agent.state.current_subject += 1
                else:
                    print(f"Professor {self.agent.name}: No proposals received for {current_subject['nombre']}")
                    self.agent.state.current_subject += 1

            except Exception as e:
                print(f"Error in negotiation for professor {self.agent.name}: {str(e)}")

        async def evaluate_proposals(self) -> bool:
            """Evaluate received proposals and accept the best one"""
            try:
                # Sort proposals by satisfaction
                proposals = sorted(
                    self.agent.state.proposals,
                    key=lambda p: p["satisfaction"],
                    reverse=True
                )

                current_subject = self.agent.subjects[self.agent.state.current_subject]
                
                for proposal in proposals:
                    day = proposal["day"]
                    block = proposal["block"]
                    room = proposal["room"]
                    satisfaction = proposal["satisfaction"]
                    
                    # Check if time slot is available for professor
                    occupied_blocks = self.agent.state.occupied_schedule.get(day, set())
                    
                    if block not in occupied_blocks:
                        # Accept proposal
                        reply = Message(
                            to=str(proposal["message"].sender),
                            metadata={"performative": "accept-proposal"}
                        )
                        
                        reply.body = f"{day},{block},{current_subject['nombre']},{satisfaction},{room}"
                        await self.send(reply)
                        
                        # Wait for confirmation
                        confirm_msg = await self.receive(timeout=5)
                        
                        if confirm_msg and confirm_msg.body == "CONFIRM":
                            # Update schedule
                            if day not in self.agent.state.occupied_schedule:
                                self.agent.state.occupied_schedule[day] = set()
                            self.agent.state.occupied_schedule[day].add(block)
                            
                            # Update JSON schedule
                            assignment = {
                                "Nombre": current_subject["nombre"],
                                "Sala": room,
                                "Bloque": block,
                                "Dia": day,
                                "Satisfaccion": satisfaction
                            }
                            self.agent.state.schedule_json["Asignaturas"].append(assignment)
                            
                            print(f"Professor {self.agent.name}: Successfully assigned "
                                  f"{current_subject['nombre']} in room {room}, day {day}, "
                                  f"block {block}, satisfaction {satisfaction}")
                            return True
            
            except Exception as e:
                print(f"Error evaluating proposals for professor {self.agent.name}: {str(e)}")
            
            return False

        async def finish_negotiation(self):
            """Clean up and notify next professor"""
            if not self.agent.state.is_cleaning_up:
                try:
                    self.agent.state.is_cleaning_up = True
                    
                    # Get next professor's JID from knowledge base
                    next_professor = self.agent.get(f"professor_{self.agent.order + 1}")
                    
                    if next_professor:
                        msg = Message(
                            to=f"professor_{self.agent.order + 1}@{self.agent.jid.host}",
                            body="START",
                            metadata={
                                "performative": "inform",
                                "next_order": str(self.agent.order + 1)
                            }
                        )
                        await self.send(msg)
                    
                    print(f"Professor {self.agent.name} completed negotiations")
                    
                except Exception as e:
                    print(f"Error in finish_negotiation for professor {self.agent.name}: {str(e)}")

        @staticmethod
        def parse_proposal(proposal_string: str) -> dict:
            """Parse proposal string into dictionary"""
            parts = proposal_string.split(",")
            return {
                "day": parts[0],
                "block": int(parts[1]),
                "room": parts[2],
                "capacity": int(parts[3]),
                "satisfaction": int(parts[4])
            }

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
                
                if self.agent.state.is_cleaning_up:
                    reply.body = "TERMINATED"
                elif self.agent.state.current_subject >= len(self.agent.subjects):
                    reply.body = "TERMINATED"
                else:
                    reply.body = "ACTIVE"
                
                await self.send(reply)
                
            except Exception as e:
                print(f"Error sending status for professor {self.agent.name}: {str(e)}")

    class ScheduleQueryBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                reply = Message(
                    to=str(msg.sender),
                    metadata={"performative": "inform"}
                )
                reply.body = json.dumps(self.agent.state.schedule_json)
                await self.send(reply)
                
            except Exception as e:
                print(f"Error sending schedule for professor {self.agent.name}: {str(e)}")