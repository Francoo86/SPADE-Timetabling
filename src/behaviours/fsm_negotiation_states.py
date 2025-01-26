from spade.behaviour import FSMBehaviour, State

from spade.behaviour import FSMBehaviour, State
from spade.message import Message
from spade.template import Template
import asyncio
import jsonpickle
import datetime
from typing import List, Set, Dict
from objects.helper.batch_proposals import BatchProposal
from objects.helper.batch_requests import AssignmentRequest
from collections import defaultdict
from evaluators.constraint_evaluator import ConstraintEvaluator
from fipa.acl_message import FIPAPerformatives
import json

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
        self.bloques_pendientes = 0
        self.evaluator = ConstraintEvaluator(professor_agent=profesor_agent, fsm_behaviour=self)
        
        self.responding_rooms: Set[str] = set()  # Track rooms that responded
        self.expected_rooms: Set[str] = set()    # Track rooms we sent CFPs to
        self.response_times: Dict[str, float] = {}  # Track response times per room
        
        # Add states
        self.add_state(NegotiationStates.SETUP, SetupState(parent=self))
        self.add_state(NegotiationStates.COLLECTING, CollectingState(parent=self))
        self.add_state(NegotiationStates.EVALUATING, EvaluatingState(evaluator=self.evaluator, parent=self))
        self.add_state(NegotiationStates.FINISHED, FinishedState())
        
        # Define transitions
        self.add_transition(NegotiationStates.SETUP, NegotiationStates.COLLECTING)
        self.add_transition(NegotiationStates.COLLECTING, NegotiationStates.EVALUATING)
        self.add_transition(NegotiationStates.EVALUATING, NegotiationStates.SETUP)
        self.add_transition(NegotiationStates.EVALUATING, NegotiationStates.FINISHED)
        self.add_transition(NegotiationStates.SETUP, NegotiationStates.FINISHED)

class SetupState(State):
    def __init__(self, parent: NegotiationFSM):
        self.parent = parent
        super().__init__()

    async def run(self):
        if not self.agent.can_use_more_subjects():
            self.set_next_state(NegotiationStates.FINISHED)
            return

        current_subject = self.agent.get_current_subject()
        if current_subject:
            self.parent.pending_blocks = current_subject.get_horas()
            
            # Clear tracking sets for new round
            self.parent.responding_rooms.clear()
            self.parent.expected_rooms.clear()
            self.parent.response_times.clear()
            
            # Send CFPs and track sent count
            cfp_count = await self.send_cfp_messages()
            self.parent.cfp_count = cfp_count
            
            self.agent.log.info(f"Sent {cfp_count} CFPs for {current_subject.get_nombre()}")
            self.set_next_state(NegotiationStates.COLLECTING)
        else:
            self.set_next_state(NegotiationStates.FINISHED)
            
    async def send_cfp_messages(self):
        """Send CFP messages to classroom agents"""
        try:
            current_subject = self.profesor.get_current_subject()
            if not current_subject:
                self.profesor.log.error(f"No current subject available for professor {self.profesor.nombre}")
                return

            rooms = await self.profesor._kb.search(service_type="sala")
            
            if not rooms:
                self.profesor.log.error("No rooms found in knowledge base")
                return

            # Build request info
            solicitud_info = {
                "nombre": self.sanitize_subject_name(current_subject.get_nombre()),
                "vacantes": current_subject.get_vacantes(),
                "nivel": current_subject.get_nivel(),
                "campus": current_subject.get_campus(),
                "bloques_pendientes": self.bloques_pendientes,
                "sala_asignada": self.assignation_data.get_sala_asignada(),
                "ultimo_dia": self.assignation_data.get_ultimo_dia_asignado().name if self.assignation_data.get_ultimo_dia_asignado() else "",
                "ultimo_bloque": self.assignation_data.get_ultimo_bloque_asignado()
            }

            cfp_count = 0
            # Filter rooms before sending CFPs
            filtered_rooms = []
            for room in rooms:
                # Extract room properties from capabilities
                room_caps = next((cap for cap in room.capabilities if cap.service_type == "sala"), None)
                if not room_caps:
                    continue
                
                room_props = room_caps.properties
                
                should_reject = await self.room_filter.can_quick_reject(
                    subject_name=current_subject.get_nombre(),
                    subject_code=current_subject.get_codigo_asignatura(),
                    subject_campus=current_subject.get_campus(),
                    subject_vacancies=current_subject.get_vacantes(),
                    room_code=room_props["codigo"],
                    room_campus=room_props["campus"],
                    room_capacity=room_props["capacidad"]
                )
                
                if not should_reject:
                    filtered_rooms.append(room)

            if not filtered_rooms:
                self.profesor.log.debug(f"No suitable rooms found after filtering for {current_subject.get_nombre()}")
                return

            # Send CFP only to filtered rooms
            for room in filtered_rooms:
                msg = Message(
                    to=str(room.jid)
                )
                msg.set_metadata("protocol", "contract-net")
                msg.set_metadata("performative", FIPAPerformatives.CFP)
                msg.set_metadata("conversation-id", f"neg-{self.profesor.nombre}-{self.bloques_pendientes}")
                msg.body = json.dumps(solicitud_info)
                
                await self.send(msg)
                cfp_count += 1
            self.profesor.log.info(f"Sent CFPs to {cfp_count} rooms out of {len(rooms)} total rooms")
            return cfp_count
        except Exception as e:
            self.profesor.log.error(f"Error sending proposal requests: {str(e)}")
            
        return 0


