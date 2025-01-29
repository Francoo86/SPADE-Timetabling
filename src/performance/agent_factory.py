from .metrics_monitor import MetricsMonitor, RequestTimer
from agents.sala_agent import AgenteSala
from agents.profesor_redux import AgenteProfesor
from agents.supervisor import AgenteSupervisor
from spade.behaviour import PeriodicBehaviour
from functools import partial

class AgentFactory:
    def __init__(self):
        # Create single metrics monitor instance for all agents
        self.metrics_monitor = MetricsMonitor(
            output_file="mas_metrics.csv",
            request_log_file="request_metrics.csv"
        )

    async def create_professor(self, jid: str, password: str, nombre: str, asignaturas: list, orden: int) -> AgenteProfesor:
        """Create professor agent with metrics monitoring"""
        agent = AgenteProfesor(jid, password, nombre, asignaturas, orden)
        agent.metrics_monitor = self.metrics_monitor
        
        # Wrap key methods with metrics
        original_setup = agent.setup
        original_move_next = agent.move_to_next_subject
        original_update_schedule = agent.update_schedule_info
        
        async def setup_with_metrics(self):
            async with RequestTimer(self.metrics_monitor, self.nombre, "professor_setup"):
                await original_setup()
                
        async def move_next_with_metrics(self):
            async with RequestTimer(self.metrics_monitor, self.nombre, "move_next_subject"):
                await original_move_next()
                
        async def update_schedule_with_metrics(self, dia, sala, bloque, nombre_asignatura, satisfaccion):
            async with RequestTimer(
                self.metrics_monitor, 
                self.nombre, 
                "update_schedule",
                f"Room: {sala}, Block: {bloque}"
            ):
                await original_update_schedule(dia, sala, bloque, nombre_asignatura, satisfaccion)
                
        agent.setup = setup_with_metrics.__get__(agent)
        agent.move_to_next_subject = move_next_with_metrics.__get__(agent)
        agent.update_schedule_info = update_schedule_with_metrics.__get__(agent)
        
        return agent

    async def create_classroom(self, jid: str, password: str, codigo: str, campus: str, 
                             capacidad: int, turno: int) -> AgenteSala:
        """Create classroom agent with metrics monitoring"""
        agent = AgenteSala(jid, password, codigo, campus, capacidad, turno)
        agent.metrics_monitor = self.metrics_monitor
        
        # Store original methods
        original_setup = agent.setup
        original_process_request = agent.responder_behaviour.process_request
        original_confirm = agent.responder_behaviour.confirm_assignment
        
        # Define wrapped methods properly bound to the behaviour instance
        async def setup_with_metrics(self):
            async with RequestTimer(self.metrics_monitor, self.codigo, "classroom_setup"):
                await original_setup()
                
        async def process_request_with_metrics(behaviour_self, msg):
            async with RequestTimer(
                agent.metrics_monitor,  # Use agent's monitor
                agent.codigo,           # Use agent's code
                "process_request",
                f"From: {msg.sender}"
            ):
                await original_process_request(msg)
                
        async def confirm_with_metrics(behaviour_self, msg):
            async with RequestTimer(
                agent.metrics_monitor,
                agent.codigo,
                "confirm_assignment",
                f"From: {msg.sender}"
            ):
                await original_confirm(msg)
        
        # Bind methods properly
        agent.setup = setup_with_metrics.__get__(agent)
        agent.responder_behaviour.process_request = process_request_with_metrics.__get__(agent.responder_behaviour)
        agent.responder_behaviour.confirm_assignment = confirm_with_metrics.__get__(agent.responder_behaviour)
        
        return agent

    async def create_supervisor(self, jid: str, password: str, professor_jids: list) -> AgenteSupervisor:
        """Create supervisor agent with metrics monitoring"""
        agent = AgenteSupervisor(jid, password, professor_jids)
        agent.metrics_monitor = self.metrics_monitor
        
        # Add CPU monitoring behavior
        class CPUMonitorBehaviour(PeriodicBehaviour):
            async def run(self):
                await self.agent.metrics_monitor.measure_cpu_usage()
                
        agent.add_behaviour(CPUMonitorBehaviour(period=5))  # Monitor every 5 seconds
        
        return agent