from spade.behaviour import CyclicBehaviour
from spade.template import Template
from spade.message import Message
from fipa.common_templates import CommonTemplates

class StatusResponseBehaviour(CyclicBehaviour):
    """Handles status queries from supervisor"""
    
    async def run(self):
        """
        template = Template()
        template.set_metadata("performative", "query-ref")
        template.set_metadata("ontology", "agent-status")"""
        
        msg = await self.receive(timeout=10)
        if not msg:
            return

        try:
            # Create status response
            reply = Message(to=str(msg.sender))
            reply.set_metadata("performative", "inform")
            reply.set_metadata("ontology", "agent-status")
            
            # Determine current state
            if self.agent.get_current_subject() is None:
                state = "TERMINATED"
            else:
                state = "ACTIVE"
                
            reply.body = state
            await self.send(reply)
            
        except Exception as e:
            self.agent.log.error(f"Error sending status: {str(e)}")
            
class InitialWaitBehaviour(CyclicBehaviour):
    """Special wait behaviour for first professor"""
    def __init__(self, state_behaviour, message_collector):
        super().__init__()
        self.state_behaviour = state_behaviour
        self.message_collector = message_collector
        
    async def run(self):
        msg = await self.receive(timeout=10)
        if msg:
            self.agent.prepare_behaviours()
            self.kill()