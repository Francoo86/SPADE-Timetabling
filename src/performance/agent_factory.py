from .metrics_monitor import MetricsMonitor
from agents.sala_agent import AgenteSala
from agents.profesor_redux import AgenteProfesor
from agents.supervisor import AgenteSupervisor
from spade.behaviour import PeriodicBehaviour
import time
from datetime import datetime
import asyncio

class AgentFactory:
    def __init__(self):
        # get todays date
        today = datetime.now()
        mas_metrics_file = f"mas_metrics_{today.strftime('%Y-%m-%d')}.csv"
        request_metrics_file = f"request_metrics_{today.strftime('%Y-%m-%d')}.csv"
        
        self.metrics_monitor = MetricsMonitor(
            output_file=mas_metrics_file,
            request_log_file=request_metrics_file
        )
        
        asyncio.create_task(self.metrics_monitor.start())

    async def create_professor(self, jid: str, password: str, nombre: str, asignaturas: list, orden: int) -> AgenteProfesor:
        """Create professor agent with non-blocking metrics monitoring"""
        agent = AgenteProfesor(jid, password, nombre, asignaturas, orden)
        agent.metrics_monitor = self.metrics_monitor
        
        # Store original methods
        original_setup = agent.setup
        original_move_next = agent.move_to_next_subject
        original_update_schedule = agent.update_schedule_info
        
        async def setup_with_metrics(self):
            start_time = time.time()
            try:
                await original_setup()
            finally:
                end_time = time.time()
                self.metrics_monitor.measure_rtt(self.nombre, start_time, end_time)
                await self.metrics_monitor.log_request(
                    self.nombre,
                    "professor_setup",
                    start_time,
                    end_time
                )
                
        async def move_next_with_metrics(self):
            start_time = time.time()
            try:
                await original_move_next()
            finally:
                end_time = time.time()
                await self.metrics_monitor.log_request(
                    self.nombre,
                    "move_next_subject",
                    start_time,
                    end_time
                )
                
        async def update_schedule_with_metrics(self, dia, sala, bloque, nombre_asignatura, satisfaccion):
            start_time = time.time()
            try:
                await original_update_schedule(dia, sala, bloque, nombre_asignatura, satisfaccion)
            finally:
                end_time = time.time()
                await self.metrics_monitor.log_request(
                    self.nombre,
                    "update_schedule",
                    start_time,
                    end_time,
                    details=f"Room: {sala}, Block: {bloque}"
                )
                
        # Bind wrapped methods
        agent.setup = setup_with_metrics.__get__(agent)
        agent.move_to_next_subject = move_next_with_metrics.__get__(agent)
        agent.update_schedule_info = update_schedule_with_metrics.__get__(agent)
        
        return agent

    async def create_classroom(self, jid: str, password: str, codigo: str, campus: str, 
                             capacidad: int, turno: int) -> AgenteSala:
        """Create classroom agent with non-blocking metrics monitoring"""
        agent = AgenteSala(jid, password, codigo, campus, capacidad, turno)
        agent.metrics_monitor = self.metrics_monitor
        
        # Store original methods
        original_setup = agent.setup
        original_process_request = agent.responder_behaviour.process_request
        original_confirm = agent.responder_behaviour.confirm_assignment
        
        async def setup_with_metrics(self):
            start_time = time.time()
            try:
                await original_setup()
            finally:
                end_time = time.time()
                await self.metrics_monitor.log_request(
                    self.codigo,
                    "classroom_setup",
                    start_time,
                    end_time
                )
                
        async def process_request_with_metrics(behaviour_self, msg):
            start_time = time.time()
            try:
                await original_process_request(msg)
            finally:
                end_time = time.time()
                await agent.metrics_monitor.log_request(
                    agent.codigo,
                    "process_request",
                    start_time,
                    end_time,
                    details=f"From: {msg.sender}"
                )
                
        async def confirm_with_metrics(behaviour_self, msg):
            start_time = time.time()
            try:
                await original_confirm(msg)
            finally:
                end_time = time.time()
                await agent.metrics_monitor.log_request(
                    agent.codigo,
                    "confirm_assignment",
                    start_time,
                    end_time,
                    details=f"From: {msg.sender}"
                )
        
        # Bind methods properly
        agent.setup = setup_with_metrics.__get__(agent)
        agent.responder_behaviour.process_request = process_request_with_metrics.__get__(agent.responder_behaviour)
        agent.responder_behaviour.confirm_assignment = confirm_with_metrics.__get__(agent.responder_behaviour)
        
        return agent

    async def create_supervisor(self, jid: str, password: str, professor_jids: list) -> AgenteSupervisor:
        """Create supervisor agent with non-blocking metrics monitoring"""
        agent = AgenteSupervisor(jid, password, professor_jids)
        agent.metrics_monitor = self.metrics_monitor
        
        # Add CPU monitoring behavior
        class CPUMonitorBehaviour(PeriodicBehaviour):
            async def run(self):
                self.agent.metrics_monitor.measure_cpu_usage()
                
        agent.add_behaviour(CPUMonitorBehaviour(period=5))
        
        return agent