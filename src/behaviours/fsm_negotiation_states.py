from spade.behaviour import FSMBehaviour, State
from spade.message import Message
import asyncio
import jsonpickle
import datetime
from typing import List, Set, Dict
from objects.helper.batch_proposals import BatchProposal
from objects.helper.confirmed_assignments import BatchAssignmentConfirmation
from objects.helper.batch_requests import AssignmentRequest, BatchAssignmentRequest
from objects.asignation_data import AssignationData
from collections import defaultdict
from evaluators.constraint_evaluator import ConstraintEvaluator
from fipa.acl_message import FIPAPerformatives
import json
from datetime import datetime, timedelta
from aioxmpp import JID
from objects.helper.quick_rejector import RoomQuickRejectFilter

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
        self.agent = profesor_agent
        # Rather than saving it here we could save it in the agent
        self.proposals = asyncio.Queue()
        self.timeout = 5  # seconds
        self.bloques_pendientes = 0
        self.evaluator = ConstraintEvaluator(professor_agent=profesor_agent, fsm_behaviour=self)
        self.assignation_data = AssignationData()
        
        self.responding_rooms: Set[str] = set()  # Track rooms that responded
        self.expected_rooms: Set[str] = set()    # Track rooms we sent CFPs to
        self.response_times: Dict[str, float] = {}  # Track response times per room
        
        self.cfp_count = 0  # Track number of CFPs sent
        self.negotiation_start_time = None
        self.retry_count = 0
    
        # Add states
        self.add_state(NegotiationStates.SETUP, SetupState(parent=self), initial=True)
        self.add_state(NegotiationStates.COLLECTING, CollectingState(parent=self))
        self.add_state(NegotiationStates.EVALUATING, EvaluatingState(evaluator=self.evaluator, parent=self))
        self.add_state(NegotiationStates.FINISHED, FinishedState(parent=self))
        
        # Define transitions
        self.add_transition(NegotiationStates.SETUP, NegotiationStates.COLLECTING)
        self.add_transition(NegotiationStates.COLLECTING, NegotiationStates.EVALUATING)
        self.add_transition(NegotiationStates.COLLECTING, NegotiationStates.SETUP)
        self.add_transition(NegotiationStates.EVALUATING, NegotiationStates.SETUP)
        self.add_transition(NegotiationStates.EVALUATING, NegotiationStates.FINISHED)
        self.add_transition(NegotiationStates.EVALUATING, NegotiationStates.COLLECTING)
        self.add_transition(NegotiationStates.SETUP, NegotiationStates.FINISHED)

