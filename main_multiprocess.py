import asyncio
import threading
from typing import Dict, List, Optional
from spade.agent import Agent
from spade.container import Container
import json
import logging
from pathlib import Path
import os
from dotenv import load_dotenv
import queue

from src.agents.profesor_redux import AgenteProfesor
from src.agents.sala_agent import AgenteSala
from src.agents.supervisor import AgenteSupervisor
from src.objects.knowledge_base import AgentKnowledgeBase
from json_stuff.json_salas import SalaScheduleStorage
from json_stuff.json_profesores import ProfesorScheduleStorage

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='agent_logs.log',
    filemode='w'
)
logger = logging.getLogger(__name__)

class AgentThread(threading.Thread):
    """Base class for agent threads"""
    def __init__(self, jid: str, password: str):
        super().__init__()
        self.jid = jid
        self.password = password
        self.agent = None
        self.ready_event = threading.Event()
        self.error = None
        self._loop = None

    def run(self):
        """Thread's main run method"""
        try:
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # Run agent setup
            self._loop.run_until_complete(self._setup_agent())
            
            # Run event loop
            self._loop.run_forever()
        except Exception as e:
            self.error = e
            logger.error(f"Error in agent thread {self.jid}: {e}")
        finally:
            if self._loop:
                self._loop.close()

    async def _setup_agent(self):
        """Must be implemented by subclasses"""
        raise NotImplementedError

    async def stop(self):
        """Stop the agent and thread"""
        if self._loop and self.agent:
            async def _stop():
                if self.agent.is_alive():
                    await self.agent.stop()
            
            future = asyncio.run_coroutine_threadsafe(_stop(), self._loop)
            future.result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)

class RoomThread(AgentThread):
    """Thread for room agents"""
    def __init__(self, jid: str, password: str, room_data: dict, kb: AgentKnowledgeBase):
        super().__init__(jid, password)
        self.room_data = room_data
        self.kb = kb

    async def _setup_agent(self):
        # Create and start room agent
        storage = await SalaScheduleStorage.get_instance()
        self.agent = AgenteSala(
            jid=self.jid,
            password=self.password,
            codigo=self.room_data.get("Codigo"),
            campus=self.room_data.get("Campus"),
            capacidad=self.room_data.get("Capacidad"),
            turno=self.room_data.get("Turno")
        )
        self.agent.set_knowledge_base(self.kb)
        self.agent.set_storage(storage)
        
        await self.agent.start()
        logger.info(f"Room agent started: {self.jid}")
        self.ready_event.set()

class ProfessorThread(AgentThread):
    """Thread for professor agents"""
    def __init__(self, jid: str, password: str, prof_data: dict, orden: int, kb: AgentKnowledgeBase):
        super().__init__(jid, password)
        self.prof_data = prof_data
        self.orden = orden
        self.kb = kb

    async def _setup_agent(self):
        # Create and start professor agent
        storage = await ProfesorScheduleStorage.get_instance()
        self.agent = AgenteProfesor(
            jid=self.jid,
            password=self.password,
            nombre=self.prof_data.get("Nombre"),
            asignaturas=self.prof_data.get("Asignaturas"),
            orden=self.orden
        )
        self.agent.set_knowledge_base(self.kb)
        self.agent.set_storage(storage)
        
        await self.agent.start()
        logger.info(f"Professor agent started: {self.jid}")
        self.ready_event.set()

class SupervisorThread(AgentThread):
    """Thread for supervisor agent"""
    def __init__(self, jid: str, password: str, professor_jids: List[str], kb: AgentKnowledgeBase):
        super().__init__(jid, password)
        self.professor_jids = professor_jids
        self.kb = kb

    async def _setup_agent(self):
        # Create and start supervisor agent
        room_storage = await SalaScheduleStorage.get_instance()
        prof_storage = await ProfesorScheduleStorage.get_instance()
        completion_event = asyncio.Event()
        
        self.agent = AgenteSupervisor(
            jid=self.jid,
            password=self.password,
            professor_jids=self.professor_jids
        )
        self.agent.set_knowledge_base(self.kb)
        self.agent.set_storages(room_storage, prof_storage)
        self.agent.add_finalizer_event(completion_event)
        
        await self.agent.start()
        logger.info("Supervisor agent started")
        self.ready_event.set()

