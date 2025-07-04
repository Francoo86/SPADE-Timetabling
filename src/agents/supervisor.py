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
from fipa.acl_message import FIPAPerformatives
from src.performance.lightweight_monitor import CentralizedPerformanceMonitor

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

    def __init__(self, jid: str, password: str, professor_jids: List[str], scenario: str):
        super().__init__(jid, password)
        self.professor_jids = professor_jids
        self.state = None
        self._kb : AgentKnowledgeBase = None
        self.log = AgentLogger("Supervisor")
        self.monitor = None
        self.room_storage = None
        self.prof_storage = None
        
        self.finalizer : asyncio.Event = None
        self.metrics_monitor = None
        self.scenario = scenario
        
        """
        self.performance_monitor = CentralizedPerformanceMonitor(
            agent_identifier=self.jid,
            agent_type="supervisor",
            scenario=self.scenario
        )"""
        
        self.room_agents = []
        
    def set_room_agents(self, room_agents: List[Agent]):
        self.room_agents = room_agents
        
    def set_metrics_monitor(self, monitor):
        self.metrics_monitor = monitor
        
    def add_finalizer_event(self, finalizer : asyncio.Event):
        self.finalizer = finalizer
        
    def set_knowledge_base(self, kb : AgentKnowledgeBase):
        self._kb = kb
        
    def set_storages(self, room_storage, professor_storage):
        self.room_storage = room_storage
        self.prof_storage = professor_storage

    async def setup(self):
        """Initialize the supervisor agent"""
        # await self.performance_monitor.start_monitoring()
        self.state = SupervisorState(self.professor_jids)
        
        self.set("system_active", True)
        
        capability = AgentCapability(
            service_type="supervisor",
            properties={"professor_jids": self.professor_jids},
            last_updated=datetime.now()
        )
        
        await self._kb.register_agent(self.jid, [capability])
        
        # Add shutdown behavior
        shutdown_template = Template()
        shutdown_template.set_metadata("performative", FIPAPerformatives.CANCEL)
        shutdown_template.set_metadata("ontology", "system-control")
        shutdown_template.body = "NULL_PROF"
        # shutdown_template.set_metadata("content", "NULL_PROF")
        
        self.add_behaviour(self.ShutdownBehaviour(), shutdown_template)

    class ShutdownBehaviour(CyclicBehaviour):
        """Handles system shutdown signals from professors"""
        
        async def run(self):            
            msg = await self.receive(timeout=0.5)
            if msg:
                try:
                    self.agent.log.info("Received shutdown signal - initiating system shutdown")
                    
                    # First stop metrics monitor to ensure clean metrics shutdown
                    if self.agent.metrics_monitor:
                        self.agent.log.info("Stopping metrics monitor...")
                        await self.agent.metrics_monitor.stop()
                        await self.agent.metrics_monitor._flush_all()  # Final flush
                    
                    # Generate final files with proper error handling
                    try:
                        self.agent.log.info("Generating room schedules JSON...")
                        # await self.agent.room_storage.generate_json_file()
                        await self.agent.room_storage.generate_supervisor_final_report(self.agent.room_agents)
                        
                        self.agent.log.info("Generating professor schedules JSON...")
                        await self.agent.prof_storage.generate_json_file()
                        
                        # Force flush any pending updates
                       #  await self.agent.room_storage.force_flush()
                        await self.agent.prof_storage.force_flush()
                        
                    except Exception as e:
                        self.agent.log.error(f"Error generating JSON files: {str(e)}")

                    # Deregister from KB
                    try:
                        await self.agent._kb.deregister_agent(self.agent.jid)
                        self.agent.log.info("Deregistered from knowledge base")
                    except Exception as e:
                        self.agent.log.error(f"Error deregistering from KB: {str(e)}")

                    # Set completion event
                    # if self.agent.finalizer:
                        # await self.agent.finalizer.set()
                        self.agent.log.info("Finalizer event set")
                        
                except Exception as e:
                    self.agent.log.error(f"Error during shutdown: {str(e)}")
                    # Ensure finalizer is set even on error
                    # if self.agent.finalizer:
                        # await self.agent.finalizer.set()
                self.agent.set("system_active", False)