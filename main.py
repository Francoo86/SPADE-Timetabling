import asyncio
import spade
from spade.agent import Agent
from typing import Dict, List
import json
import os
from datetime import datetime
from src.agents.profesor import ProfesorAgent
from src.agents.sala import RoomAgent
from src.agents.supervisor import SupervisorAgent

class SPADEApplication:
    def __init__(self, xmpp_server: str, password: str):
        self.xmpp_server = xmpp_server
        self.password = password
        self.room_agents = {}
        self.professor_agents = []
        self.supervisor_agent = None
        self.running = True

    async def start_platform(self):
        try:
            # Load configuration data
            professors_data = self.load_json("profesores.json")
            rooms_data = self.load_json("salas.json")

            # Calculate total subjects for room request configuration
            total_subjects = sum(
                len(prof.get("Asignaturas", [])) 
                for prof in professors_data
            )

            # Initialize room agents first
            print("Creating room agents...")
            await self.initialize_rooms(rooms_data)
            await asyncio.sleep(2)  # Give rooms time to initialize

            # Initialize professor agents
            print("Creating professor agents...")
            room_jids = [
                f"room_{room['Codigo']}@{self.xmpp_server}"
                for room in rooms_data
            ]
            await self.initialize_professors(professors_data, room_jids)
            await asyncio.sleep(2)  # Give professors time to initialize

            # Start supervisor last
            await self.start_supervisor()

            print("Platform initialization complete.")
            
            # Wait until supervisor finishes
            while self.supervisor_agent.get("system_active", True):
                try:
                    await asyncio.sleep(1)
                except KeyboardInterrupt:
                    break

        except Exception as e:
            print(f"Error in platform: {e}")
        finally:
            await self.cleanup()

    @staticmethod
    def load_json(filename: str) -> list:
        """Load and parse a JSON file"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            return []

    async def initialize_rooms(self, rooms_data: List[dict]):        
        """Initialize and start room agents"""
        for room_data in rooms_data:
            try:
                code = room_data["Codigo"]
                room_jid = f"room_{code}@{self.xmpp_server}"
                
                room = RoomAgent(
                    jid=room_jid,
                    password=self.password,
                    json_data=room_data,
                    schedule_handler=None  # Optional: Add schedule handler if needed
                )
                await room.start(auto_register=True)
                self.room_agents[code] = room
                print(f"Room agent {code} started at {room_jid}")
            except Exception as e:
                print(f"Error creating room agent {code}: {e}")

    async def initialize_professors(self, professors_data: List[dict], room_jids: List[str]):
        """Initialize and start professor agents"""
        for i, prof_data in enumerate(professors_data):
            try:
                prof_jid = f"professor_{i}@{self.xmpp_server}"
                
                professor = ProfesorAgent(
                    jid=prof_jid,
                    password=self.password,
                    json_data=prof_data,
                    order=i,
                    room_jids=room_jids
                )

                # Store next professor's JID in knowledge base for chain communication
                if i < len(professors_data) - 1:
                    next_jid = f"professor_{i+1}@{self.xmpp_server}"
                    professor.set(f"professor_{i+1}", next_jid)

                await professor.start(auto_register=True)
                self.professor_agents.append(professor)
                print(f"Professor agent {prof_data['Nombre']} started at {prof_jid}")
            except Exception as e:
                print(f"Error creating professor agent {prof_data['Nombre']}: {e}")

    async def start_supervisor(self):        
        """Initialize and start the supervisor agent"""
        try:
            professor_jids = [agent.jid for agent in self.professor_agents]
            supervisor_jid = f"supervisor@{self.xmpp_server}"
            
            self.supervisor_agent = SupervisorAgent(
                supervisor_jid,
                self.password,
                professor_jids
            )
            await self.supervisor_agent.start(auto_register=True)
            print(f"Supervisor agent started at {supervisor_jid}")
        except Exception as e:
            print(f"Error creating supervisor agent: {e}")

    async def cleanup(self):
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
    """Main entry point for the SPADE application"""
    # Load environment variables
    import dotenv
    dotenv.load_dotenv()

    xmpp_server = os.getenv("XMPP_SERVER")
    password = os.getenv("AGENT_PASSWORD")

    if not xmpp_server or not password:
        print("Error: XMPP_SERVER and AGENT_PASSWORD must be set in .env file")
        return

    app = SPADEApplication(xmpp_server, password)
    spade.run(app.start_platform())

if __name__ == "__main__":
    main()