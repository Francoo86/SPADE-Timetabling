from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour
from spade.message import Message
from typing import List, Dict
import asyncio
import json
from datetime import datetime

class SupervisorAgent(Agent):
    class SupervisorState:
        def __init__(self, professor_jids: List[str]):
            self.professor_jids = professor_jids
            self.is_system_active = True
            self.inactivity_counters: Dict[str, int] = {}
            self.last_known_states: Dict[str, str] = {}
            self.MAX_INACTIVITY = 12  # 1 minute with 5-second intervals

    async def setup(self):
        """Initialize the supervisor agent"""
        self.state = self.SupervisorState(self.professor_jids)
        print(f"[Supervisor] Monitoring {len(self.professor_jids)} professors")

        # Add the monitoring behavior
        self.add_behaviour(self.MonitorBehaviour(period=5))

    class MonitorBehaviour(PeriodicBehaviour):
        """Periodic behavior to monitor professors' status"""
        
        async def query_agent_status(self, jid: str) -> str:
            """Query the status of an agent"""
            try:
                msg = Message(
                    to=jid,
                    metadata={
                        "performative": "query-ref",
                        "ontology": "agent-status"
                    }
                )
                await self.send(msg)
                
                # Wait for response with timeout
                response = await self.receive(timeout=2)
                if response:
                    return response.body
                return "UNKNOWN"
            except Exception as e:
                print(f"[Supervisor] Error querying agent {jid}: {str(e)}")
                return "ERROR"

        async def on_start(self):
            """Called when the behaviour starts"""
            print("[Supervisor] Monitoring behavior started")

        async def run(self):
            """Main monitoring logic"""
            if not self.agent.state.is_system_active:
                return

            try:
                all_terminated = True
                state_count = {
                    "ACTIVE": 0,
                    "WAITING": 0,
                    "SUSPENDED": 0,
                    "IDLE": 0,
                    "TERMINATED": 0,
                    "INITIATED": 0,
                    "UNKNOWN": 0
                }

                # Monitor each professor's state
                for jid in self.agent.state.professor_jids:
                    current_state = await self.query_agent_status(jid)
                    previous_state = self.agent.state.last_known_states.get(jid)

                    # Update state counts
                    state_count[current_state] = state_count.get(current_state, 0) + 1

                    # Check if state has changed
                    if current_state == previous_state:
                        self.agent.state.inactivity_counters[jid] = \
                            self.agent.state.inactivity_counters.get(jid, 0) + 1
                    else:
                        self.agent.state.inactivity_counters[jid] = 0
                        self.agent.state.last_known_states[jid] = current_state

                    # Process different states
                    match current_state:
                        case "ACTIVE":
                            all_terminated = False
                            if self.agent.state.inactivity_counters.get(jid, 0) >= \
                               self.agent.state.MAX_INACTIVITY:
                                print(f"[WARNING] Professor {jid} appears stuck in ACTIVE state. "
                                      f"Inactivity count: {self.agent.state.inactivity_counters[jid]}")
                        
                        case "WAITING":
                            all_terminated = False
                            if self.agent.state.inactivity_counters.get(jid, 0) >= \
                               self.agent.state.MAX_INACTIVITY:
                                print(f"[WARNING] Professor {jid} appears stuck in WAITING state. "
                                      f"Inactivity count: {self.agent.state.inactivity_counters[jid]}")
                        
                        case "SUSPENDED":
                            all_terminated = False
                            print(f"[WARNING] Professor {jid} is in SUSPENDED state.")
                        
                        case "IDLE":
                            all_terminated = False
                            if self.agent.state.inactivity_counters.get(jid, 0) >= \
                               self.agent.state.MAX_INACTIVITY:
                                print(f"[WARNING] Professor {jid} appears stuck in IDLE state. "
                                      f"Inactivity count: {self.agent.state.inactivity_counters[jid]}")
                        
                        case "TERMINATED":
                            # Remove from monitoring
                            self.agent.state.inactivity_counters.pop(jid, None)
                            self.agent.state.last_known_states.pop(jid, None)
                        
                        case "INITIATED":
                            all_terminated = False
                            print(f"[INFO] Professor {jid} is still in INITIATED state.")
                        
                        case _:
                            print(f"[WARNING] Professor {jid} is in unknown state: {current_state}")

                # Regular status report (every 20 seconds - every 4th check with 5s period)
                if self.agent.state.is_system_active and \
                   datetime.now().timestamp() % 20 < 5:
                    print("\n[Supervisor] Status Report:")
                    for state, count in state_count.items():
                        print(f"- {state}: {count}")
                    print(f"Total Agents: {len(self.agent.state.professor_jids)}\n")

                # Check if system should be shut down
                if all_terminated or state_count["TERMINATED"] == len(self.agent.state.professor_jids):
                    print("[Supervisor] All professors have completed their work.")
                    await self.finish_system()

            except Exception as e:
                print(f"[Supervisor] Error in monitoring: {str(e)}")

        async def finish_system(self):
            """Cleanup and shutdown the system"""
            try:
                self.agent.state.is_system_active = False
                print("[Supervisor] Generating final JSON files...")
                
                # Generate final reports
                await self.generate_final_reports()
                
                print("[Supervisor] System shutdown complete.")
                await self.agent.stop()
                
            except Exception as e:
                print(f"[Supervisor] Error finishing system: {str(e)}")

        async def generate_final_reports(self):
            """Generate final JSON reports"""
            try:
                # Professor schedules
                professor_schedules = await self.collect_professor_schedules()
                with open("professor_schedules.json", "w") as f:
                    json.dump(professor_schedules, f, indent=2)

                # Room schedules
                room_schedules = await self.collect_room_schedules()
                with open("room_schedules.json", "w") as f:
                    json.dump(room_schedules, f, indent=2)

            except Exception as e:
                print(f"[Supervisor] Error generating reports: {str(e)}")

        async def collect_professor_schedules(self) -> dict:
            """Collect final schedules from all professors"""
            schedules = {}
            for jid in self.agent.state.professor_jids:
                try:
                    msg = Message(
                        to=jid,
                        metadata={
                            "performative": "query-ref",
                            "ontology": "schedule-data"
                        }
                    )
                    await self.send(msg)
                    response = await self.receive(timeout=2)
                    if response:
                        schedules[jid] = json.loads(response.body)
                except Exception as e:
                    print(f"[Supervisor] Error collecting schedule from {jid}: {str(e)}")
            return schedules

        async def collect_room_schedules(self) -> dict:
            """Collect final schedules from all rooms"""
            # This would be implemented similar to collect_professor_schedules
            # but for room agents
            pass

    def __init__(self, jid: str, password: str, professor_jids: List[str]):
        super().__init__(jid, password)
        self.professor_jids = professor_jids