class ThreadManager:
    """Manages all agent threads"""
    def __init__(self, xmpp_server: str, password: str):
        self.xmpp_server = xmpp_server
        self.password = password
        self.threads: Dict[str, AgentThread] = {}
        self.kb = None

    def load_json(self, filename: str) -> List[dict]:
        """Load JSON data from file"""
        try:
            path = Path(__file__).parent / "data" / filename
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
            return []

    async def initialize_kb(self):
        """Initialize shared knowledge base"""
        self.kb = await AgentKnowledgeBase.get_instance()

    def start_agents(self, professor_data: List[dict], room_data: List[dict]):
        """Start all agent threads"""
        try:
            # Start room threads
            for room in room_data:
                jid = f"Sala{room['Codigo']}@{self.xmpp_server}"
                thread = RoomThread(jid, self.password, room, self.kb)
                thread.start()
                self.threads[room['Codigo']] = thread

            # Start professor threads
            professor_jids = []
            for i, prof in enumerate(professor_data):
                jid = f"Profesor{i}@{self.xmpp_server}"
                professor_jids.append(jid)
                thread = ProfessorThread(jid, self.password, prof, i, self.kb)
                thread.start()
                self.threads[f"prof_{i}"] = thread

            # Start supervisor once others are ready
            supervisor_jid = f"Supervisor@{self.xmpp_server}"
            thread = SupervisorThread(
                supervisor_jid, 
                self.password,
                professor_jids,
                self.kb
            )
            thread.start()
            self.threads["supervisor"] = thread

        except Exception as e:
            logger.error(f"Error starting threads: {e}")
            self.cleanup()

    def wait_for_startup(self, timeout: int = 30):
        """Wait for all agents to start"""
        try:
            start_time = threading.time.time()
            for thread in self.threads.values():
                remaining = timeout - (threading.time.time() - start_time)
                if remaining <= 0:
                    raise TimeoutError("Startup timeout exceeded")
                    
                if not thread.ready_event.wait(timeout=remaining):
                    raise TimeoutError(f"Timeout waiting for {thread.jid}")
                    
                if thread.error:
                    raise Exception(f"Error in thread {thread.jid}: {thread.error}")
                    
            logger.info("All agents successfully started")
            
        except Exception as e:
            logger.error(f"Error during startup: {e}")
            self.cleanup()

    def cleanup(self):
        """Clean up all threads"""
        logger.info("Cleaning up threads...")
        for thread in self.threads.values():
            try:
                thread.stop()
                thread.join(timeout=5)
            except Exception as e:
                logger.error(f"Error stopping thread {thread.jid}: {e}")
        logger.info("Cleanup complete")

async def run_manager(manager: ThreadManager, professor_data: List[dict], room_data: List[dict]):
    """Run the thread manager"""
    try:
        # Initialize knowledge base
        await manager.initialize_kb()
        
        # Start all agents
        manager.start_agents(professor_data, room_data)
        
        # Wait for startup
        manager.wait_for_startup()
        
        # Wait for completion
        while any(thread.is_alive() for thread in manager.threads.values()):
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    except Exception as e:
        logger.error(f"Error in manager: {e}")
    finally:
        manager.cleanup()

def main():
    """Main entry point"""
    # Load environment variables
    load_dotenv()
    
    xmpp_server = os.getenv("XMPP_SERVER")
    password = os.getenv("AGENT_PASSWORD")
    
    if not xmpp_server or not password:
        logger.error("XMPP_SERVER and AGENT_PASSWORD must be set in .env file")
        return
        
    try:
        # Initialize thread manager
        manager = ThreadManager(xmpp_server, password)
        
        # Load configuration data
        professor_data = manager.load_json("20profs.json")
        room_data = manager.load_json("inputOfSala.json")
        
        if not professor_data or not room_data:
            logger.error("Failed to load required data files")
            return
            
        # Run manager in asyncio event loop
        asyncio.run(run_manager(manager, professor_data, room_data))
        
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    main()