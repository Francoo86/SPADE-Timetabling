from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import List, Dict
import json
from datetime import datetime, timedelta

class SupervisorState:
    def __init__(self, professor_jids: List[str]):
        self.professor_jids = professor_jids
        self.is_system_active = True
        self.inactivity_counters: Dict[str, int] = {}
        self.last_known_states: Dict[str, str] = {}
        self.MAX_INACTIVITY = 12  # 1 minute with 5-second intervals

class SupervisorAgent(Agent):
    def __init__(self, jid: str, password: str, professor_jids: List[str]):
        super().__init__(jid, password)
        self.professor_jids = professor_jids
        self.state = None

    async def setup(self):
        """Initialize the supervisor agent"""
        self.state = SupervisorState(self.professor_jids)
        print(f"[Supervisor] Monitoring {len(self.professor_jids)} professors")
        print("[Supervisor] Monitoring behavior started")
        
        # Add monitoring behavior
        self.add_behaviour(self.MonitorBehaviour(period=5))
        
        # Add message handling behavior
        template = Template()
        template.set_metadata("performative", "inform")
        self.add_behaviour(self.MessageHandlerBehaviour(), template)

    class MonitorBehaviour(PeriodicBehaviour):
        async def run(self):
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

                for jid in self.agent.state.professor_jids:
                    try:
                        msg = Message(
                            to=jid,
                            body="status_query",
                            metadata={
                                "performative": "query-ref",
                                "ontology": "agent-status"
                            }
                        )
                        await self.send(msg)
                        response = await self.receive(timeout=2)
                        
                        current_state = "UNKNOWN"
                        if response:
                            current_state = response.body
                            
                        state_count[current_state] = state_count.get(current_state, 0) + 1
                        previous_state = self.agent.state.last_known_states.get(jid)

                        # Update inactivity counter
                        if current_state == previous_state:
                            self.agent.state.inactivity_counters[jid] = \
                                self.agent.state.inactivity_counters.get(jid, 0) + 1
                        else:
                            self.agent.state.inactivity_counters[jid] = 0
                            self.agent.state.last_known_states[jid] = current_state

                        # Check state and inactivity
                        if current_state != "TERMINATED":
                            all_terminated = False
                            if self.agent.state.inactivity_counters.get(jid, 0) >= \
                               self.agent.state.MAX_INACTIVITY:
                                print(f"[WARNING] Professor {jid} appears stuck in {current_state} state. "
                                      f"Inactivity count: {self.agent.state.inactivity_counters[jid]}")
                            
                    except Exception as e:
                        print(f"[Supervisor] Error querying agent {jid}: {str(e)}")
                        state_count["UNKNOWN"] += 1

                # Print regular status report
                print("\n[Supervisor] Status Report:")
                for state, count in state_count.items():
                    print(f"- {state}: {count}")
                print(f"Total Agents: {len(self.agent.state.professor_jids)}\n")

                if all_terminated or state_count["TERMINATED"] == len(self.agent.state.professor_jids):
                    print("[Supervisor] All professors have completed their work.")
                    await self.finish_system()

            except Exception as e:
                print(f"[Supervisor] Error in monitoring: {str(e)}")

        async def finish_system(self):
            """Clean up and shut down the system"""
            try:
                self.agent.state.is_system_active = False
                print("[Supervisor] Generating final JSON files...")
                
                professor_schedules = {}
                for jid in self.agent.state.professor_jids:
                    try:
                        msg = Message(
                            to=jid,
                            body="schedule_query",
                            metadata={
                                "performative": "query-ref",
                                "ontology": "schedule-data"
                            }
                        )
                        await self.send(msg)
                        response = await self.receive(timeout=2)
                        if response:
                            professor_schedules[jid] = json.loads(response.body)
                    except Exception as e:
                        print(f"[Supervisor] Error collecting schedule from {jid}: {str(e)}")

                # Save final schedules
                with open("professor_schedules.json", "w") as f:
                    json.dump(professor_schedules, f, indent=2)
                
                print("[Supervisor] System shutdown complete.")
                await self.agent.stop()
                
            except Exception as e:
                print(f"[Supervisor] Error finishing system: {str(e)}")

    class MessageHandlerBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            try:
                if msg.metadata.get("ontology") == "schedule-update":
                    # Handle schedule updates if needed
                    pass
                elif msg.metadata.get("ontology") == "status-update":
                    # Handle status updates if needed
                    pass
            except Exception as e:
                print(f"[Supervisor] Error handling message: {str(e)}")