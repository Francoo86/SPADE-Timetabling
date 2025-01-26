from spade.behaviour import FSMBehaviour, State

from spade.behaviour import FSMBehaviour, State
from spade.message import Message
from spade.template import Template
import asyncio
from typing import Optional, Dict, List

# States for the FSM
class NegotiationStates:
    SETUP = "SETUP"
    COLLECTING = "COLLECTING"
    EVALUATING = "EVALUATING"
    FINISHED = "FINISHED"

class ProfessorNegotiationFSM(FSMBehaviour):
    """FSM for handling professor negotiations"""
    
    def __init__(self, profesor_agent):
        super().__init__()
        self.profesor = profesor_agent
        self.proposals = asyncio.Queue()
        self.timeout = 5  # seconds
        self.pending_blocks = 0
        
        # Add states
        self.add_state(NegotiationStates.SETUP, SetupState())
        self.add_state(NegotiationStates.COLLECTING, CollectingState())
        self.add_state(NegotiationStates.EVALUATING, EvaluatingState())
        self.add_state(NegotiationStates.FINISHED, FinishedState())
        
        # Define transitions
        self.add_transition(NegotiationStates.SETUP, NegotiationStates.COLLECTING)
        self.add_transition(NegotiationStates.COLLECTING, NegotiationStates.EVALUATING)
        self.add_transition(NegotiationStates.EVALUATING, NegotiationStates.SETUP)
        self.add_transition(NegotiationStates.EVALUATING, NegotiationStates.FINISHED)
        self.add_transition(NegotiationStates.SETUP, NegotiationStates.FINISHED)

class SetupState(State):
    async def run(self):
        if not self.agent.can_use_more_subjects():
            self.set_next_state(NegotiationStates.FINISHED)
            return
            
        current_subject = self.agent.get_current_subject()
        if current_subject:
            self.parent.pending_blocks = current_subject.get_horas()
            await self.send_cfp_messages()
            self.set_next_state(NegotiationStates.COLLECTING)
        else:
            self.set_next_state(NegotiationStates.FINISHED)

class CollectingState(State):
    async def run(self):
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < self.parent.timeout:
            msg = await self.receive(timeout=0.1)
            if msg:
                if msg.get_metadata("performative") == "propose":
                    await self.handle_proposal(msg)
                    
            if not self.parent.proposals.empty():
                self.set_next_state(NegotiationStates.EVALUATING)
                return
                
            await asyncio.sleep(0.1)
            
        # Timeout reached
        if not self.parent.proposals.empty():
            self.set_next_state(NegotiationStates.EVALUATING)
        else:
            self.set_next_state(NegotiationStates.SETUP)

class EvaluatingState(State):
    async def run(self):
        proposals = []
        while not self.parent.proposals.empty():
            proposals.append(await self.parent.proposals.get())
            
        valid_proposals = await self.filter_and_sort_proposals(proposals)
        
        if valid_proposals and await self.try_assign_proposals(valid_proposals):
            if self.parent.pending_blocks == 0:
                await self.agent.move_to_next_subject()
                self.set_next_state(NegotiationStates.SETUP)
            else:
                self.set_next_state(NegotiationStates.COLLECTING)
        else:
            self.set_next_state(NegotiationStates.SETUP)

class FinishedState(State):
    async def run(self):
        await self.agent.finish_negotiations()
        self.kill()