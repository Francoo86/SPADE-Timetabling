import asyncio
from typing import Dict, List, Optional
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from spade.template import Template
import json
import logging

import sys

from pathlib import Path
from src.agents.profesor_redux import AgenteProfesor
from src.agents.sala_agent import AgenteSala
from src.agents.supervisor import AgenteSupervisor
from src.objects.knowledge_base import AgentKnowledgeBase

from json_stuff.json_salas import SalaScheduleStorage
from json_stuff.json_profesores import ProfesorScheduleStorage
from src.fipa.acl_message import FIPAPerformatives

from src.performance.agent_factory import AgentFactory
from src.performance.rtt_stats import RTTLogger
import time

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='agent_logs.log',  # Specify the file to write logs
    filemode='w'  # Optional: Use 'w' to overwrite the file each time, or 'a' to append
)
logger = logging.getLogger(__name__)

class ApplicationAgent(Agent):
    """
    Main application controller agent that manages the lifecycle of other agents
    """
    def __init__(self, jid: str, password: str, room_data: List[dict], 
                 professor_data: List[dict], scenario: str = "small"):
        super().__init__(jid, password, verify_security=False)
        self.room_data = room_data
        self.professor_data = professor_data
        self.room_agents: Dict[str, Agent] = {}
        self.professor_agents: List[Agent] = []
        self.supervisor_agent: Optional[Agent] = None
        self.is_running = True
        self._kb = None
        self.rtt_logger : 'RTTLogger' = None
        
        self._rooms_ready = False
        self._professors_ready = False
        self._supervisor_ready = False
        
        self.prof_storage = None
        self.room_storage = None
        
        # ULTIMATUM
        self.end_event = asyncio.Event()
        self.factory = AgentFactory(scenario=scenario)
        
        self.scenario = scenario
    
    async def get_system_status(self, request):
        """Web endpoint to get overall system status"""
        return {
            "rooms_ready": self._rooms_ready,
            "professors_ready": self._professors_ready,
            "supervisor_ready": self._supervisor_ready,
            "active_professors": len([p for p in self.professor_agents if p.is_alive()]),
            "active_rooms": len([r for r in self.room_agents.values() if r.is_alive()])
        }

    async def get_agent_status(self, request):
        """Web endpoint to get detailed agent status"""
        status = {
            "professors": {},
            "rooms": {}
        }
        
        # Collect professor status
        for prof in self.professor_agents:
            subject = prof.get_current_subject()
            
            status["professors"][str(prof.jid)] = {
                "alive": prof.is_alive(),
                "current_subject": subject.get_nombre() if subject else None,
                "pending_blocks": getattr(prof, "bloques_pendientes", 0),
                "order": prof.orden
            }
            
        # Collect room status  
        for code, room in self.room_agents.items():
            status["rooms"][code] = {
                "alive": room.is_alive(),
                "assignments": len([a for day in room.horario_ocupado.values() 
                                for a in day if a is not None])
            }
            
        return status
        
    async def setup(self):
        self.web.start(hostname="127.0.0.1", port=20000)
        self.web.add_get("/status", self.get_system_status, template=None)
        self.web.add_get("/agents", self.get_agent_status, template=None)
    
        """Initialize agent behaviors and start agent creation sequence"""
        logger.info("Application agent starting...")
        self._kb = await AgentKnowledgeBase.get_instance()
        self._kb.set_scenario(self.scenario)
        
        # Initialize storage instances
        self.prof_storage = await ProfesorScheduleStorage.get_instance()
        self.room_storage = await SalaScheduleStorage.get_instance()
        
        self.prof_storage.set_scenario(self.scenario)
        self.room_storage.set_scenario(self.scenario)
        
        # Initialize RTT logger
        logger.info("Initializing RTT logger...")
        self.rtt_logger = await RTTLogger(self.scenario)
        await self.rtt_logger.start()
        
        # Add startup coordinator behavior
        startup_template = Template()
        startup_template.set_metadata("conversation-id", "startup-sequence")
        self.add_behaviour(self.StartupCoordinatorBehaviour(factory=self.factory), startup_template)
        
        # Add monitoring behavior
        monitor_template = Template()
        monitor_template.set_metadata("conversation-id", "system-monitor")
        self.add_behaviour(self.SystemMonitorBehaviour(period=5), monitor_template)

    class StartupCoordinatorBehaviour(CyclicBehaviour):
        """Coordinates the startup sequence of all agents"""
        def __init__(self, factory : AgentFactory):
            super().__init__()
            self.factory = factory
        
        async def on_start(self):
            """Initialize startup sequence"""
            self.current_stage = 0
            self.stages = [
                self.initialize_rooms,
                self.initialize_professors,
                self.initialize_supervisor,
                self.start_negotiations
            ]
            
        async def run(self):
            start_time = time.time()
            try:
                # 1. Initialize rooms first
                if not self.agent._rooms_ready:
                    await self.initialize_rooms()
                    self.agent._rooms_ready = True
                    await self.factory.metrics_monitor.log_request(
                        "SystemStartup",
                        "system_initialization",
                        start_time,
                        time.time(),
                        details="Rooms initialized"
                    )
                    return

                # 2. Initialize professors after rooms
                if not self.agent._professors_ready:
                    await self.initialize_professors()
                    self.agent._professors_ready = True
                    await self.factory.metrics_monitor.log_request(
                        "SystemStartup",
                        "system_initialization",
                        start_time,
                        time.time(),
                        details="Professors initialized"
                    )
                    return

                # 3. Initialize supervisor
                if not self.agent._supervisor_ready:
                    await self.initialize_supervisor()
                    self.agent._supervisor_ready = True
                    await self.factory.metrics_monitor.log_request(
                        "SystemStartup",
                        "system_initialization",
                        start_time,
                        time.time(),
                        details="Supervisor initialized"
                    )
                    return

                # 4. Start negotiations when ready
                if (self.agent._rooms_ready and 
                    self.agent._professors_ready and 
                    self.agent._supervisor_ready):
                    
                    negotiation_start = time.time()
                    
                    # Start first professor
                    first_prof = self.agent.professor_agents[0]
                    msg = Message(to=str(first_prof.jid))
                    msg.set_metadata("performative", FIPAPerformatives.INFORM)
                    msg.set_metadata("conversation-id", "negotiation-start-base")
                    msg.body = "START"
                    
                    await self.send(msg)
                    await self.factory.metrics_monitor.log_request(
                        "SystemStartup",
                        "start_negotiations",
                        negotiation_start,
                        time.time(),
                        details="First professor started"
                    )
                    
                    await self.factory.metrics_monitor.log_request(
                        "SystemStartup",
                        "system_initialization",
                        start_time,
                        time.time(),
                        details="System fully initialized"
                    )
                    print("[GOOD] System initialization complete - Starting negotiations")
                    await asyncio.sleep(0.1)
                    self.kill()
                    
            except Exception as e:
                await self.factory.metrics_monitor.log_request(
                    "SystemStartup",
                    "system_initialization",
                    start_time,
                    time.time(),
                    status="error",
                    details=f"Error: {str(e)}"
                )
                print(f"[FATAL] Error in startup sequence: {str(e)}")

        async def initialize_rooms(self):
            """Initialize and start room agents with metrics"""
            start_time = time.time()
            logger.info("Initializing room agents...")
            rooms_started = 0
            rooms_failed = 0
            
            for room_data in self.agent.room_data:
                try:
                    room_jid = f"Sala{room_data['Codigo']}@{self.agent.jid.domain}"
                    
                    # Create room through factory for metrics integration
                    room = await self.factory.create_classroom(
                        jid=room_jid,
                        password=self.agent.password,
                        codigo=room_data.get("Codigo"),
                        campus=room_data.get("Campus"),
                        capacidad=room_data.get("Capacidad"),
                        turno=room_data.get("Turno")
                    )
                    
                    room.set_storage(self.agent.room_storage)
                    room.set_knowledge_base(self.agent._kb)
                    room.set_rtt_logger(self.agent.rtt_logger)
                    await room.start(auto_register=True)
                    self.agent.room_agents[room_data['Codigo']] = room
                    logger.info(f"Room agent started: {room_jid}")
                    rooms_started += 1
                    
                except Exception as e:
                    logger.error(f"Failed to start room agent: {e}")
                    rooms_failed += 1
            
            status = "partial_failure" if rooms_failed > 0 else "completed"
            await self.factory.metrics_monitor.log_request(
                "SystemStartup",
                "initialize_rooms",
                start_time,
                time.time(),
                status=status,
                details=f"Started: {rooms_started}, Failed: {rooms_failed}"
            )
                    
            await asyncio.sleep(2)  # Allow rooms to initialize

        async def initialize_professors(self):
            """Initialize and start professor agents with metrics"""
            start_time = time.time()
            logger.info("Initializing professor agents...")
            profs_started = 0
            profs_failed = 0
            
            for i, prof_data in enumerate(self.agent.professor_data):
                try:
                    prof_jid = f"Profesor{i}@{self.agent.jid.domain}"
                    
                    # Create professor through factory for metrics integration
                    professor = await self.factory.create_professor(
                        jid=prof_jid,
                        password=self.agent.password,
                        nombre=prof_data.get("Nombre"),
                        asignaturas=prof_data.get("Asignaturas"),
                        orden=i
                    )
                    
                    professor.set_storage(self.agent.prof_storage)
                    professor.set_knowledge_base(self.agent._kb)
                    professor.set_rtt_logger(self.agent.rtt_logger)
                    await professor.start(auto_register=True)
                    self.agent.professor_agents.append(professor)
                    logger.info(f"Professor agent started: {prof_jid}")
                    profs_started += 1
                    
                except Exception as e:
                    logger.error(f"Failed to start professor agent: {e}")
                    profs_failed += 1
            
            status = "partial_failure" if profs_failed > 0 else "completed"
            await self.factory.metrics_monitor.log_request(
                "SystemStartup",
                "initialize_professors",
                start_time,
                time.time(),
                status=status,
                details=f"Started: {profs_started}, Failed: {profs_failed}"
            )
                    
            await asyncio.sleep(2)  # Allow professors to initialize

        async def initialize_supervisor(self):
            """Initialize and start supervisor agent with metrics"""
            start_time = time.time()
            logger.info("Initializing supervisor agent...")
            
            try:
                supervisor_jid = f"Supervisor@{self.agent.jid.domain}"
                
                # Create supervisor through factory for metrics integration
                supervisor = await self.factory.create_supervisor(
                    jid=supervisor_jid,
                    password=self.agent.password,
                    professor_jids=[agent.jid for agent in self.agent.professor_agents]
                )
                
                supervisor.add_finalizer_event(self.agent.end_event)
                supervisor.set_storages(self.agent.room_storage, self.agent.prof_storage)
                supervisor.set_knowledge_base(self.agent._kb)
                await supervisor.start(auto_register=True)
                self.agent.supervisor_agent = supervisor
                logger.info(f"Supervisor agent started: {supervisor_jid}")
                
                await self.factory.metrics_monitor.log_request(
                    "SystemStartup",
                    "initialize_supervisor",
                    start_time,
                    time.time(),
                    details="Supervisor started successfully"
                )
                
            except Exception as e:
                logger.error(f"Failed to start supervisor agent: {e}")
                await self.factory.metrics_monitor.log_request(
                    "SystemStartup",
                    "initialize_supervisor",
                    start_time,
                    time.time(),
                    status="error",
                    details=f"Error: {str(e)}"
                )
                
            await asyncio.sleep(2)  # Allow supervisor to initialize
            
        async def start_negotiations(self):
            """Trigger the start of negotiations"""
            logger.info("Starting negotiation process...")
            
            try:
                # Send start signal to first professor
                if self.agent.professor_agents:
                    msg = Message(to=str(self.agent.professor_agents[0].jid))
                    msg.set_metadata("performative", FIPAPerformatives.INFORM)
                    msg.set_metadata("conversation-id", "negotiation-start-base")
                    msg.body = "START"
                    await self.send(msg)
                    logger.info("Sent START signal to first professor")
                    
            except Exception as e:
                logger.error(f"Failed to start negotiations: {e}")
                
        async def cleanup(self):
            """Clean up in case of startup failure"""
            logger.info("Cleaning up due to startup failure...")
            await self.agent.stop()

    class SystemMonitorBehaviour(PeriodicBehaviour):
        """Monitors system status and handles shutdown"""
        
        async def run(self):
            """Check system status and manage shutdown if needed"""
            try:
                if self.agent.supervisor_agent:
                    system_active = self.agent.supervisor_agent.get("system_active")
                    if not system_active:
                        logger.info("System completion detected, initiating shutdown...")
                        await self.initiate_shutdown()
                        
            except Exception as e:
                logger.error(f"Error in system monitor: {e}")
                
        async def initiate_shutdown(self):
            """Coordinate graceful system shutdown"""
            logger.info("Beginning system shutdown sequence...")
            
            # Stop agents in reverse order
            cleanup_tasks = []
            
            if self.agent.supervisor_agent:
                cleanup_tasks.append(self.agent.supervisor_agent.stop())
                
            for agent in reversed(self.agent.professor_agents):
                cleanup_tasks.append(agent.stop())
                
            for agent in reversed(list(self.agent.room_agents.values())):
                cleanup_tasks.append(agent.stop())
                
            # Wait for all cleanup tasks
            if cleanup_tasks:
                await asyncio.gather(*cleanup_tasks)
                
            # Stop the application agent
            self.agent.is_running = False
            await self.agent.stop()
            self.agent.end_event.set()
            
            logger.info("System shutdown complete")

