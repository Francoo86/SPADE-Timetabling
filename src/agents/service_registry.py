from typing import Dict, Set
from spade.agent import Agent
from spade.message import Message
from spade.behaviour import CyclicBehaviour
from spade.template import Template

class ServiceRegistry:
    def __init__(self):
        self.services: Dict[str, Set[str]] = {}  # service_type -> set of JIDs

    def register(self, service_type: str, jid: str):
        if service_type not in self.services:
            self.services[service_type] = set()
        self.services[service_type].add(jid)

    def unregister(self, service_type: str, jid: str):
        if service_type in self.services:
            self.services[service_type].discard(jid)
            if not self.services[service_type]:
                del self.services[service_type]

    def get_services(self, service_type: str) -> Set[str]:
        return self.services.get(service_type, set())

class RegistryAgent(Agent):
    def __init__(self, jid: str, password: str):
        super().__init__(jid, password)
        self.registry = ServiceRegistry()
        
    async def setup(self):
        template_register = Template()
        template_register.set_metadata("performative", "register")
        self.add_behaviour(self.RegisterBehaviour(), template_register)

        template_search = Template()
        template_search.set_metadata("performative", "search")
        self.add_behaviour(self.SearchBehaviour(), template_search)

    class RegisterBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            service_type = msg.get_metadata("service-type")
            if service_type:
                self.agent.registry.register(service_type, str(msg.sender))
                
                # Send confirmation
                reply = Message(to=str(msg.sender))
                reply.set_metadata("performative", "confirm-registration")
                await self.send(reply)

    class SearchBehaviour(CyclicBehaviour):
        async def run(self):
            msg = await self.receive(timeout=0.5)
            if not msg:
                return

            service_type = msg.get_metadata("service-type")
            if service_type:
                services = self.agent.registry.get_services(service_type)
                
                # Send results
                reply = Message(to=str(msg.sender))
                reply.set_metadata("performative", "search-result")
                reply.body = ",".join(services)
                await self.send(reply)