from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour, CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import List, Dict
import json
from datetime import datetime, timedelta
import asyncio
import aioxmpp
from objects.knowledge_base import AgentKnowledgeBase, AgentCapability
from .agent_logger import AgentLogger
from pathlib import Path
import os


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

class AgenteSupervisor(Agent):
    CHECK_INTERVAL = 5  # seconds

    def __init__(self, jid: str, password: str, professor_jids: List[str]):
        super().__init__(jid, password)
        self.professor_jids = professor_jids
        self.state = None
        self._kb : AgentKnowledgeBase = None
        self.log = AgentLogger("Supervisor")
        self.monitor = None
        self.room_storage = None
        self.prof_storage = None
        
    def set_knowledge_base(self, kb : AgentKnowledgeBase):
        self._kb = kb
        
    def set_storages(self, room_storage, professor_storage):
        self.room_storage = room_storage
        self.prof_storage = professor_storage

    async def setup(self):
        """Initialize the supervisor agent"""
        self.state = SupervisorState(self.professor_jids)
        print(f"[Supervisor] Monitoring {len(self.professor_jids)} professors")
        
        # Store initial state in knowledge base
        self.set("system_active", True)
        
        capability = AgentCapability(
            service_type="supervisor",
            properties={"professor_jids": self.professor_jids},
            last_updated=datetime.now()
        )
        
        await self._kb.register_agent(self.jid, [capability])
        
        self.monitor = self.MonitorBehaviour(period=self.CHECK_INTERVAL)
        
        # Add monitoring behavior
        self.add_behaviour(self.monitor)

        print("[Supervisor] Monitoring behavior started")
        
        # Add shutdown behavior
        shutdown_template = Template()
        shutdown_template.set_metadata("performative", "inform")
        shutdown_template.set_metadata("ontology", "system-control")
        shutdown_template.set_metadata("content", "SHUTDOWN")
        
        self.add_behaviour(self.ShutdownBehaviour(), shutdown_template)

    class MonitorBehaviour(PeriodicBehaviour):
        def __init__(self, period: float, start_at: datetime | None = None):
            super().__init__(period, start_at)
            self.current_iteration = 0
        
        async def on_start(self):
            """Initialize the behaviour"""
            print("[Supervisor] Starting monitoring cycle")
            self.agent.state.state_count = {state: 0 for state in self.agent.state.state_count}
        
        async def run(self):
            pass
            """
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
                            pass
                            # print(f"[WARNING] Professor {jid} appears stuck in {current_state} state. "
                                # f"Inactivity count: {inactivity}")

                if self.current_iteration % 4 == 0:
                    pass
                    # await self.print_status_report()

                if all_terminated or self.agent.state.state_count["TERMINATED"] == len(self.agent.state.professor_jids):
                    print("[Supervisor] All professors have completed their work.")
                    await self.finish_system()

            except Exception as e:
                print(f"[Supervisor] Error in monitoring: {str(e)}") """

        async def finish_system(self):
            """Clean up and shut down the system"""
            try:
                self.agent.set("system_active", False)
                print("[Supervisor] Generating final JSON files...")
                
                # Generate final files using both storage systems
                
                await self.agent.room_storage.generate_json_file()
                await self.agent.prof_storage.generate_json_file()
                
                # Verify files were generated
                output_path = Path(os.getcwd()) / "agent_output"
                sala_file = output_path / "Horarios_salas.json"
                prof_file = output_path / "Horarios_asignados.json"
                
                if sala_file.exists() and sala_file.stat().st_size > 0:
                    print("[Supervisor] Horarios_salas.json generated correctly")
                else:
                    print("[Supervisor] ERROR: Horarios_salas.json is empty or does not exist")
                    
                if prof_file.exists() and prof_file.stat().st_size > 0:
                    print("[Supervisor] Horarios_asignados.json generated correctly")
                else:
                    print("[Supervisor] ERROR: Horarios_asignados.json is empty or does not exist")
                
                print("[Supervisor] System finalized.")
                
                await self.agent._kb.deregister_agent(self.agent.jid)
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
                    msg.set_metadata("content", "status_query")
                    
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

    class ShutdownBehaviour(CyclicBehaviour):
        """Handles system shutdown signals from professors"""
        
        async def run(self):            
            msg = await self.receive(timeout=0.1)
            if msg:
                try:
                    self.agent.log.info("Received shutdown signal - initiating system shutdown")
                    
                    # Set system inactive to stop monitoring
                    self.agent.set("system_active", False)
                    
                    # Generate final JSON files
                    await self.agent.monitor.finish_system()
                    
                    # Clean up and stop all agents
                    # await self.agent.stop()
                    
                except Exception as e:
                    self.agent.log.error(f"Error during shutdown: {str(e)}")