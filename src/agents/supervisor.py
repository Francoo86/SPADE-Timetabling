from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import List, Dict
import json
from datetime import datetime, timedelta
import asyncio
import aioxmpp

class SupervisorState:
    def __init__(self, professor_jids: List[str]):
        self.professor_jids = professor_jids
        self.is_system_active = True
        self.inactivity_counters: Dict[str, int] = {}
        self.last_known_states: Dict[str, str] = {}
        self.MAX_INACTIVITY = 12  # 1 minute with 5-second intervals
        self.state_count = {
            "ACTIVE": 0,
            "WAITING": 0,
            "SUSPENDED": 0,
            "IDLE": 0,
            "TERMINATED": 0,
            "INITIATED": 0,
            "UNKNOWN": 0
        }

class SupervisorAgent(Agent):
    CHECK_INTERVAL = 5  # seconds

    def __init__(self, jid: str, password: str, professor_jids: List[str]):
        super().__init__(jid, password)
        self.professor_jids = professor_jids
        self.state = None

    async def setup(self):
        """Initialize the supervisor agent"""
        self.state = SupervisorState(self.professor_jids)
        print(f"[Supervisor] Monitoring {len(self.professor_jids)} professors")
        
        # Store initial state in knowledge base
        self.set("system_active", True)
        
        # Add monitoring behavior
        self.add_behaviour(self.MonitorBehaviour(period=self.CHECK_INTERVAL))
        
        # Add message handling behavior
        template = Template()
        template.set_metadata("performative", "inform")
        self.add_behaviour(self.MessageHandlerBehaviour(), template)

        print("[Supervisor] Monitoring behavior started")
        
        # Add message handling behavior for room schedules
        room_template = Template()
        room_template.set_metadata("performative", "query-ref")
        room_template.set_metadata("ontology", "room-schedule")
        self.add_behaviour(self.RoomScheduleCollectorBehaviour(), room_template)

    class RoomScheduleCollectorBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                if msg.get_metadata("ontology") == "room-schedule-data":
                    room_code = msg.get_metadata("room-code")
                    schedule_data = json.loads(msg.body)
                    self.agent.set(f"room_schedule_{room_code}", schedule_data)
            except Exception as e:
                print(f"[Supervisor] Error handling room schedule: {str(e)}")

    class MonitorBehaviour(PeriodicBehaviour):
        async def finish_system(self):
            """Clean up and shut down the system"""
            try:
                self.agent.set("system_active", False)
                print("[Supervisor] Generating final JSON files...")
                
                # Collect professor schedules
                professor_schedules = await self.collect_all_schedules()
                with open("professor_schedules.json", "w") as f:
                    json.dump(professor_schedules, f, indent=2, ensure_ascii=False)


                # Collect and save room schedules
                room_schedules = await self.collect_room_schedules()
                print("ROOM SCHEDULES: ", room_schedules)
                with open("rooms_output.json", "w") as f:
                    json.dump(room_schedules, f, indent=2, ensure_ascii=False)
                
                print("[Supervisor] System shutdown complete.")
                await self.agent.stop()
                
            except Exception as e:
                print(f"[Supervisor] Error finishing system: {str(e)}")

        async def collect_room_schedules(self) -> List[dict]:
            """Collect all room schedules and format them"""
            room_schedules = []
            
            for room_jid in self.agent.get("room_jids") or []:
                try:
                    msg = Message(
                        to=str(room_jid),
                        metadata={
                            "performative": "query-ref",
                            "ontology": "room-schedule"
                        }
                    )
                    await self.send(msg)
                    response = await self.receive(timeout=2)
                    
                    if response and response.body:
                        schedule_data = json.loads(response.body)
                        room_schedule = {
                            "Codigo": schedule_data["code"],
                            "Asignaturas": []
                        }
                        
                        # Transform schedule data into required format
                        for day, assignments in schedule_data["schedule"].items():
                            for block_idx, assignment in enumerate(assignments, 1):
                                if assignment:
                                    room_schedule["Asignaturas"].append({
                                        "Nombre": assignment["subject_name"],
                                        "Valoracion": assignment["satisfaction"],
                                        "Bloque": block_idx,
                                        "Dia": day
                                    })
                        
                        room_schedules.append(room_schedule)
                
                except Exception as e:
                    print(f"[Supervisor] Error collecting room schedule: {str(e)}")
            
            return room_schedules

    class MonitorBehaviour(PeriodicBehaviour):
        def __init__(self, period: float, start_at: datetime | None = None):
            super().__init__(period, start_at)
            self.current_iteration = 0
        
        async def on_start(self):
            """Initialize the behaviour"""
            print("[Supervisor] Starting monitoring cycle")
            self.agent.state.state_count = {state: 0 for state in self.agent.state.state_count}
        
        async def run(self):
            self.current_iteration += 1
            system_active = self.agent.get("system_active")
            if not system_active:
                self.kill()
                return

            try:
                all_terminated = True
                self.agent.state.state_count = {state: 0 for state in self.agent.state.state_count}

                # Query all professors in parallel
                responses = await self.query_all_professors()

                # Process responses
                for jid, response in responses.items():
                    current_state = "UNKNOWN"
                    if response and response.body:
                        current_state = response.body

                    self.agent.state.state_count[current_state] += 1
                    previous_state = self.agent.state.last_known_states.get(jid)

                    if current_state == previous_state:
                        self.agent.state.inactivity_counters[jid] = \
                            self.agent.state.inactivity_counters.get(jid, 0) + 1
                    else:
                        self.agent.state.inactivity_counters[jid] = 0
                        self.agent.state.last_known_states[jid] = current_state

                    if current_state != "TERMINATED":
                        all_terminated = False
                        inactivity = self.agent.state.inactivity_counters.get(jid, 0)
                        if inactivity >= self.agent.state.MAX_INACTIVITY:
                            print(f"[WARNING] Professor {jid} appears stuck in {current_state} state. "
                                f"Inactivity count: {inactivity}")

                if self.current_iteration % 4 == 0:
                    await self.print_status_report()

                if all_terminated or self.agent.state.state_count["TERMINATED"] == len(self.agent.state.professor_jids):
                    print("[Supervisor] All professors have completed their work.")
                    await self.finish_system()

            except Exception as e:
                print(f"[Supervisor] Error in monitoring: {str(e)}")

        async def finish_system(self):
            """Clean up and shut down the system"""
            try:
                self.agent.set("system_active", False)
                print("[Supervisor] Generating final JSON files...")
                
                # Collect professor schedules
                professor_schedules = await self.collect_all_schedules()
                with open("professor_schedules.json", "w") as f:
                    json.dump(professor_schedules, f, indent=2, ensure_ascii=False)

                # Collect and save room schedules
                room_schedules = await self.collect_room_schedules()
                print("[Supervisor] Room schedules collected:", room_schedules)
                with open("rooms_output.json", "w") as f:
                    json.dump(room_schedules, f, indent=2, ensure_ascii=False)
                
                print("[Supervisor] System shutdown complete.")
                await self.agent.stop()
                
            except Exception as e:
                print(f"[Supervisor] Error finishing system: {str(e)}")

        async def query_all_professors(self) -> Dict[str, Message]:
            """Query all professors in parallel and return their responses"""
            async def query_professor(jid: aioxmpp.JID) -> tuple[str, Message]:
                try:
                    receptor = f"{jid.localpart}@{jid.domain}"
                    msg = Message(to=receptor)
                    msg.set_metadata("performative", "query-ref")
                    msg.set_metadata("ontology", "agent-status")
                    msg.body = "status_query"
                    
                    await self.send(msg)
                    response = await self.receive(timeout=2)
                    return jid, response
                except Exception as e:
                    print(f"[Supervisor] Error querying agent {jid}: {str(e)}")
                    return jid, None

            tasks = [query_professor(jid) for jid in self.agent.state.professor_jids]
            responses = await asyncio.gather(*tasks)
            return dict(responses)

        async def print_status_report(self):
            """Print current status report"""
            print("\n[Supervisor] Status Report:")
            for state, count in self.agent.state.state_count.items():
                print(f"- {state}: {count}")
            print(f"Total Agents: {len(self.agent.state.professor_jids)}\n")

        async def collect_all_schedules(self) -> List[dict]:
            """Collect and transform schedules from all professors"""
            async def get_professor_schedule(jid: aioxmpp.JID) -> tuple[str, dict]:
                jid_str = str(jid)
                try:
                    msg = Message(to=str(jid))
                    msg.set_metadata("performative", "query-ref")
                    msg.set_metadata("ontology", "schedule-data")
                    msg.body = "schedule_query"
                    
                    await self.send(msg)
                    response = await self.receive(timeout=2)
                    
                    if response and response.body:
                        return jid_str, json.loads(response.body)
                    return jid_str, None
                except Exception as e:
                    print(f"[Supervisor] Error collecting schedule from {jid}: {str(e)}")
                    return jid_str, None

            tasks = [get_professor_schedule(jid) for jid in self.agent.state.professor_jids]
            raw_schedules = await asyncio.gather(*tasks)
            
            transformed_schedules = []
            for jid, schedule in raw_schedules:
                if schedule is not None:
                    prof_data = self.agent.get(f"professor_data_{jid}")
                    if prof_data:
                        transformed_schedule = {
                            "Nombre": prof_data["name"],
                            "AsignaturasCompletadas": len(schedule["Asignaturas"]),
                            "Solicitudes": len(prof_data["subjects"]),
                            "Asignaturas": schedule["Asignaturas"]
                        }
                        transformed_schedules.append(transformed_schedule)

            transformed_schedules.sort(key=lambda x: x["Nombre"])
            return transformed_schedules

        async def collect_room_schedules(self) -> List[dict]:
            """Collect all room schedules and format them"""
            room_schedules = []
            room_jids = self.agent.get("room_jids") or []
            print(f"[Supervisor] Collecting schedules from {len(room_jids)} rooms")
            
            for room_jid in room_jids:
                try:
                    print(f"[Supervisor] Requesting schedule from room: {room_jid}")
                    msg = Message(
                        to=str(room_jid),
                        metadata={
                            "performative": "query-ref",
                            "ontology": "room-schedule"
                        }
                    )
                    await self.send(msg)
                    response = await self.receive(timeout=2)
                    
                    if response and response.body:
                        schedule_data = json.loads(response.body)
                        room_schedule = {
                            "Codigo": schedule_data["code"],
                            "Asignaturas": []
                        }
                        
                        for day, assignments in schedule_data["schedule"].items():
                            for block_idx, assignment in enumerate(assignments, 1):
                                if assignment:
                                    room_schedule["Asignaturas"].append({
                                        "Nombre": assignment["subject_name"],
                                        "Valoracion": assignment["satisfaction"],
                                        "Bloque": block_idx,
                                        "Dia": day
                                    })
                        
                        room_schedules.append(room_schedule)
                        print(f"[Supervisor] Successfully collected schedule from room: {schedule_data['code']}")
                    else:
                        print(f"[Supervisor] No response received from room: {room_jid}")
                
                except Exception as e:
                    print(f"[Supervisor] Error collecting room schedule from {room_jid}: {str(e)}")
            
            return room_schedules

    class MessageHandlerBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                if msg.get_metadata("ontology") == "schedule-update":
                    await self.handle_schedule_update(msg)
                elif msg.get_metadata("ontology") == "status-update":
                    await self.handle_status_update(msg)
            except Exception as e:
                print(f"[Supervisor] Error handling message: {str(e)}")

        async def handle_schedule_update(self, msg: Message):
            """Handle schedule update messages"""
            # Implement if needed
            pass

        async def handle_status_update(self, msg: Message):
            """Handle status update messages"""
            # Implement if needed
            pass