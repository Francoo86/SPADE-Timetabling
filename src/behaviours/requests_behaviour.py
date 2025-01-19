from spade.behaviour import CyclicBehaviour, OneShotBehaviour
from spade.template import Template
from spade.message import Message
import asyncio
# from .negotiation_behaviour import NegotiationStateBehaviour
# from .message_collector import MessageCollectorBehaviour
# from agents.profesor_redux import AgenteProfesor

class EsperarTurnoBehaviour(CyclicBehaviour):
    """Behaviour that waits for the agent's turn before starting negotiations."""
    
    def __init__(self, profesor_agent,
                 state_behaviour,
                 message_collector):
        """Initialize the wait turn behaviour.
        
        Args:
            profesor_agent: The professor agent instance
            state_behaviour: The negotiation state behaviour to add when it's our turn
            message_collector: The message collector behaviour to add when it's our turn
        """
        super().__init__()
        
        self.profesor = profesor_agent
        self.state_behaviour = state_behaviour
        self.message_collector = message_collector
        

    async def run(self):
        """Main behaviour loop - checks for START messages."""
        # Create message template for INFORM messages with START content
        msg = await self.receive(timeout=10)  # Pass the template
        
        if msg:
            try:
                # Get the next order from user-defined parameters
                next_orden = int(msg.get_metadata("nextOrden"))
                
                # Check if it's our turn
                if next_orden == self.profesor.orden:
                    self.profesor.log.info(
                        f"Professor {self.profesor.nombre} received START signal. "
                        f"My order={self.profesor.orden}, requested order={next_orden}"
                    )
                    
                    # Add negotiation behaviors when it's our turn
                    self.agent.add_behaviour(self.state_behaviour)
                    self.agent.add_behaviour(self.message_collector)
                    
                    # Remove this waiting behavior
                    await self.agent.remove_behaviour(self)
                    # self.kill()
                    
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
        """
        Initialize the notification behaviour
        
        Args:
            profesor: The professor agent instance
            next_orden: Order number of the next professor
        """
        super().__init__()
        self.profesor = profesor
        self.next_orden = next_orden
        
    async def run(self):
        """Execute the notification"""
        try:
            # Get the next professor's JID
            next_professor_jid = self.profesor.get(f"professor_{self.next_orden}")
            
            if next_professor_jid:
                # Create START message
                msg = Message(
                    to=next_professor_jid,
                    metadata={
                        "performative": "inform",
                        "ontology": "professor-chain",
                        "nextOrden": str(self.next_orden)
                    },
                    body="START"
                )
                
                await self.send(msg)
                self.profesor.log.info(
                    f"Successfully notified next professor {next_professor_jid} "
                    f"with order: {self.next_orden}"
                )
            else:
                self.profesor.log.info(
                    f"No next professor found with order {self.next_orden}"
                )
                
        except Exception as e:
            self.profesor.log.error(f"Error notifying next professor: {str(e)}")
            
    async def on_end(self):
        """Cleanup after notification is sent"""
        await super().on_end()