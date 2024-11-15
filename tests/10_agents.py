import asyncio
import spade
from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour, OneShotBehaviour
from spade.message import Message
from spade.template import Template
import random
import logging
import datetime
from typing import List, Dict
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class CommunicativeAgent(Agent):
    def __init__(self, jid: str, password: str, agent_info: Dict):
        super().__init__(jid, password)
        self.agent_info = agent_info
        self.received_messages = 0
        self.sent_messages = 0
        self.known_agents = set()

    class InformBehaviour(PeriodicBehaviour):
        async def run(self):
            if not self.agent.known_agents:
                return

            # Choose a random agent to send message to
            receiver = random.choice(list(self.agent.known_agents))
            
            # Generate some dynamic content based on agent's role
            if self.agent.agent_info["role"] == "sensor":
                data = random.uniform(20.0, 30.0)  # Simulate sensor reading
                content = f"Temperature reading: {data:.2f}°C"
            elif self.agent.agent_info["role"] == "processor":
                data = random.choice(["process_a", "process_b", "process_c"])
                content = f"Running process: {data}"
            else:  # coordinator
                data = random.choice(["high", "medium", "low"])
                content = f"System load: {data}"

            msg = Message(
                to=receiver,
                body=content,
                metadata={
                    "timestamp": datetime.datetime.now().isoformat(),
                    "sender_role": self.agent.agent_info["role"]
                }
            )

            await self.send(msg)
            self.agent.sent_messages += 1
            logging.info(f"{self.agent.name} sent message to {receiver}: {content}")

    class ReceiveBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                self.agent.received_messages += 1
                logging.info(f"{self.agent.name} received message from {msg.sender}: {msg.body}")
                
                # Process message based on agent's role
                if self.agent.agent_info["role"] == "processor":
                    # Process the data and send result
                    if "Temperature reading" in msg.body:
                        temp = float(msg.body.split(":")[1].replace("°C", ""))
                        if temp > 25:
                            alert_msg = Message(
                                to=str(msg.sender),
                                body=f"Alert: High temperature detected: {temp}°C"
                            )
                            await self.send(alert_msg)
                
                elif self.agent.agent_info["role"] == "coordinator":
                    # Coordinator monitors all communication
                    if "Alert" in msg.body:
                        # Broadcast to all known agents
                        for agent_jid in self.agent.known_agents:
                            broadcast = Message(
                                to=agent_jid,
                                body=f"Broadcast: {msg.body}"
                            )
                            await self.send(broadcast)
            else:
                await asyncio.sleep(1)

    async def setup(self):
        logging.info(f"Agent {self.name} starting... Role: {self.agent_info['role']}")
        
        # Add behaviors
        inform_behavior = self.InformBehaviour(period=random.uniform(5, 10))
        receive_behavior = self.ReceiveBehaviour()
        
        self.add_behaviour(inform_behavior)
        self.add_behaviour(receive_behavior)

class AgentNetwork:
    def __init__(self, domain: str = "localhost", num_agents: int = 10):
        self.domain = domain
        self.num_agents = num_agents
        self.agents: List[CommunicativeAgent] = []
        
        # Define different roles for agents
        self.roles = {
            "sensor": {"count": 4, "description": "Monitors environment"},
            "processor": {"count": 4, "description": "Processes data"},
            "coordinator": {"count": 2, "description": "Coordinates responses"}
        }

    def create_agent_info(self, index: int) -> Dict:
        """Assign roles to agents based on index"""
        if index < self.roles["sensor"]["count"]:
            role = "sensor"
        elif index < self.roles["sensor"]["count"] + self.roles["processor"]["count"]:
            role = "processor"
        else:
            role = "coordinator"
            
        return {
            "role": role,
            "id": index,
            "description": self.roles[role]["description"]
        }

    async def setup_network(self):
        """Create and start all agents"""
        logging.info("Setting up agent network...")
        
        for i in range(self.num_agents):
            jid = f"agent{i}@{self.domain}"
            password = f"pass_{i}"
            agent_info = self.create_agent_info(i)
            
            agent = CommunicativeAgent(jid, password, agent_info)
            await agent.start()
            self.agents.append(agent)
            
            # Add this agent to all other agents' known_agents list
            for other_agent in self.agents[:-1]:
                other_agent.known_agents.add(jid)
                agent.known_agents.add(str(other_agent.jid))
                
            logging.info(f"Started agent {jid} with role {agent_info['role']}")
            
        logging.info(f"Successfully started {len(self.agents)} agents")

    async def stop_network(self):
        """Stop all agents"""
        logging.info("Stopping agent network...")
        for agent in self.agents:
            await agent.stop()
        logging.info("All agents stopped")

    def print_statistics(self):
        """Print network statistics"""
        print("\n=== Network Statistics ===")
        for agent in self.agents:
            print(f"\nAgent: {agent.name}")
            print(f"Role: {agent.agent_info['role']}")
            print(f"Messages sent: {agent.sent_messages}")
            print(f"Messages received: {agent.received_messages}")
            print(f"Known agents: {len(agent.known_agents)}")

async def main():
    try:
        # Create and setup agent network
        network = AgentNetwork(domain="localhost", num_agents=10)
        await network.setup_network()
        
        print("\nAgent network is running. Press Ctrl+C to stop...")
        
        # Keep the network running and print statistics every 30 seconds
        while True:
            await asyncio.sleep(30)
            network.print_statistics()
            
    except KeyboardInterrupt:
        print("\nShutting down agent network...")
        await network.stop_network()
        
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        await network.stop_network()

if __name__ == "__main__":
    asyncio.run(main())