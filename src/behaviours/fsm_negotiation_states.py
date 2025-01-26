from spade.behaviour import FSMBehaviour, State

from spade.behaviour import FSMBehaviour, State
from spade.message import Message
from spade.template import Template
import asyncio
import jsonpickle
import datetime
from typing import List
from objects.helper.batch_proposals import BatchProposal
from objects.helper.batch_requests import AssignmentRequest
from collections import defaultdict

# States for the FSM
class NegotiationStates:
    SETUP = "SETUP"
    COLLECTING = "COLLECTING"
    EVALUATING = "EVALUATING"
    FINISHED = "FINISHED"

class NegotiationFSM(FSMBehaviour):
    """FSM for handling professor negotiations"""
    
    def __init__(self, profesor_agent):
        super().__init__()
        self.profesor = profesor_agent
        # Rather than saving it here we could save it in the agent
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
            self.agent.pending_blocks = current_subject.get_horas()
            await self.send_cfp_messages()
            self.set_next_state(NegotiationStates.COLLECTING)
        else:
            self.set_next_state(NegotiationStates.FINISHED)

class CollectingState(State):
    async def run(self):
        try:
            start_time = asyncio.get_event_loop().time()
            
            while asyncio.get_event_loop().time() - start_time < self.agent.timeout:
                msg = await self.receive(timeout=0.05)
                
                if msg:
                    sender = str(msg.sender)
                    response_time = asyncio.get_event_loop().time() - self.agent.response_times.get(sender, start_time)
                    
                    # Track response regardless of type
                    if sender in self.agent.expected_rooms:
                        self.agent.responding_rooms.add(sender)
                    
                    if msg.get_metadata("performative") == "propose":
                        await self.handle_proposal(msg)
                        self.agent.log.debug(f"Proposal from {sender} received in {response_time:.3f}s")
                    elif msg.get_metadata("performative") == "refuse":
                        self.agent.log.debug(f"Refuse from {sender} received in {response_time:.3f}s")
                
                # Log progress
                if len(self.agent.responding_rooms) == self.agent.cfp_count:
                    self.agent.log.info("Received all expected responses")
                    break
                    
                await asyncio.sleep(0.05)
            
            # Report collection results
            responses = len(self.agent.responding_rooms)
            missing = self.agent.cfp_count - responses
            self.agent.log.info(
                f"Collection complete: {responses}/{self.agent.cfp_count} responses received. "
                f"Missing responses: {missing}"
            )
            
            # List non-responding rooms
            if missing > 0:
                non_responding = self.agent.expected_rooms - self.agent.responding_rooms
                self.agent.log.warning(f"No response from rooms: {non_responding}")
            
            # Determine next state
            if not self.agent.proposals.empty():
                self.set_next_state(NegotiationStates.EVALUATING)
            else:
                self.set_next_state(NegotiationStates.SETUP)
                
        except Exception as e:
            self.agent.log.error(f"Error in collecting state: {str(e)}")
            self.set_next_state(NegotiationStates.SETUP)

class EvaluatingState(State):
    async def run(self):
        try:
            # Log response statistics before evaluation
            total_rooms = len(self.agent.expected_rooms)
            responded_rooms = len(self.agent.responding_rooms)
            propose_count = self.agent.proposals.qsize()
            refuse_count = responded_rooms - propose_count
            
            self.agent.log.info(
                f"Evaluation starting with: "
                f"{propose_count} proposals, {refuse_count} refusals, "
                f"{total_rooms - responded_rooms} no responses"
            )
            
            # Process proposals and continue with evaluation logic...
            proposals = []
            while not self.agent.proposals.empty():
                proposals.append(await self.agent.proposals.get())
                
            valid_proposals = await self.filter_and_sort_proposals(proposals)
            
            if valid_proposals and await self.try_assign_proposals(valid_proposals):
                if self.agent.pending_blocks == 0:
                    await self.agent.move_to_next_subject()
                    self.set_next_state(NegotiationStates.SETUP)
                else:
                    self.set_next_state(NegotiationStates.COLLECTING)
            else:
                self.set_next_state(NegotiationStates.SETUP)
                
        except Exception as e:
            self.agent.log.error(f"Error in evaluating state: {str(e)}")
            self.set_next_state(NegotiationStates.SETUP)
        
    async def try_assign_batch_proposals(self, batch_proposals: List[BatchProposal]) -> bool:
        """Try to assign batch proposals to classrooms"""
        current_subject = self.profesor.get_current_subject()
        required_hours = current_subject.get_horas()
        batch_start_time = datetime.now()

        if self.bloques_pendientes <= 0 or self.bloques_pendientes > required_hours:
            self.profesor.log.error(
                f"Invalid pending hours state: {self.bloques_pendientes}/{required_hours} "
                f"for {current_subject.get_nombre()}"
            )
            return False

        daily_assignments = defaultdict(int)
        total_assigned = 0

        for batch_proposal in batch_proposals:
            proposal_start_time = datetime.now()
            requests = []

            # Process each day's blocks in this room
            for day, block_proposals in batch_proposal.get_day_proposals().items():
                # Skip if day already has 2 blocks
                if daily_assignments[day] >= 2:
                    continue

                # Process blocks for this day
                for block in block_proposals:
                    # Stop if we've assigned all needed blocks
                    if total_assigned >= self.bloques_pendientes:
                        break

                    # Skip if block not available
                    if not self.profesor.is_block_available(day, block.get_block()):
                        continue

                    requests.append(AssignmentRequest(
                        day=day,
                        block=block.get_block(),
                        subject_name=current_subject.get_nombre(),
                        satisfaction=batch_proposal.get_satisfaction_score(),
                        classroom_code=batch_proposal.get_room_code(),
                        vacancy=current_subject.get_vacantes()
                    ))

                    total_assigned += 1
                    daily_assignments[day] += 1

            # Send batch assignment if we have requests
            if len(requests) > 0:
                try:
                    if await self.send_batch_assignment(requests, batch_proposal.get_original_message()):
                        self.profesor.log.info(
                            f"Successfully assigned {len(requests)} blocks in room "
                            f"{batch_proposal.get_room_code()} for {current_subject.get_nombre()}"
                        )

                        proposal_time = (datetime.now() - proposal_start_time).total_seconds() * 1000
                        self.profesor.log.info(
                            f"[TIMING] Room {batch_proposal.get_room_code()} assignment took "
                            f"{proposal_time} ms - Assigned {len(requests)} blocks for "
                            f"{current_subject.get_nombre()}"
                        )
                except Exception as e:
                    self.profesor.log.error(f"Error in batch assignment: {str(e)}")
                    return False

        total_batch_time = (datetime.now() - batch_start_time).total_seconds() * 1000
        self.profesor.log.info(
            f"[TIMING] Total batch assignment time for {current_subject.get_nombre()}: "
            f"{total_batch_time} ms - Total blocks assigned: {total_assigned}"
        )

        return total_assigned > 0

class FinishedState(State):
    async def run(self):
        await self.agent.finish_negotiations()
        self.kill()