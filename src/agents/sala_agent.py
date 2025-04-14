from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from typing import Dict, List, Optional, Any
from json_stuff.json_salas import SalaScheduleStorage
import json
import asyncio
from objects.knowledge_base import AgentKnowledgeBase, AgentCapability
from datetime import datetime

from objects.asignation_data import AsignacionSala
from objects.helper.batch_proposals import ClassroomAvailability
from objects.helper.batch_requests import BatchAssignmentRequest
from objects.helper.confirmed_assignments import BatchAssignmentConfirmation, ConfirmedAssignment

from objects.static.agent_enums import Day

from .agent_logger import AgentLogger
from fipa.common_templates import CommonTemplates
from fipa.acl_message import FIPAPerformatives
import jsonpickle

from performance.rtt_stats import RTTLogger
from sys import getsizeof

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

class ResponderSolicitudesBehaviour(CyclicBehaviour):
    """Enhanced room responder behaviour to work with FSM professors"""
    def __init__(self):
        super().__init__()
        self.rtt_logger = None
        self.rtt_initialized = False
        
    async def on_start(self):
        """Initialize RTT logger on behaviour start"""
        if self.rtt_initialized:
            return
        
        self.rtt_logger = RTTLogger(str(self.agent.jid), self.agent.scenario)
        self.rtt_initialized = True
        await self.rtt_logger.start()

    async def run(self):
        """Main behaviour loop with improved message handling"""
        try:
            # Wait for a message with short timeout for responsiveness
            msg = await self.receive(timeout=0.1)
            if not msg:
                await asyncio.sleep(0.1)
                return

            performative = msg.get_metadata("performative")
            # conversation_id = msg.get_metadata("conversation-id")

            if performative == FIPAPerformatives.CFP:
                await self.process_request(msg)
            elif performative == FIPAPerformatives.ACCEPT_PROPOSAL:
                await self.confirm_assignment(msg)

        except Exception as e:
            self.agent.log.error(f"Error in room responder: {str(e)}")

    async def process_request(self, msg: Message):
        """Process incoming room requests with improved error handling"""
        try:
            # Parse request data
            request_data = json.loads(msg.body)
            subject_name = self.agent.sanitize_subject_name(request_data["nombre"])
            vacancies = request_data["vacantes"]
            
            # Check availability with timeout protection
            async with asyncio.timeout(1.0):
                available_blocks = self.get_available_blocks(vacancies)
                
                if available_blocks:
                    # Create availability response
                    availability = ClassroomAvailability(
                        codigo=self.agent.codigo,
                        campus=self.agent.campus,
                        capacidad=self.agent.capacidad,
                        available_blocks=available_blocks
                    )
                    
                    # Send proposal with response tracking
                    reply = msg.make_reply()
                    reply.set_metadata("performative", FIPAPerformatives.PROPOSE)
                    reply.set_metadata("conversation-id", msg.get_metadata("conversation-id"))
                    reply.set_metadata("ontology", "classroom-availability")
                    reply.body = jsonpickle.encode(availability)
                    
                    await self.send(reply)
                    self.agent.log.debug(f"Sent proposal to {msg.sender} for {subject_name}")
                else:
                    # Send refuse with reason
                    reply = msg.make_reply()
                    reply.set_metadata("performative", FIPAPerformatives.REFUSE)
                    reply.set_metadata("conversation-id", msg.get_metadata("conversation-id"))
                    reply.set_metadata("ontology", "classroom-availability")
                    reply.body = "No blocks available"
                    
                    await self.send(reply)
                    self.agent.log.debug(f"Sent refuse to {msg.sender} - no blocks available")
                    
        except asyncio.TimeoutError:
            self.agent.log.error(f"Timeout processing request from {msg.sender}")
        except Exception as e:
            self.agent.log.error(f"Error processing request: {str(e)}")
    
    def get_available_blocks(self, vacancies: int) -> Dict[str, List[int]]:
        """Get available blocks for each day"""
        available_blocks = {}
        for day, assignments in self.agent.horario_ocupado.items():
            free_blocks = []
            for block_idx, assignment in enumerate(assignments):
                if assignment is None:
                    free_blocks.append(block_idx + 1)
            if free_blocks:
                available_blocks[day.name] = free_blocks
        return available_blocks


    async def confirm_assignment(self, msg: Message):
        """Handle assignment confirmation with improved verification"""
        try:
            # Parse batch assignment request
            request_data : BatchAssignmentRequest = jsonpickle.decode(msg.body)
            assignments = []
            
            # Process assignments with validation
            async with asyncio.timeout(1.0):
                for assignment in request_data.get_assignments():
                    if assignment.classroom_code != self.agent.codigo:
                        self.agent.log.debug(f"Skipping request for different room: {assignment.classroom_code}")
                        continue

                    day = assignment.day
                    block = assignment.block - 1
                    subject_name = assignment.subject_name
                    satisfaction = assignment.satisfaction

                    # Verify block availability
                    if block < 0 or block >= len(self.agent.horario_ocupado[day]):
                        self.agent.log.warning(f"Invalid block requested: {block + 1}")
                        continue

                    if self.agent.horario_ocupado[day][block] is not None:
                        self.agent.log.warning(f"Block {block + 1} already assigned")
                        continue

                    # Create and store assignment
                    new_assignment = AsignacionSala(
                        subject_name,
                        satisfaction,
                        float(assignment.vacancy) / self.agent.capacidad
                    )
                    
                    self.agent.horario_ocupado[day][block] = new_assignment
                    
                    assignments.append(ConfirmedAssignment(
                        day,
                        block + 1,
                        self.agent.codigo,
                        satisfaction
                    ))

                # Send confirmation for successful assignments
                if assignments:
                    confirmation = BatchAssignmentConfirmation(assignments)
                    reply = msg.make_reply()
                    reply.set_metadata("performative", FIPAPerformatives.INFORM)
                    reply.set_metadata("ontology", "room-assignment")
                    reply.set_metadata("conversation-id", msg.get_metadata("conversation-id"))
                    reply.body = jsonpickle.encode(confirmation)
                    
                    rtt_id = msg.get_metadata("rtt-id")
                    await self.rtt_logger.end_request(
                        rtt_id,
                        response_performative=FIPAPerformatives.INFORM,  # Performative de respuesta
                        message_size=getsizeof(reply.body),
                        success=True,
                        ontology="room-assignment"
                    )
            
                    await self.send(reply)
                    
                    # Update storage asynchronously
                    asyncio.create_task(self.update_schedule_storage())
                    
        except asyncio.TimeoutError:
            self.agent.log.error(f"Timeout confirming assignment from {msg.sender}")
        except Exception as e:
            self.agent.log.error(f"Error confirming assignment: {str(e)}")

    async def update_schedule_storage(self):
        """Update storage with error handling"""
        try:
            schedule_data = {
                "codigo": self.agent.codigo,
                "campus": self.agent.campus,
                "horario": {
                    day.name: [
                        assignment.to_dict() if assignment else None
                        for assignment in assignments
                    ]
                    for day, assignments in self.agent.horario_ocupado.items()
                }
            }
            
            await self.agent.update_schedule_storage(schedule_data)
            
        except Exception as e:
            self.agent.log.error(f"Error updating schedule storage: {str(e)}")