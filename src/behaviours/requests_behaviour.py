from spade.behaviour import CyclicBehaviour
import asyncio

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
                
        #else:
            #await asyncio.sleep(0.1)

    async def on_end(self):
        """Cleanup when behaviour ends."""
        self.profesor.log.info(f"Wait turn behaviour ended for professor {self.profesor.nombre}")