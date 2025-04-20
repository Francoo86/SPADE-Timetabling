from spade.agent import Agent
from spade.behaviour import PeriodicBehaviour
from typing import Dict, List, Optional, Any
from json_stuff.json_salas import SalaScheduleStorage
from objects.knowledge_base import AgentKnowledgeBase, AgentCapability
from datetime import datetime

from objects.asignation_data import AsignacionSala

from objects.static.agent_enums import Day

from .agent_logger import AgentLogger
from fipa.common_templates import CommonTemplates
from behaviours.responder_behaviour import ResponderSolicitudesBehaviour
from src.performance.rtt_stats import RTTLogger

class AgenteSala(Agent):
    SERVICE_NAME = "sala"

    def __init__(self, jid, password, codigo: str, campus: str, capacidad: int, turno: int, scenario : str = ""):
        super().__init__(jid, password)
        self.codigo = codigo
        self.campus = campus
        self.capacidad = capacidad
        self.turno = turno
        self.horario_ocupado: Dict[Day, List[Optional[AsignacionSala]]] = {}
        self.is_registered = False
        self.MEETING_ROOM_THRESHOLD = 10
        self.log = AgentLogger("Sala" + self.codigo)
        self._kb = None
        self.storage = None
        self.scenario = scenario
        
        self.responder_behaviour = ResponderSolicitudesBehaviour()
        
    def set_rtt_logger(self, rtt_logger: RTTLogger):
        self.rtt_logger = rtt_logger

    def set_knowledge_base(self, kb: AgentKnowledgeBase):
        self._kb = kb

    async def setup(self):
        """Initialize agent setup"""
        self.initialize_schedule()
        await self.register_service()
        
        template = CommonTemplates.get_room_assigment_template()
        self.add_behaviour(self.responder_behaviour, template)
        
    def initialize_schedule(self):
        """Initialize empty schedule for all days"""
        self.horario_ocupado = {}
        for day in Day:
            self.horario_ocupado[day] = [None] * 9  # 9 blocks per day
            
    async def register_service(self):
        """Register agent service in directory"""
        try:
            await self.register_service()
            self.is_registered = True
            self.log.info(f"Room {self.codigo} registered successfully")
        except Exception as e:
            self.log.error(f"Error registering room {self.codigo}: {str(e)}")

    def is_meeting_room(self) -> bool:
        """Check if room is a meeting room based on capacity"""
        return self.capacidad < self.MEETING_ROOM_THRESHOLD

    @staticmethod
    def sanitize_subject_name(name: str) -> str:
        """Sanitize subject name by removing special characters"""
        return ''.join(c for c in name if c.isalnum())
    
    async def register_service(self):
        """Register room service in knowledge base"""
        try:
            # Create capability
            room_capability = AgentCapability(
                service_type="sala",
                properties={
                    "codigo": self.codigo,
                    "campus": self.campus,
                    "capacidad": self.capacidad,
                    "turno": self.turno
                },
                last_updated=datetime.now()
            )
            
            # Register agent
            success = await self._kb.register_agent(
                self.jid,
                [room_capability]
            )
            
            if not success:
                raise Exception(f"Failed to register room {self.codigo}")
                
            self.is_registered = True
            
        except Exception as e:
            self.log.error(f"Error registering room: {str(e)}")
            raise
        
    def set_storage(self, storage: SalaScheduleStorage):
        self.storage = storage
        
    async def update_schedule_storage(self, schedule_data: Dict[str, Any]) -> None:
        """
        Update the room's schedule in persistent storage
        
        Args:
            schedule_data: Dictionary containing the schedule information
        """
        try:
            await self.storage.update_schedule(
                codigo=self.codigo,
                campus=self.campus,
                schedule_data=schedule_data
            )
            
        except Exception as e:
            self.log.error(f"Error updating schedule storage: {str(e)}")
            raise

    class HeartbeatBehaviour(PeriodicBehaviour):
        """Send periodic heartbeats to maintain registration"""
        
        def __init__(self):
            super().__init__(period=30)  # 30 seconds between heartbeats
            
        async def run(self):
            try:
                await self.agent._kb.update_heartbeat(self.agent.jid)
            except Exception as e:
                self.agent.log.error(f"Error sending heartbeat: {str(e)}")

    async def cleanup(self):
        """Deregister from directory during cleanup"""
        try:
            if self.is_registered:
                await self.agent._kb.deregister_agent(self.jid)
                self.is_registered = False
                self.log.info(f"Room {self.agent.codigo} deregistered from directory")
        except Exception as e:
            self.log.error(f"Agent Sala{self.agent.codigo}:Error during cleanup: {str(e)}")