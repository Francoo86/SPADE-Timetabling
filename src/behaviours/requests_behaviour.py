from spade.behaviour import CyclicBehaviour
from spade.template import Template
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
        template = Template()
        template.performative = "inform"
        template.body = "START"
        
        # Wait for a message matching our template
        msg = await self.receive(timeout=10)  # 10 second timeout
        
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