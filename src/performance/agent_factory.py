from .metrics_monitor import ActionsMonitor
from .lightweight_monitor import CentralizedPerformanceMonitor
from ..agents.sala_agent import AgenteSala
from ..agents.profesor_redux import AgenteProfesor
from ..agents.supervisor import AgenteSupervisor
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
        
        self.metrics_monitor = ActionsMonitor(
            output_file=mas_metrics_file,
            request_log_file=request_metrics_file
        )
        
        asyncio.create_task(self.metrics_monitor.start())
        # asyncio.create_task(CentralizedPerformanceMonitor.initialize(self.scenario))
        
    def patch_agent(self, agent: Agent, agent_type: str, agent_name: str):
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
    def create_professor(self, jid: str, password: str, nombre: str, asignaturas: list, orden: int) -> AgenteProfesor:
        """Create professor agent with non-blocking metrics monitoring"""
        agent = AgenteProfesor(jid, password, nombre, asignaturas, orden, self.scenario)
        agent.metrics_monitor = self.metrics_monitor
        
        # self.patch_agent(agent, "professor", nombre)
        return agent

    def create_classroom(self, jid: str, password: str, codigo: str, campus: str,
                         capacidad: int, turno: int) -> AgenteSala:
        """Create classroom agent with non-blocking metrics monitoring"""
        agent = AgenteSala(jid, password, codigo, campus, capacidad, turno, self.scenario)
        agent.metrics_monitor = self.metrics_monitor

        # self.patch_agent(agent, "classroom", codigo)
        return agent

    def create_supervisor(self, jid: str, password: str, professor_jids: list) -> AgenteSupervisor:
        """Create supervisor agent with non-blocking metrics monitoring"""
        agent = AgenteSupervisor(jid, password, professor_jids, self.scenario)
        agent.metrics_monitor = self.metrics_monitor
        return agent