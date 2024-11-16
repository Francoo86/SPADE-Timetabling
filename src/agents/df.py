from spade.agent import Agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message
from spade.template import Template
from typing import Dict, List

class DFMixin:
    async def register_in_df(self):
        """Register the agent's service in Directory Facilitator"""
        try:
            # Create service description
            dfd = {"name": str(self.jid)}
            sd = {
                "name": self.jid.localpart,
                "type": self._service_type,  # Define this in implementing classes
                "properties": self._service_properties  # Define this in implementing classes
            }
            dfd["services"] = [sd]

            # Register with DF using presence
            await self.presence.register_service(
                str(self.jid),
                sd
            )
            print(f"Agent {self.jid} registered in DF")
            return True
        except Exception as e:
            print(f"Error registering in DF: {e}")
            return False

    async def search_in_df(self, service_type: str) -> List[str]:
        """Search for agents providing a specific service"""
        try:
            # Search services through presence
            services = await self.presence.search_services(service_type)
            return [service["jid"] for service in services]
        except Exception as e:
            print(f"Error searching DF: {e}")
            return []

    async def deregister_from_df(self):
        """Remove service registration from DF"""
        try:
            await self.presence.deregister_service()
            print(f"Agent {self.jid} deregistered from DF")
        except Exception as e:
            print(f"Error deregistering from DF: {e}")