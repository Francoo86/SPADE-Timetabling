from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.template import Template
from spade.message import Message
import asyncio
# from .negotiation_behaviour import NegotiationStateBehaviour
# from .message_collector import MessageCollectorBehaviour
# from agents.profesor_redux import AgenteProfesor
from spade.agent import Agent
from objects.knowledge_base import AgentKnowledgeBase
from fipa.acl_message import FIPAPerformatives

class EsperarTurnoBehaviour(CyclicBehaviour):
    """Behaviour that waits for the agent's turn before starting negotiations."""
    
    def __init__(self, profesor_agent):
        super().__init__()
        self.profesor = profesor_agent

    async def run(self):
        """Main behaviour loop - checks for START messages."""
        msg = await self.receive(timeout=10)
        
        if msg:
            try:
                content = msg.body
                # Check if this is a START message
                if content == "START":
                    # Get the next order from metadata
                    next_orden_str = msg.get_metadata("nextOrden")
                    if next_orden_str is None:
                        self.profesor.log.warning("Received START message without nextOrden metadata")
                        return
                        
                    next_orden = int(next_orden_str)
                    
                    # Check if it's our turn
                    if next_orden == self.profesor.orden:
                        self.profesor.log.info(
                            f"Professor {self.profesor.nombre} received START signal. "
                            f"My order={self.profesor.orden}, requested order={next_orden}"
                        )
                        
                        # Add negotiation behaviors when it's our turn
                        self.agent.prepare_behaviours()
                        
                        # Remove this waiting behavior
                        # WORKAROUND: For some reason remove_behaviour doesn't work
                        # kill it anyways because we don't need it anymore
                        self.kill()
                        
            except (KeyError, ValueError) as e:
                self.profesor.log.error(f"Error processing START message: {str(e)}")
                
        else:
            # No message received, wait a bit
            await asyncio.sleep(0.1)

    async def on_end(self):
        """Cleanup when behaviour ends."""
        self.profesor.log.info(f"Wait turn behaviour ended for professor {self.profesor.nombre}")

class NotifyNextProfessorBehaviour(OneShotBehaviour):
    """One-shot behaviour to notify the next professor to start negotiations"""
    
    def __init__(self, profesor, next_orden):
        super().__init__()
        self.profesor = profesor
        self.next_orden = next_orden
        
    async def run(self):
        """Execute the notification"""
        try:
            # Get the knowledge base
            
            # Search for professor with next order
            professors = await self.agent._kb.search(
                service_type="profesor",
                properties={"orden": self.next_orden}
            )
            
            if professors:
                next_professor = professors[0]
                # Create START message
                msg = Message(
                    to=str(next_professor.jid)
                )
                msg.set_metadata("performative", FIPAPerformatives.INFORM)
                msg.set_metadata("conversation-id", "negotiation-start")
                msg.set_metadata("nextOrden", str(self.next_orden))

                msg.body = "START"
                
                await self.send(msg)
                self.profesor.log.info(
                    f"Successfully notified next professor {next_professor.jid} "
                    f"with order: {self.next_orden}"
                )
            else:
                self.profesor.log.warning(
                    f"No professor found with order {self.next_orden}"
                )
                
        except Exception as e:
            self.profesor.log.error(f"Error notifying next professor: {str(e)}")
            
    async def on_end(self):
        """Cleanup after notification is sent"""
        await super().on_end()