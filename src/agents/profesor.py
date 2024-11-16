from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template
from datetime import datetime, timedelta
import json
import asyncio

class ProfesorAgent(Agent):
    class NegotiationState:
        def __init__(self):
            self.current_subject = 0
            self.proposals = []
            self.negotiation_started = False
            self.is_cleaning_up = False
            self.occupied_schedule = {}  # day -> set of blocks
            self.schedule_json = {
                "Asignaturas": []
            }

    async def setup(self):
        self.state = self.NegotiationState()
        
        # Initialize from JSON data
        if self.json_data:
            self.name = self.json_data.get("Nombre")
            self.rut = self.json_data.get("RUT")
            self.subjects = []
            
            for subject in self.json_data.get("Asignaturas", []):
                self.subjects.append({
                    "nombre": subject["Nombre"],
                    "horas": subject["Horas"],
                    "vacantes": subject["Vacantes"]
                })
        
        print(f"Professor {self.name} (order {self.order}) started")
        
        # Register behaviors
        if self.order == 0:
            self.add_behaviour(self.NegotiationBehaviour())
        else:
            template = Template()
            template.set_metadata("performative", "inform")
            self.add_behaviour(self.WaitTurnBehaviour(), template)
        
        # Add periodic status check
        self.add_behaviour(self.StatusCheckBehaviour(period=5))

    class WaitTurnBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if msg:
                if msg.body == "START":
                    next_order = int(msg.get_metadata("next_order"))
                    if next_order == self.agent.order:
                        print(f"Professor {self.agent.name} (order {self.agent.order}) activating on START signal")
                        self.agent.add_behaviour(self.agent.NegotiationBehaviour())
                        self.kill()
                    else:
                        print(f"[DEBUG] Ignoring START message (not for me)")

    class NegotiationBehaviour(CyclicBehaviour):
        async def run(self):
            if self.agent.state.current_subject >= len(self.agent.subjects):
                await self.cleanup()
                self.kill()
                return

            current_subject = self.agent.subjects[self.agent.state.current_subject]
            
            # Request proposals
            msg = Message(
                to="directory@localhost",  # Service discovery would be implemented here
                body=f"{current_subject['nombre']},{current_subject['vacantes']}",
                metadata={"performative": "cfp"}
            )
            await self.send(msg)
            
            # Wait for proposals
            start_time = datetime.now()
            while (datetime.now() - start_time).seconds < 5:  # 5 second timeout
                msg = await self.receive(timeout=0.1)
                if msg and msg.get_metadata("performative") == "propose":
                    proposal = self.parse_proposal(msg.body)
                    proposal["message"] = msg
                    self.agent.state.proposals.append(proposal)
            
            # Evaluate proposals
            if self.agent.state.proposals:
                if await self.evaluate_proposals():
                    self.agent.state.current_subject += 1
                    self.agent.state.proposals = []
            else:
                print(f"Professor {self.agent.name}: No proposals received for {current_subject['nombre']}")
                self.agent.state.current_subject += 1

        async def evaluate_proposals(self):
            # Sort proposals by satisfaction
            proposals = sorted(
                self.agent.state.proposals,
                key=lambda p: p["satisfaction"],
                reverse=True
            )
            
            for proposal in proposals:
                day = proposal["day"]
                block = proposal["block"]
                room = proposal["room"]
                satisfaction = proposal["satisfaction"]
                
                occupied_blocks = self.agent.state.occupied_schedule.get(day, set())
                
                if block not in occupied_blocks:
                    # Accept proposal
                    reply = Message(
                        to=proposal["message"].sender,
                        body=f"{day},{block},{self.agent.subjects[self.agent.state.current_subject]['nombre']},{satisfaction},{room}",
                        metadata={"performative": "accept-proposal"}
                    )
                    await self.send(reply)
                    
                    # Wait for confirmation
                    msg = await self.receive(timeout=5)
                    if msg and msg.get_metadata("performative") == "inform":
                        # Update schedule
                        if day not in self.agent.state.occupied_schedule:
                            self.agent.state.occupied_schedule[day] = set()
                        self.agent.state.occupied_schedule[day].add(block)
                        
                        # Update JSON schedule
                        self.update_schedule_json(day, room, block, satisfaction)
                        return True
            
            return False

        def update_schedule_json(self, day, room, block, satisfaction):
            subject = {
                "Nombre": self.agent.subjects[self.agent.state.current_subject]["nombre"],
                "Sala": room,
                "Bloque": block,
                "Dia": day,
                "Satisfaccion": satisfaction
            }
            self.agent.state.schedule_json["Asignaturas"].append(subject)

        async def cleanup(self):
            if not self.agent.state.is_cleaning_up:
                self.agent.state.is_cleaning_up = True
                
                # Save final schedule
                # Implementation of schedule saving would go here
                
                # Notify next professor
                next_order = self.agent.order + 1
                msg = Message(
                    to="directory@localhost",  # Would be replaced with actual next professor address
                    body="START",
                    metadata={
                        "performative": "inform",
                        "next_order": str(next_order)
                    }
                )
                await self.send(msg)
                
                # Final cleanup
                await self.agent.stop()

    class StatusCheckBehaviour(PeriodicBehaviour):
        async def run(self):
            print(f"\n=== Status Check for Professor {self.agent.name} ===")
            print(f"Current subject: {self.agent.state.current_subject}/{len(self.agent.subjects)}")
            print(f"Occupied schedule: {self.agent.state.occupied_schedule}")
            print("=============================\n")

    @staticmethod
    def parse_proposal(proposal_string):
        parts = proposal_string.split(",")
        return {
            "day": parts[0],
            "block": int(parts[1]),
            "room": parts[2],
            "capacity": int(parts[3]),
            "satisfaction": int(parts[4])
        }

    def __init__(self, jid: str, password: str, json_data: dict, order: int):
        super().__init__(jid, password)
        self.json_data = json_data
        self.order = order