class ApplicationRunner:
    """Manages the SPADE application lifecycle"""
    
    def __init__(self, xmpp_server: str, password: str, scenario : str = "small"):
        self.xmpp_server = xmpp_server
        self.password = password
        self.app_agent: Optional[ApplicationAgent] = None
        self.scenario = scenario
        
    def load_json(self, filename: str) -> List[dict]:
        """Load JSON data from file"""
        try:
            path = Path(__file__).parent / "data" / filename
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
            return []
            
    async def run(self):
        """Run the SPADE application"""
        try:
            # Load configuration data
            professors_data = self.load_json(f"scenarios/{self.scenario}/profesores.json")
            rooms_data = self.load_json(f"scenarios/{self.scenario}/salas.json")
            
            if not professors_data or not rooms_data:
                logger.error("Failed to load required data files")
                return
                
            # Create and start application agent
            app_jid = f"application@{self.xmpp_server}"
            app_agent = ApplicationAgent(
                app_jid,
                self.password,
                rooms_data,
                professors_data,
                scenario=self.scenario
            )
            
            self.app_agent = app_agent
            
            await app_agent.start(auto_register=True)
            logger.info("Application agent started successfully")
            
            # Wait for completion using the end_event
            try:
                await self.app_agent.end_event.wait()
            except KeyboardInterrupt:
                logger.info("Received shutdown signal")
                
        except Exception as e:
            logger.error(f"Application error: {e}")
            
        finally:
            # Ensure proper SPADE shutdown
            await self.cleanup()
            logger.info("SPADE platform shutdown complete")
            
    async def cleanup(self):
        # close all the agents
        """Stop all agents and clean up resources"""
        print("\nCleaning up platform...")
        
        cleanup_tasks = []
        
        # Stop all agents in reverse order
        if self.app_agent.supervisor_agent:
            cleanup_tasks.append(self.app_agent.supervisor_agent.stop())
            
        for agent in reversed(self.app_agent.professor_agents):
            cleanup_tasks.append(agent.stop())
            
        for agent in reversed(list(self.app_agent.room_agents.values())):
            cleanup_tasks.append(agent.stop())

        # Wait for all cleanup tasks to complete
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks)
        
        print("Platform shutdown complete.")

def main():
    """Main entry point"""
    import os
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    xmpp_server = os.getenv("XMPP_SERVER")
    password = os.getenv("AGENT_PASSWORD")
    
    if not xmpp_server or not password:
        logger.error("XMPP_SERVER and AGENT_PASSWORD must be set in .env file")
        sys.exit(1)
        
    # Run the application
    runner = ApplicationRunner(xmpp_server, password, "medium")
    asyncio.run(runner.run())

if __name__ == "__main__":
    main()