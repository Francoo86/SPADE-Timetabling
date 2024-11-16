import json
import asyncio
from typing import Dict, List
import sys
from datetime import datetime
import os
import dotenv
dotenv.load_dotenv()

XMPP_SERVER = os.getenv("XMPP_SERVER")
PASSWORD = os.getenv("GENERIC_PASSWORD")

from src.agents.sala import RoomAgent, RoomScheduleHandler
from src.agents.profesor import ProfesorAgent
from src.agents.supervisor import SupervisorAgent

class SPADEApplication:
    def __init__(self, xmpp_server: str):
        self.xmpp_server = xmpp_server
        self.room_controllers: Dict[str, RoomAgent] = {}
        self.professor_controllers: List[ProfesorAgent] = []
        self.schedule_handler = RoomScheduleHandler()
        self.running = True
        
    async def start_platform(self):
        try:
            # Load data from JSON files
            professors_data = self.load_json("profesores.json")
            rooms_data = self.load_json("salas.json")

            print("Creating room agents...")
            await self.initialize_rooms(rooms_data)
            await asyncio.sleep(2)  # Give time for rooms to initialize

            total_subjects = self.calculate_total_subjects(professors_data)
            print(f"Total subjects to assign: {total_subjects}")

            print("Creating professor agents...")
            await self.initialize_professors(professors_data)
            await asyncio.sleep(2)  # Give time for professors to initialize

            # Start supervisor
            await self.create_supervisor_agent()

            # Keep the application running
            while self.running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("\nStopping all agents...")
            await self.cleanup()
        except Exception as e:
            print(f"Error in platform: {e}")
            await self.cleanup()
            raise e

    @staticmethod
    def load_json(filename: str) -> List[dict]:
        """Load and parse a JSON file"""
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                return json.load(file)
        except Exception as e:
            print(f"Error loading {filename}: {e}")
            sys.exit(1)

    async def initialize_rooms(self, rooms_data: List[dict]):
        """Initialize all room agents"""
        for room_data in rooms_data:
            try:
                code = room_data["Codigo"]
                jid = f"room_{code}@{self.xmpp_server}"
                password = PASSWORD

                room_agent = RoomAgent(
                    jid=jid,
                    password=password,
                    json_data=room_data,
                    schedule_handler=self.schedule_handler
                )
                await room_agent.start()
                self.room_controllers[code] = room_agent
                
                print(f"Room agent {code} created and started with data: {room_data}")
                
            except Exception as e:
                print(f"Error creating room agent {room_data.get('Codigo', 'unknown')}: {e}")

    @staticmethod
    def calculate_total_subjects(professors_data: List[dict]) -> int:
        """Calculate total number of subjects to be assigned"""
        return sum(len(prof["Asignaturas"]) for prof in professors_data)

    async def initialize_professors(self, professors_data: List[dict]):
        """Initialize all professor agents"""
        for i, prof_data in enumerate(professors_data):
            try:
                name = prof_data["Nombre"]
                jid = f"professor_{i}@{self.xmpp_server}"
                password = PASSWORD

                professor_agent = ProfesorAgent(
                    jid=jid,
                    password=password,
                    json_data=prof_data,
                    order=i
                )
                await professor_agent.start()
                self.professor_controllers.append(professor_agent)
                
                print(f"Professor agent created: order={i}, name={name}")
                
            except Exception as e:
                print(f"Error creating professor agent {prof_data.get('Nombre', 'unknown')}: {e}")

    async def create_supervisor_agent(self):
        """Create and start the supervisor agent"""
        try:
            professor_jids = [agent.jid for agent in self.professor_controllers]
            
            supervisor = SupervisorAgent(
                jid=f"supervisor@{self.xmpp_server}",
                password=PASSWORD,
                professor_jids=professor_jids
            )
            await supervisor.start()
            print("Supervisor agent created and started")
            
        except Exception as e:
            print(f"Error creating supervisor agent: {e}")

    async def cleanup(self):
        """Clean up and stop all agents"""
        print("Cleaning up...")
        self.running = False
        
        # Stop all room agents
        for room_agent in self.room_controllers.values():
            try:
                await room_agent.stop()
            except Exception as e:
                print(f"Error stopping room agent: {e}")

        # Stop all professor agents
        for prof_agent in self.professor_controllers:
            try:
                await prof_agent.stop()
            except Exception as e:
                print(f"Error stopping professor agent: {e}")

        # Wait a moment for cleanup
        await asyncio.sleep(2)

if __name__ == "__main__":
    # Example JSON structure for testing
    example_prof_json = """
    [
        {
            "Nombre": "John Doe",
            "RUT": "12345678-9",
            "Asignaturas": [
                {
                    "Nombre": "Mathematics",
                    "Horas": 4,
                    "Vacantes": 30
                },
                {
                    "Nombre": "Physics",
                    "Horas": 4,
                    "Vacantes": 25
                }
            ]
        }
    ]
    """

    example_room_json = """
    [
        {
            "Codigo": "A101",
            "Capacidad": 30
        }
    ]
    """

    # For testing purposes, create the JSON files if they don't exist
    if not all(map(lambda x: os.path.exists(x), ["profesores.json", "salas.json"])):
        with open("profesores.json", "w", encoding="utf-8") as f:
            f.write(example_prof_json)
        with open("salas.json", "w", encoding="utf-8") as f:
            f.write(example_room_json)

    # Create and run the application
    xmpp_server = XMPP_SERVER
    app = SPADEApplication(xmpp_server)
    
    # Run the application
    asyncio.run(app.start_platform())