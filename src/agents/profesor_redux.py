from spade.agent import Agent
from typing import Dict, List, Optional
import asyncio

import sys
sys.path.append('src/')

from objects.asignation_data import Asignatura
from objects.static.agent_enums import TipoContrato, Day
from behaviours.requests_behaviour import EsperarTurnoBehaviour
from objects.asignation_data import BloqueInfo
from .agent_logger import AgentLogger
from objects.knowledge_base import AgentKnowledgeBase, AgentCapability
from behaviours.monitoring import InitialWaitBehaviour
from fipa.common_templates import CommonTemplates
from json_stuff.json_profesores import ProfesorScheduleStorage
from behaviours.fsm_negotiation_states import NegotiationFSM
from src.performance.rtt_stats import RTTLogger
from src.performance.lightweight_monitor import CentralizedPerformanceMonitor
from datetime import datetime

# TODO: Usar la clase TimetableAgent en lugar de Agent
class AgenteProfesor(Agent):
    AGENT_NAME = "Profesor"
    SERVICE_NAME = AGENT_NAME.lower()
    
    def __init__(self, jid: str, password: str, nombre: str, asignaturas: List[Asignatura], orden: int, scenario : str = ""):
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
        self.log =  AgentLogger(f"Profesor{self.orden}")
        self._initialize_data_structures()
        self._kb = None
        # self.batch_proposals = asyncio.Queue()
        self.is_cleaning_up = False
        self.rtt_logger = None
        self.storage = None
        # self.cleanup_lock = asyncio.Lock()
        self.metrics_monitor = None
        self.message_logger = None
        self.representative_name = f"Profesor{self.orden}"

        # Lock para replicar el synchronized de Java
        # self.prof_lock = asyncio.Lock()
        
        self.scenario = scenario
        """
        self.performance_monitor = CentralizedPerformanceMonitor(
            agent_identifier=self.nombre,
            agent_type=self.AGENT_NAME,
            scenario=self.scenario
        ) """
        
        # inicializar una fuente de verdad de los behaviors
        self.negotiation_state_behaviour = NegotiationFSM(profesor_agent=self)
        # self.negotiation_state_behaviour = NegotiationStateBehaviour(self, self.batch_proposals)
        # self.message_collector_behaviour = MessageCollectorBehaviour(self, self.batch_proposals, self.negotiation_state_behaviour)
    def set_rtt_logger(self, rtt_logger: RTTLogger):
        self.rtt_logger = rtt_logger
        
    def get_bloques_pendientes(self) -> int:
        """Get the number of pending blocks for the current subject."""
        """ Wrapper for the negotiation state behaviour """
        return self.negotiation_state_behaviour.get_bloques_pendientes()
    
    def set_message_logger(self, message_logger):
        """Set the message logger for this agent"""
        self.message_logger = message_logger
        
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
        
    def prepare_behaviours(self):
        negotiation_template = CommonTemplates.get_negotiation_template()
        self.add_behaviour(self.negotiation_state_behaviour, negotiation_template)

    async def setup(self):
        """Setup the agent behaviors and structures."""
        try:
            # await self.performance_monitor.start_monitoring()
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
            
            # Discover rooms
            # await self.discover_rooms()
            
            # Add appropriate behaviour based on order
            if self.orden == 0:
                self.log.info("Starting as first professor")
                template = CommonTemplates.get_notify_next_professor_template(is_base=True)
                self.add_behaviour(InitialWaitBehaviour(), template)
            else:
                self.log.info(f"Waiting for turn (order: {self.orden})")
                wait_behaviour = EsperarTurnoBehaviour(
                    self,
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
        # async with self.prof_lock:
        try:
            if self.asignatura_actual >= len(self.asignaturas):
                return False
                
            current = self.asignaturas[self.asignatura_actual]
            if current is None:
                self.log.warning(f"Null subject at index {self.asignatura_actual}")
                return False
                
            return True
        except IndexError:
            self.log.error(f"Index out of bounds checking for more subjects: "
                        f"{self.asignatura_actual}/{len(self.asignaturas)}")
            return False

    def get_current_subject(self) -> Optional[Asignatura]:
        """Get the current subject being processed."""
        # async with self.prof_lock:
        if not self.can_use_more_subjects():
            return None
        return self.asignaturas[self.asignatura_actual]

    def move_to_next_subject(self):
        """Move to the next subject in the list."""
    # async with self.prof_lock:
        self.log.info(f"[MOVE] Moving from subject index {self.asignatura_actual} "
                    f"(total: {len(self.asignaturas)})")
        
        if self.asignatura_actual >= len(self.asignaturas):
            self.log.info(f" [MOVE] Already at last subject")
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
                self.log.info(f" [MOVE] Moving to next instance ({self.current_instance_index}) "
                            f"of {current_name}")
            else:
                self.current_instance_index = 0
                self.log.info(f" [MOVE] Moving to new subject {next_subject.get_nombre()}")
        else:
            self.log.info(f" [MOVE] Reached end of subjects")
    
    def is_block_available(self, dia: Day, bloque: int) -> bool:
        """Check if a time block is available."""
        return dia not in self.horario_ocupado or bloque not in self.horario_ocupado[dia]

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

    async def update_schedule_info(self, dia: Day, sala: str, bloque: int, nombre_asignatura: str, satisfaccion: int):
        """Update the schedule information with a new assignment."""
        try:
            if not self.storage:
                self.log.error("Storage not properly initialized")
                return
                
            current_instance_key = self.get_current_instance_key()
            
            # Update local structures first
            self.horario_ocupado.setdefault(dia, set()).add(bloque)
            self.bloques_asignados_por_dia.setdefault(dia, {}).setdefault(
                current_instance_key, []).append(bloque)
            
            # Update JSON structure
            await self._actualizar_horario_json(dia, sala, bloque, satisfaccion)
            
            # Create a deep copy of data for storage
            schedule_data = {
                "Asignaturas": self.horario_json["Asignaturas"].copy(),
                "Nombre": self.nombre,
                "TotalAsignaturas": len(self.asignaturas),
                "AsignaturasCompletadas": self.asignatura_actual
            }
            
            # Update storage with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await asyncio.shield(
                        self.storage.update_schedule(
                            self.nombre,
                            schedule_data,
                            self.asignaturas
                        )
                    )
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        self.log.error(f"Failed to update storage after {max_retries} attempts: {str(e)}")
                    else:
                        await asyncio.sleep(0.1 * (attempt + 1))
                        
        except Exception as e:
            self.log.error(f"Error updating schedule: {str(e)}")
            # Log the current state for debugging
            self.log.error(f"Current state - Blocks: {len(self.horario_json['Asignaturas'])}, "
                        f"Subject: {self.asignatura_actual}/{len(self.asignaturas)}")

    def get_tipo_contrato(self) -> TipoContrato:
        """Get the contract type based on total teaching hours."""
        return self.inferir_tipo_contrato(self.asignaturas)
    
    def set_storage(self, storage : ProfesorScheduleStorage):
        self.storage = storage

    async def _actualizar_horario_json(self, dia: Day, sala: str, bloque: int, satisfaccion: int):
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

    @staticmethod
    def sanitize_subject_name(name: str) -> str:
        return ''.join(c for c in name if c.isalnum())

    async def cleanup(self):
        """Simplified cleanup that avoids behavior killing but addresses locks"""
        try:
        # Use a timeout for the entire cleanup operation
        # async with asyncio.timeout(10):  # 10 second total timeout
            # async with self.cleanup_lock:
            if self.is_cleaning_up:
                self.log.warning("Cleanup already in progress, skipping...")
                return
                
            self.is_cleaning_up = True
            self.log.info(f"Starting cleanup for professor {self.nombre}")
            
            # 1. Flush metrics - with timeout
            if self.metrics_monitor:
                try:
                    # async with asyncio.timeout(2):
                    await self.metrics_monitor._flush_all()
                except asyncio.TimeoutError:
                    self.log.error("Metrics flush timed out, continuing")
            
            """
            # 2. Deregister from knowledge base - with timeout
            if self._kb:
                try:
                    async with asyncio.timeout(2):
                        await self._kb.deregister_agent(self.jid)
                except asyncio.TimeoutError:
                    self.log.error("KB deregistration timed out, continuing") """
            
            # 3. Final storage flush - with timeout
            if self.storage is not None:
                try:
                    #async with asyncio.timeout(2):
                    await self.storage.force_flush()
                except asyncio.TimeoutError:
                    self.log.error("Storage flush timed out, continuing")
            
            # 4. Brief pause then stop agent
            # await asyncio.sleep(0.1)
            await self.stop()
            self.log.info("Agent stopped successfully")
        except asyncio.TimeoutError:
            self.log.error("Overall cleanup timed out, forcing stop")
            await self.stop()
        except Exception as e:
            self.log.error(f"Critical error in cleanup: {str(e)}")
            await self.stop()
        finally:
            # Ensure the cleanup state is reset even if there was an error
            self.is_cleaning_up = False
            self.log.info(f"Cleanup completed for professor {self.nombre}")

    async def export_schedule_json(self) -> Dict:
        return {
            "nombre": self.nombre,
            "asignaturas": self.horario_json["Asignaturas"],
            "completadas": len(self.horario_json["Asignaturas"]),
            "total": len(self.asignaturas)
        }