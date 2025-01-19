from spade.agent import Agent
from typing import Dict, List, Optional
from queue import Queue
import asyncio
from objects.asignation_data import Asignatura
from objects.static.agent_enums import TipoContrato, Day
from behaviours.negotiation_behaviour import NegotiationStateBehaviour
from behaviours.message_collector import MessageCollectorBehaviour
from behaviours.requests_behaviour import EsperarTurnoBehaviour
from objects.asignation_data import BloqueInfo

class AgenteProfesor(Agent):
    AGENT_NAME = "Profesor"
    SERVICE_NAME = AGENT_NAME.lower()
    
    def __init__(self, jid: str, password: str, nombre: str, asignaturas: List[Asignatura]):
        super().__init__(jid, password)
        self.nombre = nombre
        self.asignaturas = asignaturas
        self.asignatura_actual = 0
        self.horario_ocupado = {}  # dia -> set(bloques)
        self.orden = None  # Will be set during setup
        self.horario_json = {}
        self.bloques_asignados_por_dia = {}  # dia -> {asignatura -> List[bloques]}
        self.instance_counter = 0
        self.current_instance_index = 0
        self._initialize_data_structures()

    def _initialize_data_structures(self):
        """Initialize all data structures needed for the agent."""
        # Initialize schedule tracking
        self.horario_ocupado = {day: set() for day in Day}
        
        # Initialize JSON structures
        self.horario_json = {"Asignaturas": []}
        
        # Initialize daily block assignments
        self.bloques_asignados_por_dia = {day: {} for day in Day}

    async def setup(self):
        """Setup the agent behaviors and structures."""
        batch_proposals = Queue()
        state_behaviour = NegotiationStateBehaviour(self, batch_proposals)
        
        if self.orden == 0:
            self.add_behaviour(state_behaviour)
            self.add_behaviour(MessageCollectorBehaviour(self, batch_proposals, state_behaviour))
        else:
            self.add_behaviour(EsperarTurnoBehaviour(self, state_behaviour, MessageCollectorBehaviour(self, batch_proposals, state_behaviour)))    
    

    def can_use_more_subjects(self) -> bool:
        """Check if there are more subjects to process."""
        try:
            if self.asignatura_actual >= len(self.asignaturas):
                return False
                
            current = self.asignaturas[self.asignatura_actual]
            if current is None:
                self.log.warning(f"Warning: Null subject at index {self.asignatura_actual}")
                return False
                
            return True
        except IndexError:
            self.log.error(f"Index out of bounds checking for more subjects: "
                          f"{self.asignatura_actual}/{len(self.asignaturas)}")
            return False

    def get_current_subject(self) -> Optional[Asignatura]:
        """Get the current subject being processed."""
        if not self.can_use_more_subjects():
            return None
        return self.asignaturas[self.asignatura_actual]

    def move_to_next_subject(self):
        """Move to the next subject in the list."""
        self.log.info(f"[MOVE] Moving from subject index {self.asignatura_actual} "
                     f"(total: {len(self.asignaturas)})")
        
        if self.asignatura_actual >= len(self.asignaturas):
            self.log.info("[MOVE] Already at last subject")
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
                self.log.info(f"[MOVE] Moving to next instance ({self.current_instance_index}) "
                            f"of {current_name}")
            else:
                self.current_instance_index = 0
                self.log.info(f"[MOVE] Moving to new subject {next_subject.get_nombre()}")
        else:
            self.log.info("[MOVE] Reached end of subjects")

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