class CollectingState(State):
    def __init__(self, parent: NegotiationFSM):
        self.parent = parent
        super().__init__()
    
    async def run(self):
        try:
            start_time = asyncio.get_event_loop().time()
            
            while asyncio.get_event_loop().time() - start_time < self.parent.timeout:
                msg = await self.receive(timeout=0.05)
                
                if msg:
                    sender = str(msg.sender)
                    response_time = asyncio.get_event_loop().time() - self.parent.response_times.get(sender, start_time)
                    
                    # Track response regardless of type
                    if sender in self.parent.expected_rooms:
                        self.parent.responding_rooms.add(sender)
                    
                    if msg.get_metadata("performative") == "propose":
                        await self.handle_proposal(msg)
                        self.agent.log.debug(f"Proposal from {sender} received in {response_time:.3f}s")
                    elif msg.get_metadata("performative") == "refuse":
                        self.agent.log.debug(f"Refuse from {sender} received in {response_time:.3f}s")
                
                # Log progress
                if len(self.parent.responding_rooms) == self.parent.cfp_count:
                    self.agent.log.info("Received all expected responses")
                    break
                    
                await asyncio.sleep(0.05)
            
            # Report collection results
            responses = len(self.parent.responding_rooms)
            missing = self.parent.cfp_count - responses
            self.agent.log.info(
                f"Collection complete: {responses}/{self.parent.cfp_count} responses received. "
                f"Missing responses: {missing}"
            )
            
            # List non-responding rooms
            if missing > 0:
                non_responding = self.parent.expected_rooms - self.parent.responding_rooms
                self.agent.log.warning(f"No response from rooms: {non_responding}")
            
            # Determine next state
            if not self.parent.proposals.empty():
                self.set_next_state(NegotiationStates.EVALUATING)
            else:
                self.set_next_state(NegotiationStates.SETUP)
                
        except Exception as e:
            self.agent.log.error(f"Error in collecting state: {str(e)}")
            self.set_next_state(NegotiationStates.SETUP)

class EvaluatingState(State):
    def __init__(self, evaluator: ConstraintEvaluator, parent: NegotiationFSM):
        self.evaluator = evaluator
        self.parent = parent
        super().__init__()
    
    async def run(self):
        try:
            # Log response statistics before evaluation
            total_rooms = len(self.parent.expected_rooms)
            responded_rooms = len(self.parent.responding_rooms)
            propose_count = self.parent.proposals.qsize()
            refuse_count = responded_rooms - propose_count
            
            self.agent.log.info(
                f"Evaluation starting with: "
                f"{propose_count} proposals, {refuse_count} refusals, "
                f"{total_rooms - responded_rooms} no responses"
            )
            
            # Process proposals and continue with evaluation logic...
            proposals = []
            while not self.parent.proposals.empty():
                proposals.append(await self.parent.proposals.get())
                
            valid_proposals = await self.evaluator.filter_and_sort_proposals(proposals)
            
            if valid_proposals and await self.try_assign_proposals(valid_proposals):
                if self.parent.pending_blocks == 0:
                    await self.agent.move_to_next_subject()
                    self.set_next_state(NegotiationStates.SETUP)
                else:
                    self.set_next_state(NegotiationStates.COLLECTING)
            else:
                self.set_next_state(NegotiationStates.SETUP)
                
        except Exception as e:
            self.agent.log.error(f"Error in evaluating state: {str(e)}")
            self.set_next_state(NegotiationStates.SETUP)

class FinishedState(State):
    async def run(self):
        await self.agent.finish_negotiations()
        self.kill()