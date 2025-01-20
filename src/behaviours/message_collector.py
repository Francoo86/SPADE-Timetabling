from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
import json
import asyncio
# from agents.profesor_redux import AgenteProfesor
from dataclasses import dataclass

from objects.helper.batch_proposals import BatchProposal
from objects.helper.classroom_availability import ClassroomAvailability
from .negotiation_behaviour import NegotiationStateBehaviour

class MessageCollectorBehaviour(CyclicBehaviour):
    def __init__(self, professor_agent, batch_proposals: asyncio.Queue, state_behaviour : NegotiationStateBehaviour):
        """
        Initialize the message collector behaviour.
        
        Args:
            professor_agent: The SPADE agent instance
            batch_proposals: Queue to store received proposals
            state_behaviour: Associated negotiation state behaviour
        """
        super().__init__()
        self.professor = professor_agent
        self.batch_proposals = batch_proposals
        self.state_behaviour = state_behaviour

    async def run(self):
        """Main behaviour loop"""
        try:
            # Create message template for PROPOSE and REFUSE
            """
            template = Template()
            template.set_metadata("performative", "propose")
            template.set_metadata("ontology", "classroom-availability") """
            
            # Wait for a message
            msg = await self.receive(timeout=10)
            
            if msg and msg.get_metadata("ontology") == "classroom-availability":
                if msg.get_metadata("performative") == "propose":
                    await self.handle_proposal(msg)
                # We can ignore REFUSE messages as they don't require processing
                
            else:
                # No message received, wait a bit before next check
                await asyncio.sleep(0.05)

        except Exception as e:
            self.professor.log.error(f"Error in MessageCollector: {str(e)}")

    async def handle_proposal(self, msg: Message):
        """
        Handle received proposal messages.
        
        Args:
            msg: The received SPADE message
        """
        try:
            # Parse the content (assumed to be JSON)
            content = json.loads(msg.body)
            
            # Create ClassroomAvailability object
            availability = ClassroomAvailability(
                codigo=content['codigo'],
                campus=content['campus'],
                capacidad=content['capacidad'],
                available_blocks=content['available_blocks']
            )

            if availability:
                # Create batch proposal
                batch_proposal = BatchProposal.from_availability(availability, msg)
                
                # Add to queue
                await self.batch_proposals.put(batch_proposal)
                
                # Notify state behaviour
                await self.state_behaviour.notify_proposal_received()
                
            else:
                self.professor.log.warning("Received null classroom availability")

        except Exception as e:
            self.professor.log.error(f"Error processing proposal: {str(e)}")

    async def on_end(self):
        """Cleanup when behaviour ends"""
        self.professor.log.info("MessageCollector behaviour finished")
        