class SetupState(State):
    def __init__(self, parent: NegotiationFSM):
        self.parent = parent
        self.room_filter = RoomQuickRejectFilter()
        super().__init__()

    async def run(self):
        self.agent.log.info(f"Starting negotiation setup for professor {self.agent.nombre}")
        if not self.agent.can_use_more_subjects():
            self.set_next_state(NegotiationStates.FINISHED)
            return

        current_subject = self.agent.get_current_subject()
        if current_subject:
            self.parent.bloques_pendientes = current_subject.get_horas()
            self.parent.negotiation_start_time = datetime.now()
            
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
            
    @staticmethod
    def sanitize_subject_name(name: str) -> str:
        """Sanitize subject name removing special characters"""
        return ''.join(c for c in name if c.isalnum())
            
    async def send_cfp_messages(self):
        """Send CFP messages to classroom agents"""
        try:
            current_subject = self.agent.get_current_subject()
            if not current_subject:
                self.agent.log.error(f"No current subject available for professor {self.agent.nombre}")
                return 0

            rooms = await self.agent._kb.search(service_type="sala")
            
            if not rooms:
                self.agent.log.error("No rooms found in knowledge base")
                return 0

            # Build request info
            solicitud_info = {
                "nombre": self.sanitize_subject_name(current_subject.get_nombre()),
                "vacantes": current_subject.get_vacantes(),
                "nivel": current_subject.get_nivel(),
                "campus": current_subject.get_campus(),
                "bloques_pendientes": self.parent.bloques_pendientes,
                "sala_asignada": self.parent.assignation_data.get_sala_asignada(),
                "ultimo_dia": self.parent.assignation_data.get_ultimo_dia_asignado().name if self.parent.assignation_data.get_ultimo_dia_asignado() else "",
                "ultimo_bloque": self.parent.assignation_data.get_ultimo_bloque_asignado()
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
                self.agent.log.debug(f"No suitable rooms found after filtering for {current_subject.get_nombre()}")
                return 0

            # Send CFP only to filtered rooms
            for room in filtered_rooms:
                msg = Message(
                    to=str(room.jid)
                )
                msg.set_metadata("protocol", "contract-net")
                msg.set_metadata("performative", FIPAPerformatives.CFP)
                msg.set_metadata("conversation-id", f"neg-{self.agent.nombre}-{self.parent.bloques_pendientes}")
                msg.body = json.dumps(solicitud_info)
                
                await self.send(msg)
                cfp_count += 1
            self.agent.log.info(f"Sent CFPs to {cfp_count} rooms out of {len(rooms)} total rooms")
            self.parent.expected_rooms = {str(r.jid) for r in filtered_rooms}
            return cfp_count
        except Exception as e:
            self.agent.log.error(f"Error sending proposal requests: {str(e)}")
            
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
            
    async def handle_proposal(self, msg: Message):
        """
        Handle received proposal messages.
        
        Args:
            msg: The received SPADE message
        """
        try:
            # Parse the content (assumed to be JSON)
            availability = jsonpickle.decode(msg.body)

            if availability:
                # Create batch proposal
                batch_proposal = BatchProposal.from_availability(availability, msg)
                
                # Add to queue
                await self.parent.proposals.put(batch_proposal)                
            else:
                self.agent.log.warning("Received null classroom availability")

        except Exception as e:
            self.agent.log.error(f"Error processing proposal: {str(e)}")

class EvaluatingState(State):
    TIMEOUT_PROPUESTA = 1000
    MAX_RETRIES = 3
    
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

            if valid_proposals and await self.try_assign_batch_proposals(valid_proposals):
                if self.parent.bloques_pendientes == 0:
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
        current_subject = self.agent.get_current_subject()
        required_hours = current_subject.get_horas()
        batch_start_time = datetime.now()

        if self.parent.bloques_pendientes <= 0 or self.parent.bloques_pendientes > required_hours:
            self.agent.log.error(
                f"Invalid pending hours state: {self.parent.bloques_pendientes}/{required_hours} "
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
                daily_count = daily_assignments.get(day, 0)
                # Skip if day already has 2 blocks
                if daily_count >= 2:
                    continue

                # Process blocks for this day
                for block in block_proposals:
                    # Stop if we've assigned all needed blocks
                    if total_assigned >= self.parent.bloques_pendientes:
                        break

                    # Skip if block not available
                    if not self.agent.is_block_available(day, block.get_block()):
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
                        self.agent.log.info(
                            f"Successfully assigned {len(requests)} blocks in room "
                            f"{batch_proposal.get_room_code()} for {current_subject.get_nombre()}"
                        )

                        proposal_time = (datetime.now() - proposal_start_time).total_seconds() * 1000
                        self.agent.log.info(
                            f"[TIMING] Room {batch_proposal.get_room_code()} assignment took "
                            f"{proposal_time} ms - Assigned {len(requests)} blocks for "
                            f"{current_subject.get_nombre()}"
                        )
                except Exception as e:
                    self.agent.log.error(f"Error in batch assignment: {str(e)}")
                    return False

        total_batch_time = (datetime.now() - batch_start_time).total_seconds() * 1000
        self.agent.log.info(
            f"[TIMING] Total batch assignment time for {current_subject.get_nombre()}: "
            f"{total_batch_time} ms - Total blocks assigned: {total_assigned}"
        )

        return total_assigned > 0
    
    async def send_batch_assignment(
        self,
        requests: List[AssignmentRequest],
        original_msg: Message
    ) -> bool:
        """Send batch assignment request and wait for confirmation"""
        if self.parent.bloques_pendientes - len(requests) < 0:
            self.agent.log.warning("Assignment would exceed required hours")
            return False
        
        try:
            conv_id = original_msg.get_metadata("conversation-id")
            # Create batch request message
            msg = Message()
            msg.to = str(original_msg.sender)
            msg.set_metadata("performative", FIPAPerformatives.ACCEPT_PROPOSAL)
            msg.set_metadata("ontology", "room-assignment")
            msg.set_metadata("conversation-id", conv_id)
            msg.set_metadata("protocol", "contract-net")
            
            msg.body = jsonpickle.encode(BatchAssignmentRequest(requests))

            # Send message and wait for confirmation
            await self.send(msg)
            
            # Wait for confirmation with timeout
            start_time = datetime.now()
            timeout = timedelta(seconds=1)

            while datetime.now() - start_time < timeout:
                confirmation_msg = await self.receive(timeout=0.1)
                if confirmation_msg and self.is_valid_confirm(confirmation_msg, original_msg.sender, conv_id):                    
                    confirmation_data : BatchAssignmentConfirmation = jsonpickle.decode(confirmation_msg.body)

                    # Process confirmed assignments
                    for assignment in confirmation_data.get_confirmed_assignments():
                        await self.agent.update_schedule_info(
                            dia=assignment.get_day(),
                            sala=assignment.get_classroom_code(),
                            bloque=assignment.get_block(),
                            nombre_asignatura=self.agent.get_current_subject().get_nombre(),
                            satisfaccion=assignment.get_satisfaction()
                        )

                        self.parent.bloques_pendientes -= 1
                        self.parent.assignation_data.assign(
                            assignment.get_day(),
                            assignment.get_classroom_code(),
                            assignment.get_block()
                        )

                    return True

                await asyncio.sleep(0.05)

        except Exception as e:
            self.agent.log.error(f"Error in send_batch_assignment: {str(e)}")
            
        return False
    
    def is_valid_confirm(self, confirm : Message, og_sender : JID, conv_id : str) -> bool:
        return confirm.get_metadata("performative") == FIPAPerformatives.INFORM and\
        confirm.sender == og_sender and confirm.get_metadata("conversation-id") == conv_id
        
    async def handle_proposal_failure(self):
        """Handle failure to assign proposals."""
        self.parent.retry_count += 1
        if self.retry_count >= self.MAX_RETRIES:
            if self.parent.assignation_data.has_sala_asignada():
                # Try different room if current one isn't working
                self.agent.log.critical("Max retries reached - clearing assigned room")
                self.parent.assignation_data.set_sala_asignada(None)
            else:
                # If we've tried different rooms without success, move on
                self.agent.log.critical("Max retries reached - moving to next subject")
                await self.agent.move_to_next_subject()
            
            self.parent.retry_count = 0
            self.set_next_state(NegotiationStates.SETUP)
        else:
            # Add exponential backoff
            backoff_time = 2 ** self.parent.retry_count * 1000
            self.agent.log.debug(
                f"Retry {self.parent.retry_count}/{self.MAX_RETRIES} - "
                f"backing off for {backoff_time}ms"
            )
            
            # In SPADE we need to use asyncio.sleep for the backoff
            await asyncio.sleep(backoff_time / 1000)  # Convert to seconds
            
            self.set_next_state(NegotiationStates.COLLECTING)
            await self.send_proposal_requests()

class FinishedState(State):
    def __init__(self, parent: NegotiationFSM):
        self.parent = parent
        super().__init__()
    
    async def run(self):
        await self.finish_negotiations()
        self.kill()
        
    async def finish_negotiations(self):
        """Handle finished state and cleanup"""
        try:
            # Record completion time
            total_time = (datetime.now() - self.parent.negotiation_start_time).total_seconds() * 1000
            self.agent.log.info(
                f"Professor {self.agent.nombre} completed all negotiations in {total_time} ms"
            )

            # Notify next professor first
            await self.notify_next_professor()
            
            # Kill this behavior
            self.kill()
                
            # Start cleanup with small delay to allow next prof to start
            await asyncio.sleep(0.5)
            await self.agent.cleanup()
            
        except Exception as e:
            self.agent.log.error(f"Error in finish_negotiations: {str(e)}")
            
    async def notify_next_professor(self):
        try:
            next_orden = self.agent.orden + 1
            
            # Search for next professor
            professors = await self.agent._kb.search(
                service_type="profesor",
                properties={"orden": next_orden}
            )
            
            if professors:
                next_professor = professors[0]
                
                # Create START message
                msg = Message(to=str(next_professor.jid))
                msg.set_metadata("performative", FIPAPerformatives.INFORM)
                msg.set_metadata("conversation-id", "negotiation-start")
                msg.set_metadata("nextOrden", str(next_orden))
                
                msg.body = "START"
                
                await self.send(msg)
                self.agent.log.info(f"Successfully notified next professor with order: {next_orden}")
            else:
                # No next professor means we're done - trigger system shutdown
                self.agent.log.info("No next professor found - all professors completed")
                
                # Notify supervisor to begin shutdown
                supervisor_agents = await self.agent._kb.search(service_type="supervisor")
                if supervisor_agents:
                    supervisor = supervisor_agents[0]
                    shutdown_msg = Message(to=str(supervisor.jid))
                    shutdown_msg.set_metadata("performative", FIPAPerformatives.INFORM)
                    shutdown_msg.set_metadata("ontology", "system-control")
                    shutdown_msg.set_metadata("content", "SHUTDOWN")
                    
                    await self.send(shutdown_msg)
                    self.agent.log.info("Sent shutdown signal to supervisor")
                else:
                    self.agent.log.error("Could not find supervisor agent for shutdown")
                    # Even without supervisor, proceed with cleanup
                    await self.agent.cleanup()
                
        except Exception as e:
            self.agent.log.error(f"Error in notify_next_professor: {str(e)}")
            # On error, attempt cleanup to avoid stuck state
            await self.agent.cleanup()