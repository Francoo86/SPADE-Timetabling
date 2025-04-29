from .metrics_monitor import MetricsMonitor
from .lightweight_monitor import CentralizedPerformanceMonitor
from agents.sala_agent import AgenteSala
from agents.profesor_redux import AgenteProfesor
from agents.supervisor import AgenteSupervisor
# from spade.behaviour import PeriodicBehaviour
import time
from datetime import datetime
import asyncio
import os
from spade.agent import Agent
FILE_PATH = os.path.dirname(os.path.abspath(__file__))
# GO TWO DIRECTORIES UP
OUTPUT_DIR = os.path.abspath(os.path.join(FILE_PATH, "..", "..", "agent_output", "Metrics"))

class AgentFactory:
    def __init__(self, scenario: str = "small"):
        # get todays date
        today = datetime.now()

        mas_metrics_file = f"mas_metrics_{today.strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        request_metrics_file = f"request_metrics_{today.strftime('%Y-%m-%d_%H-%M-%S')}.csv"
        self.scenario = scenario
        
        # set scenario in metrics monitor
        mas_metrics_file = os.path.join(OUTPUT_DIR, scenario, mas_metrics_file)
        request_metrics_file = os.path.join(OUTPUT_DIR, scenario, request_metrics_file)
        
        if not os.path.exists(os.path.join(OUTPUT_DIR, scenario)):
            os.makedirs(os.path.join(OUTPUT_DIR, scenario), exist_ok=True)
        
        self.metrics_monitor = MetricsMonitor(
            output_file=mas_metrics_file,
            request_log_file=request_metrics_file
        )
        
        asyncio.create_task(self.metrics_monitor.start())
        asyncio.create_task(CentralizedPerformanceMonitor.initialize(self.scenario))
        
    async def patch_agent(self, agent: Agent, agent_type: str, agent_name: str):
        # assume it is registering
        original_start = agent.start
        # this is for unregistering
        original_stop = agent.stop
        
        async def start_with_metrics(self, *args, **kwargs):
            start_time = time.time()
            try:
                await original_start(*args, **kwargs)
            finally:
                end_time = time.time()
                await self.metrics_monitor.log_request(
                    agent_name,
                    f"{agent_type}_start",
                    start_time,
                    end_time
                )
        
        async def stop_with_metrics(self):
            start_time = time.time()
            try:
                await original_stop()
            finally:
                end_time = time.time()
                await self.metrics_monitor.log_request(
                    agent_name,
                    f"{agent_type}_stop",
                    start_time,
                    end_time
                )
                
        agent.start = start_with_metrics.__get__(agent)
        agent.stop = stop_with_metrics.__get__(agent)
        
        return agent
    

    # i hate both of these methods.
    async def create_professor(self, jid: str, password: str, nombre: str, asignaturas: list, orden: int) -> AgenteProfesor:
        """Create professor agent with non-blocking metrics monitoring"""
        agent = AgenteProfesor(jid, password, nombre, asignaturas, orden, self.scenario)
        agent.metrics_monitor = self.metrics_monitor
        
        await self.patch_agent(agent, "professor", nombre)
            
                
        """
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
                )"""
                
        # agent.start = start_with_metrics.__get__(agent)
        #agent.move_to_next_subject = move_next_with_metrics.__get__(agent)
        # agent.update_schedule_info = update_schedule_with_metrics.__get__(agent)
        
        return agent

    async def create_classroom(self, jid: str, password: str, codigo: str, campus: str, 
                             capacidad: int, turno: int) -> AgenteSala:
        """Create classroom agent with non-blocking metrics monitoring"""
        agent = AgenteSala(jid, password, codigo, campus, capacidad, turno, self.scenario)
        agent.metrics_monitor = self.metrics_monitor
        
        await self.patch_agent(agent, "classroom", codigo)
        
        """
        original_start = agent.start
        original_process_request = agent.responder_behaviour.process_request
        original_confirm = agent.responder_behaviour.confirm_assignment
        
        async def start_with_metrics(self):
            start_time = time.time()
            try:
                await original_start()
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
                ) """
        
        # we need to measure the start = registration time.
        # agent.start = start_with_metrics.__get__(agent)
        #agent.responder_behaviour.process_request = process_request_with_metrics.__get__(agent.responder_behaviour)
        #agent.responder_behaviour.confirm_assignment = confirm_with_metrics.__get__(agent.responder_behaviour)
        
        return agent

    async def create_supervisor(self, jid: str, password: str, professor_jids: list) -> AgenteSupervisor:
        """Create supervisor agent with non-blocking metrics monitoring"""
        agent = AgenteSupervisor(jid, password, professor_jids, self.scenario)
        # agent.set_metrics_monitor(self.metrics_monitor)
        
        # Add CPU monitoring behavior
        # class CPUMonitorBehaviour(PeriodicBehaviour):
        #     async def run(self):
        #         self.agent.metrics_monitor.measure_cpu_usage()
                
        # agent.add_behaviour(CPUMonitorBehaviour(period=5))
        
        return agent