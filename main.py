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

# Configure logging
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ApplicationAgent(Agent):
    """
    Main application controller agent that manages the lifecycle of other agents
    """
    def __init__(self, jid: str, password: str, room_data: List[dict], 
                 professor_data: List[dict]):
        super().__init__(jid, password)
        self.room_data = room_data
        self.professor_data = professor_data
        self.room_agents: Dict[str, Agent] = {}
        self.professor_agents: List[Agent] = []
        self.supervisor_agent: Optional[Agent] = None
        self.is_running = True
        
    async def setup(self):
        """Initialize agent behaviors and start agent creation sequence"""
        logger.info("Application agent starting...")
        
        # Add startup coordinator behavior
        startup_template = Template()
        startup_template.set_metadata("conversation-id", "startup-sequence")
        self.add_behaviour(self.StartupCoordinatorBehaviour(), startup_template)
        
        # Add monitoring behavior
        monitor_template = Template()
        monitor_template.set_metadata("conversation-id", "system-monitor")
        self.add_behaviour(self.SystemMonitorBehaviour(period=5), monitor_template)

    class StartupCoordinatorBehaviour(CyclicBehaviour):
        """Coordinates the startup sequence of all agents"""
        
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
            """Execute startup stages sequentially"""
            if self.current_stage < len(self.stages):
                try:
                    await self.stages[self.current_stage]()
                    self.current_stage += 1
                except Exception as e:
                    logger.error(f"Error in startup stage {self.current_stage}: {e}")
                    await self.cleanup()
                    
            await asyncio.sleep(0.1)
            
        async def initialize_rooms(self):
            """Initialize and start room agents"""
            logger.info("Initializing room agents...")
            
            for room_data in self.agent.room_data:
                try:
                    room_jid = f"Sala{room_data['Codigo']}@{self.agent.jid.domain}"  # Changed from room_ to Sala
                    room = AgenteSala(  # Changed from RoomAgent to AgenteSala
                        jid=room_jid,
                        password=self.agent.password,
                        codigo=room_data.get("Codigo"),
                        campus=room_data.get("Campus"),
                        capacidad=room_data.get("Capacidad"),
                        turno=room_data.get("Turno")
                    )
                    await room.start(auto_register=True)
                    self.agent.room_agents[room_data['Codigo']] = room
                    logger.info(f"Room agent started: {room_jid}")
                    
                except Exception as e:
                    logger.error(f"Failed to start room agent: {e}")
                    
            await asyncio.sleep(2)  # Allow rooms to initialize
            
        async def initialize_professors(self):
            """Initialize and start professor agents"""
            logger.info("Initializing professor agents...")
            
            for i, prof_data in enumerate(self.agent.professor_data):
                try:
                    prof_jid = f"Profesor{i}@{self.agent.jid.domain}"  # Changed from professor_ to Profesor
                    professor = AgenteProfesor(  # Changed from ProfessorAgent to AgenteProfesor
                        jid=prof_jid,
                        password=self.agent.password,
                        nombre=prof_data.get("Nombre"),  # Need to pass actual professor attributes
                        asignaturas=prof_data.get("Asignaturas"),
                        orden=i
                    )
                    await professor.start(auto_register=True)
                    self.agent.professor_agents.append(professor)
                    logger.info(f"Professor agent started: {prof_jid}")
                    
                except Exception as e:
                    logger.error(f"Failed to start professor agent: {e}")
                    
            await asyncio.sleep(2)  # Allow professors to initialize
            
        async def initialize_supervisor(self):
            """Initialize and start supervisor agent"""
            logger.info("Initializing supervisor agent...")
            
            try:
                supervisor_jid = f"Supervisor@{self.agent.jid.domain}"  # Match the original JADE name
                supervisor = AgenteSupervisor(  # Changed to match original name
                    jid=supervisor_jid,
                    password=self.agent.password,
                    profesores_controllers=self.agent.professor_agents  # Match original constructor
                )
                await supervisor.start(auto_register=True)
                logger.info(f"Supervisor agent started: {supervisor_jid}")
                
            except Exception as e:
                logger.error(f"Failed to start supervisor agent: {e}")
                
            await asyncio.sleep(2)  # Allow supervisor to initialize
            
        async def start_negotiations(self):
            """Trigger the start of negotiations"""
            logger.info("Starting negotiation process...")
            
            try:
                # Send start signal to first professor
                if self.agent.professor_agents:
                    msg = Message(to=str(self.agent.professor_agents[0].jid))
                    msg.set_metadata("performative", "inform")
                    msg.body = "START"
                    msg.set_metadata("conversation-id", "negotiation-start")
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
                    system_active = await self.agent.supervisor_agent.get_state("system_active")
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
            
            logger.info("System shutdown complete")

class ApplicationRunner:
    """Manages the SPADE application lifecycle"""
    
    def __init__(self, xmpp_server: str, password: str):
        self.xmpp_server = xmpp_server
        self.password = password
        
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
            professors_data = self.load_json("profesores.json")
            rooms_data = self.load_json("salas.json")
            
            if not professors_data or not rooms_data:
                logger.error("Failed to load required data files")
                return
                
            # Create and start application agent
            app_jid = f"application@{self.xmpp_server}"
            app_agent = ApplicationAgent(
                app_jid,
                self.password,
                rooms_data,
                professors_data
            )
            
            await app_agent.start(auto_register=True)
            logger.info("Application agent started successfully")
            
            # Wait for completion
            while app_agent.is_running:
                try:
                    await asyncio.sleep(1)
                except KeyboardInterrupt:
                    logger.info("Received shutdown signal")
                    break
                    
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
        if self.supervisor_agent:
            cleanup_tasks.append(self.supervisor_agent.stop())
            
        for agent in reversed(self.professor_agents):
            cleanup_tasks.append(agent.stop())
            
        for agent in reversed(list(self.room_agents.values())):
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
    runner = ApplicationRunner(xmpp_server, password)
    asyncio.run(runner.run())

if __name__ == "__main__":
    main()