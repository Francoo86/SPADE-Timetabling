from spade.agent import Agent
from typing import Dict, List, Optional
from queue import Queue
from spade.template import Template
import asyncio

import sys
sys.path.append('src/')

from objects.asignation_data import Asignatura
from objects.static.agent_enums import TipoContrato, Day
from behaviours.negotiation_behaviour import NegotiationStateBehaviour
from behaviours.message_collector import MessageCollectorBehaviour
from behaviours.requests_behaviour import EsperarTurnoBehaviour, NotifyNextProfessorBehaviour
from objects.asignation_data import BloqueInfo
from spade.message import Message
from .agent_logger import AgentLogger
from objects.knowledge_base import AgentKnowledgeBase, AgentCapability
from behaviours.monitoring import StatusResponseBehaviour, InitialWaitBehaviour
from fipa.common_templates import CommonTemplates

from datetime import datetime

import logging

class AgenteProfesor(Agent):
    AGENT_NAME = "Profesor"
    SERVICE_NAME = AGENT_NAME.lower()
    
    def __init__(self, jid: str, password: str, nombre: str, asignaturas: List[Asignatura], orden: int):
        super().__init__(jid, password)
        self.nombre = nombre
        self.asignaturas = asignaturas
        self.asignatura_actual = 0
        self.horario_ocupado = {}  # dia -> set(bloques)
        self.orden = orden  # Will be set during setup
        self.horario_json = {}
        self.bloques_asignados_por_dia = {}  # dia -> {asignatura -> List[bloques]}
        self.instance_counter = 0
        self.current_instance_index = 0
        self.log =  AgentLogger(f"Professor_{self.nombre}")
        self._initialize_data_structures()
        self._kb = None
        self.batch_proposals = asyncio.Queue()
        self.is_cleaning_up = False
        
        # inicializar una fuente de verdad de los behaviors
        self.negotiation_state_behaviour = NegotiationStateBehaviour(self, self.batch_proposals)
        self.message_collector_behaviour = MessageCollectorBehaviour(self, self.batch_proposals, self.negotiation_state_behaviour)
        
    def get_relevant_behaviours(self):
        return self.negotiation_state_behaviour, self.message_collector_behaviour
        
    def set_knowledge_base(self, kb: AgentKnowledgeBase):
        self._kb = kb

    def _initialize_data_structures(self):
        """Initialize all data structures needed for the agent."""
        # Initialize schedule tracking
        self.horario_ocupado = {day: set() for day in Day}
        
        # convert asignaturas dict to object
        self.asignaturas = [Asignatura.from_json(asig) for asig in self.asignaturas]
        
        # Initialize JSON structures
        self.horario_json = {"Asignaturas": []}
        
        # Initialize daily block assignments
        self.bloques_asignados_por_dia = {day: {} for day in Day}
    
    async def get_professor_status(self, request):
        current = self.get_current_subject()
        return {
            "name": self.nombre,
            "order": self.orden,
            "current_subject": current.get_nombre() if current else None,
            "total_subjects": len(self.asignaturas),
            "completed_subjects": self.asignatura_actual,
            "negotiation_state": self.current_state.name if hasattr(self, "current_state") else None,
            "pending_blocks": self.bloques_pendientes if hasattr(self, "bloques_pendientes") else 0,
            "schedule": self.horario_json
        }

    async def setup(self):
        """Setup the agent behaviors and structures."""
        try:
            # self.web.start(hostname="127.0.0.1", port=10000 + self.orden)
            # self.web.add_get("/status", self.get_professor_status, template=None)
            # Initialize agent capabilities
            professor_capability = AgentCapability(
                service_type="profesor",
                properties={
                    "nombre": self.nombre,
                    "orden": self.orden  # Make sure order is registered
                },
                last_updated=datetime.now()
            )
            
            # Register with knowledge base
            success = await self._kb.register_agent(
                self.jid,
                [professor_capability]
            )
            
            if not success:
                self.log.error("Failed to register professor in knowledge base")
                return
                
            self.log.info(f"Professor {self.nombre} registered with order {self.orden}")
    
            # Add status response behavior
            template = Template()
            template.set_metadata("performative", "query-ref")
            template.set_metadata("ontology", "agent-status")
            self.add_behaviour(StatusResponseBehaviour(), template)
            
            # Discover rooms
            await self.discover_rooms()
            
            # Add appropriate behaviour based on order
            if self.orden == 0:
                self.log.info("Starting as first professor")
                template = CommonTemplates.get_notify_next_professor_template(is_base=True)
                self.add_behaviour(InitialWaitBehaviour(*self.get_relevant_behaviours()), template)
            else:
                self.log.info(f"Waiting for turn (order: {self.orden})")
                wait_behaviour = EsperarTurnoBehaviour(
                    self, 
                    *self.get_relevant_behaviours()
                )
                
                template = CommonTemplates.get_notify_next_professor_template()
                self.add_behaviour(wait_behaviour, template)
                
        except Exception as e:
            self.log.error(f"Error in professor setup: {str(e)}")
    
    async def discover_rooms(self):
        """Discover available rooms through knowledge base"""
        try:
            
            # First ensure the knowledge base is properly initialized
            if not self._kb._capabilities:
                self.log.warning("Knowledge base has no capabilities registered")
                return
                
            # Search for room agents
            rooms = await self._kb.search(service_type="sala")
            
            if not rooms:
                self.log.warning("No rooms found in knowledge base")
                return
                
            # Debug log the discovered rooms
            self.log.info(f"Found {len(rooms)} rooms in knowledge base:")
            for room in rooms:
                room_code = None
                for cap in room.capabilities:
                    if cap.service_type == "sala":
                        room_code = cap.properties.get("codigo")
                        break
                        
                if room_code:
                    room_jid = str(room.jid)
                    self.set(f"room_{room_code}", room_jid)
                    self.log.info(f"  - Room {room_code} at {room_jid}")
            
        except Exception as e:
            self.log.error(f"Error discovering rooms: {str(e)}")
            self.log.error(f"Knowledge base state: {self._kb._capabilities}")  # Debug log

    def can_use_more_subjects(self) -> bool:
        """Check if there are more subjects to process."""
        try:
            if self.asignatura_actual >= len(self.asignaturas):
                return False
                
            current = self.asignaturas[self.asignatura_actual]
            if current is None:
                logging.warning(f"Agente Profesor{self.orden}: Warning: Null subject at index {self.asignatura_actual}")
                return False
                
            return True
        except IndexError:
            logging.error(f"Agente Profesor{self.orden}: Index out of bounds checking for more subjects: "
                          f"{self.asignatura_actual}/{len(self.asignaturas)}")
            return False

    def get_current_subject(self) -> Optional[Asignatura]:
        """Get the current subject being processed."""
        if not self.can_use_more_subjects():
            return None
        return self.asignaturas[self.asignatura_actual]

    def move_to_next_subject(self):
        """Move to the next subject in the list."""
        logging.info(f"Agente Profesor{self.orden}: [MOVE] Moving from subject index {self.asignatura_actual} "
                     f"(total: {len(self.asignaturas)})")
        
        if self.asignatura_actual >= len(self.asignaturas):
            logging.info(f"Agente Profesor{self.orden}: [MOVE] Already at last subject")
            return
            
        current = self.get_current_subject()
        current_name = current.get_nombre()
        current_code = current.get_codigo_asignatura()
        self.asignatura_actual += 1
        
        if self.asignatura_actual < len(self.asignaturas):
            next_subject = self.asignaturas[self.asignatura_actual]
            if (next_subject.get_nombre() == current_name and 
                next_subject.get_codigo_asignatura() == current_code):
                self.current_instance_index += 1
                logging.info(f"Agente Profesor{self.orden}: [MOVE] Moving to next instance ({self.current_instance_index}) "
                            f"of {current_name}")
            else:
                self.current_instance_index = 0
                logging.info(f"Agente Profesor{self.orden}: [MOVE] Moving to new subject {next_subject.get_nombre()}")
        else:
            logging.info(f"Agente Profesor{self.orden}: [MOVE] Reached end of subjects")

    def is_block_available(self, dia: Day, bloque: int) -> bool:
        """Check if a time block is available."""
        return bloque not in self.horario_ocupado.get(dia, set())

    def get_blocks_by_day(self, dia: Day) -> Dict[str, List[int]]:
        """Get all blocks assigned for a specific day."""
        return self.bloques_asignados_por_dia.get(dia, {})

    def get_blocks_by_subject(self, nombre_asignatura: str) -> Dict[Day, List[int]]:
        """Get all blocks assigned for a specific subject."""
        bloques_asignados = {}
        for dia, asignaturas in self.bloques_asignados_por_dia.items():
            # Look for all keys that start with the asignatura name
            for subject_name, blocks in asignaturas.items():
                if subject_name.startswith(nombre_asignatura):
                    if blocks:
                        bloques_asignados.setdefault(dia, []).extend(blocks)
        return bloques_asignados

    def get_bloque_info(self, dia: Day, bloque: int) -> Optional[BloqueInfo]:
        """Get information about a specific time block."""
        clases_del_dia = self.get_blocks_by_day(dia)
        if not clases_del_dia:
            return None
            
        for nombre_asig, bloques in clases_del_dia.items():
            if bloque not in bloques:
                continue
                
            # Find the campus for the subject
            for asig in self.asignaturas:
                if asig.get_nombre() == nombre_asig:
                    return BloqueInfo(asig.get_campus(), bloque)
        
        return None

    def get_current_instance_key(self) -> str:
        """Get a unique key for the current subject instance."""
        current = self.get_current_subject()
        return f"{current.get_nombre()}-{current.get_codigo_asignatura()}-{self.current_instance_index}"

    def update_schedule_info(self, dia: Day, sala: str, bloque: int, nombre_asignatura: str, 
                           satisfaccion: int):
        """Update the schedule information with a new assignment."""
        current_instance_key = self.get_current_instance_key()
        
        # Update occupied schedule
        self.horario_ocupado.setdefault(dia, set()).add(bloque)
        
        # Update blocks by day with instance information
        self.bloques_asignados_por_dia.setdefault(dia, {}).setdefault(current_instance_key, []).append(bloque)
        
        # Update JSON schedule
        self._actualizar_horario_json(dia, sala, bloque, satisfaccion)

    def get_tipo_contrato(self) -> TipoContrato:
        """Get the contract type based on total teaching hours."""
        return self.inferir_tipo_contrato(self.asignaturas)

    def _actualizar_horario_json(self, dia: Day, sala: str, bloque: int, satisfaccion: int):
        """Update the JSON schedule with new assignment."""
        current_subject = self.get_current_subject()
        
        asignatura = {
            "Nombre": current_subject.get_nombre(),
            "Sala": sala,
            "Bloque": bloque,
            "Dia": dia.value,
            "Satisfaccion": satisfaccion,
            "CodigoAsignatura": current_subject.get_codigo_asignatura(),
            "Instance": self.current_instance_index,
            "Actividad": current_subject.get_actividad().name
        }
        
        self.horario_json["Asignaturas"].append(asignatura)
        
    @staticmethod
    def inferir_tipo_contrato(asignaturas: List[Asignatura]) -> TipoContrato:
        total_hours = sum(asig.get_horas() for asig in asignaturas)
        if 16 <= total_hours <= 18:
            return TipoContrato.JORNADA_COMPLETA
        elif 12 <= total_hours <= 14:
            return TipoContrato.MEDIA_JORNADA
        return TipoContrato.JORNADA_PARCIAL

    async def finalizar_negociaciones(self):
        try:
            if self.is_cleaning_up:
                return
            self.is_cleaning_up = True
            
            # Save final schedule
            await self.export_schedule_json()
            
            # Notify next professor
            await self.notify_next_professor()
            
            # Cleanup
            await self.cleanup()
        except Exception as e:
            logging.error(f"Agente Profesor{self.orden}: Error finalizing negotiations: {str(e)}")

    @staticmethod
    def sanitize_subject_name(name: str) -> str:
        return ''.join(c for c in name if c.isalnum())

    async def cleanup(self):
        try:
            behaviours = self.behaviours
            for behaviour in behaviours:
                if not behaviour: continue
                behaviour.kill()
            
            
            if self._kb:
                await self._kb.deregister_agent(self.jid)
                
            # Short delay to allow messages to be sent
            await asyncio.sleep(0.1)
            # Cleanup resources and deregister
            await self.stop()
        finally:
            self.is_cleaning_up = False

    async def export_schedule_json(self) -> Dict:
        return {
            "nombre": self.nombre,
            "asignaturas": self.horario_json["Asignaturas"],
            "completadas": len(self.horario_json["Asignaturas"]),
            "total": len(self.asignaturas)
        }
        
    async def notify_next_professor(self):
        try:
            next_orden = self.orden + 1
            
            # Search for next professor
            professors = await self._kb.search(
                service_type="profesor",
                properties={"orden": next_orden}
            )
            
            if professors:
                next_professor = professors[0]
                
                # Create START message
                msg = Message(to=str(next_professor.jid))
                msg.set_metadata("performative", "inform")
                msg.set_metadata("content", "START")
                msg.set_metadata("conversation-id", "negotiation-start")
                msg.set_metadata("nextOrden", str(next_orden))
                
                notify_behaviour = NotifyNextProfessorBehaviour(self, next_orden)
                self.add_behaviour(notify_behaviour, msg)
                
                # await self.send(msg)
                await notify_behaviour.join()
                self.log.info(f"Successfully notified next professor with order: {next_orden}")
                
            else:
                self.log.info(f"No next professor found with order {next_orden}")
                
        except Exception as e:
            self.log.error(f"Error notifying next professor: {str(e)}")