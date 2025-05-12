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
from performance.rtt_stats import RTTLogger
import uuid

# States for the FSM
class NegotiationStates:
    SETUP = "SETUP"
    COLLECTING = "COLLECTING"
    EVALUATING = "EVALUATING"
    FINISHED = "FINISHED"

class NegotiationFSM(FSMBehaviour):
    """FSM for handling professor negotiations"""
    MAX_RETRIES = 3
    BASE_TIMEOUT = 5 # 1 second, relative to 1000ms in JADE
    BACKOFF_OFFSET = 1 # also 1 second, relative to 1000ms in JADE
    
    def __init__(self, profesor_agent):
        super().__init__()
        self.agent = profesor_agent
        # Rather than saving it here we could save it in the agent
        self.proposals = asyncio.Queue()
        self.timeout = 0  # seconds
        self.bloques_pendientes = 0
        self.evaluator = ConstraintEvaluator(professor_agent=profesor_agent, fsm_behaviour=self)
        self.assignation_data = AssignationData()
        
        self.responding_rooms: Set[str] = set()  # Track rooms that responded
        self.expected_rooms: Set[str] = set()    # Track rooms we sent CFPs to
        self.response_times: Dict[str, float] = {}  # Track response times per room
        
        self.cfp_count = 0  # Track number of CFPs sent
        self.received_proposals = 0 # Track number of proposals received
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
        
        # A FALLBACK ONLY
        self.add_transition(NegotiationStates.SETUP, NegotiationStates.SETUP)
        self.add_transition(NegotiationStates.COLLECTING, NegotiationStates.COLLECTING)
        
class CFPSenderState(State):
    def __init__(self, parent: NegotiationFSM):
        self.parent = parent
        self.room_filter = RoomQuickRejectFilter()
        # self.rtt_logger = parent.agent.rtt_logger
        # self.rtt_logger : 'RTTLogger' = None
        self.rtt_initialized = False
        super().__init__()
        
    @staticmethod
    def sanitize_subject_name(name: str) -> str:
        """Sanitize subject name removing special characters"""
        return ''.join(c for c in name if c.isalnum())
    
    async def on_start(self):
        pass
        # if self.rtt_initialized:
            # return
        
        # self.rtt_logger = RTTLogger(str(self.agent.jid), self.agent.scenario)
        # self.rtt_initialized = True
        # await self.rtt_logger.start()
        
    async def send_cfp_messages(self):
        self.parent.cfp_count = 0
        self.parent.received_proposals = 0
        
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
                
                cfp_id = f"cfp-{str(uuid.uuid4())}"
                msg.set_metadata("rtt-id", cfp_id)
                
                await self.parent.agent.rtt_logger.start_request(
                    agent_name=self.parent.agent.nombre,
                    conversation_id=cfp_id,
                    performative=FIPAPerformatives.CFP,
                    receiver=str(room.jid),
                    ontology="classroom-availability"
                )
                
                await self.send(msg)

                cfp_count += 1
            self.agent.log.info(f"Sent CFPs to {cfp_count} rooms out of {len(rooms)} total rooms")
            self.parent.expected_rooms = {str(r.jid) for r in filtered_rooms}
            self.parent.cfp_count = cfp_count
            return cfp_count
        except Exception as e:
            self.agent.log.error(f"Error sending proposal requests: {str(e)}")
            
        return 0

class SetupState(CFPSenderState):
    def __init__(self, parent: NegotiationFSM):
        # self.parent = parent
        super().__init__(parent=parent)

    async def run(self):
        self.agent.log.info(f"Starting negotiation setup for professor {self.agent.nombre}")
        if not self.agent.can_use_more_subjects():
            self.set_next_state(NegotiationStates.FINISHED)
            return

        current_subject = self.agent.get_current_subject()
        if not current_subject:
            self.agent.log.error("No current subject available for negotiation")
            self.set_next_state(NegotiationStates.FINISHED)
            return

        self.parent.bloques_pendientes = current_subject.get_horas()
        self.parent.assignation_data.clear()
        
        # SPADE specific stuff, JADE doesn't have it.
        self.parent.responding_rooms.clear()
        self.parent.expected_rooms.clear()
        self.parent.response_times.clear()
        
        self.parent.negotiation_start_time = datetime.now()
        
        await self.send_cfp_messages()
        # self.parent.cfp_count = cfp_count
        cfp_count = self.parent.cfp_count
        
        if cfp_count > 0:
            self.agent.log.info(f"Sent {cfp_count} CFPs for {current_subject.get_nombre()} type: {current_subject.get_actividad()}")
            self.set_next_state(NegotiationStates.COLLECTING)
            self.parent.timeout = self.parent.BASE_TIMEOUT
        else:
            # NOTE: THIS SHOULDN'T EVEN HAPPEN...
            # Handle the case where no rooms are available
            self.agent.log.warning(f"No suitable rooms found for {current_subject.get_nombre()} (retry {self.parent.retry_count + 1}/{self.parent.MAX_RETRIES})")
            
            # Increment retry count
            self.parent.retry_count += 1
            
            # If we've reached max retries, move to the next subject
            if self.parent.retry_count >= self.parent.MAX_RETRIES:
                self.agent.log.info(f"Max retries reached for {current_subject.get_nombre()}, moving to next subject")
                await self.agent.move_to_next_subject()
                self.parent.retry_count = 0
            
            # Stay in SETUP state to retry or try with new subject
            self.set_next_state(NegotiationStates.SETUP)

class CollectingState(CFPSenderState):
    def __init__(self, parent: NegotiationFSM):
        self.parent = parent
        # self.rtt_logger = RTTLogger(str(self.parent.agent.jid), self.parent.agent.scenario)
        super().__init__(parent=parent)
        
    async def __log_response(self, msg : Message):
        await self.parent.agent.rtt_logger.end_request(
            agent_name=self.parent.agent.nombre,
            conversation_id=msg.get_metadata("rtt-id"),
            response_performative=msg.get_metadata("performative"),
#             sender=str(msg.sender),
            ontology="classroom-availability",
            message_size=len(msg.body),
            success=True
        )
    
    async def run(self):
        try:
            start_time = asyncio.get_event_loop().time()
            already_msgs_id = set()
            proposes_received = 0
            refuses_received = 0
            
            # Add minimum collection time to prevent rapid cycling
            min_collection_time = 0.5  # 500ms minimum wait
            min_end_time = start_time + min_collection_time
            
            # Regular collection logic
            while asyncio.get_event_loop().time() - start_time < self.parent.timeout:
                msg = await self.receive(timeout=0.1)
                
                if msg:
                    # Skip already processed messages
                    if msg.id in already_msgs_id:
                        self.agent.log.warning(f"Skipping already processed message: {msg.id}")
                        continue
                    
                    self.parent.received_proposals += 1
                    
                    sender = str(msg.sender)
                    already_msgs_id.add(msg.id)
                    
                    # In JADE this is done by an internal count.
                    if sender in self.parent.expected_rooms:
                        self.parent.responding_rooms.add(sender)
                    
                    if msg.get_metadata("performative") == FIPAPerformatives.PROPOSE:
                        proposes_received += 1
                        await self.handle_proposal(msg)
                    elif msg.get_metadata("performative") == FIPAPerformatives.REFUSE:
                        refuses_received += 1
                        
                    await self.__log_response(msg)
                
                # Log progress
                if self.parent.received_proposals >= self.parent.cfp_count and self.parent.cfp_count > 0:
                    self.agent.log.info("Received all expected responses")
                    break
                    
                    #if asyncio.get_event_loop().time() >= min_end_time:
                    #    break
                        
                await asyncio.sleep(0.05)
            
            # Report collection results
            responses = len(self.parent.responding_rooms)
            proposes = proposes_received
            refuses = refuses_received
            
            self.agent.log.info(
                f"Collection complete: {responses}/{self.parent.cfp_count} responses received. "
                f"Proposes: {proposes}, Refuses: {refuses}"
            )
            
            # Add a delay when all responses were REFUSE to slow down cycling
            if refuses == responses and responses > 0:
                self.agent.log.warning("All rooms refused - adding delay before retry")
                await asyncio.sleep(1.0)  # Add a 1-second delay to really slow down the spam
            
            if not self.parent.proposals.empty():
                self.set_next_state(NegotiationStates.EVALUATING)
            else:
                await self.handle_no_proposals()
                """
                self.parent.retry_count += 1
                
                if self.parent.retry_count >= self.parent.MAX_RETRIES:
                    self.agent.log.info(f"Max retries ({self.parent.MAX_RETRIES}) reached with only refusals, moving to next subject")
                    await self.agent.move_to_next_subject()
                    self.parent.retry_count = 0
                else:
                    self.agent.log.info(f"No proposals received (retry {self.parent.retry_count}/{self.parent.MAX_RETRIES})")
                
                self.set_next_state(NegotiationStates.SETUP) """
        
        except Exception as e:
            self.agent.log.error(f"Error in collecting state: {str(e)}")
            self.set_next_state(NegotiationStates.SETUP)
            
    async def handle_no_proposals(self):
        self.parent.retry_count += 1
        
        if self.parent.retry_count >= self.parent.MAX_RETRIES:
            current_subject = self.agent.get_current_subject()
            
            if self.parent.bloques_pendientes == current_subject.get_horas():
                await self.agent.move_to_next_subject()
            else:
                self.parent.assignation_data.set_sala_asignada(None)
            
            self.parent.retry_count = 0
            self.set_next_state(NegotiationStates.SETUP)
        else:
            backoff_time = (2 ** self.parent.retry_count) * self.parent.BACKOFF_OFFSET
            self.parent.timeout = self.parent.BASE_TIMEOUT + backoff_time
            
            self.agent.log.info(f"Retrying with timeout {self.parent.timeout:.2f}s (retry {self.parent.retry_count}/{self.parent.MAX_RETRIES})")
            await self.send_cfp_messages()
            
            self.set_next_state(NegotiationStates.COLLECTING)
            
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

class EvaluatingState(CFPSenderState):
    TIMEOUT_PROPUESTA = 1000
    MAX_RETRIES = 3
    
    def __init__(self, evaluator: ConstraintEvaluator, parent: NegotiationFSM):
        self.evaluator = evaluator
        # self.parent = parent
        super().__init__(parent=parent)
    
    async def run(self):
        try:
            # Get all proposals atomically
            proposals = []
            while not self.parent.proposals.empty():
                try:
                    proposals.append(await self.parent.proposals.get())
                except Exception as e:
                    self.agent.log.error(f"Error getting proposal: {str(e)}")
                    break

            self.agent.log.debug(f"Processing {len(proposals)} proposals")
            
            valid_proposals = await self.evaluator.filter_and_sort_proposals(proposals)
            self.agent.log.debug(f"Found {len(valid_proposals)} valid proposals")

            if valid_proposals and await self.try_assign_batch_proposals(valid_proposals):
                self.parent.retry_count = 0

                if self.parent.bloques_pendientes == 0:
                    await self.agent.move_to_next_subject()
                    self.set_next_state(NegotiationStates.SETUP)
                else:
                    # Add timeout for sending new CFPs
                    try:
                        async with asyncio.timeout(5):  # 5 second timeout
                            await self.send_cfp_messages()
                            self.parent.timeout = self.parent.BASE_TIMEOUT
                            self.set_next_state(NegotiationStates.COLLECTING)
                    except asyncio.TimeoutError:
                        self.agent.log.error("Timeout sending CFPs")
                        self.set_next_state(NegotiationStates.SETUP)
            else:
                await self.handle_proposal_failure()
                
        except Exception as e:
            self.agent.log.error(f"Error in evaluating state: {str(e)}")
            # Always ensure we transition to a valid state
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
                        vacancy=current_subject.get_vacantes(),
                        prof_name=self.agent.nombre
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
            
            id_prop = f"assign-{str(uuid.uuid4())}"
            msg.set_metadata("rtt-id", id_prop)
            
            # TODO: Remove this because we only need CFP -> PROPOSE/REFUSE.
            #await self.rtt_logger.start_request(
            #    id_prop,
            #    FIPAPerformatives.ACCEPT_PROPOSAL,
            #    str(original_msg.sender),
            #    ontology="room-assignment"
            #)

            # Send message and wait for confirmation
            await self.send(msg)
            
            # Wait for confirmation with timeout
            start_time = datetime.now()
            timeout = timedelta(seconds=1)

            while datetime.now() - start_time < timeout:
                confirmation_msg = await self.receive(timeout=0.1)
                if confirmation_msg and self.is_valid_confirm(confirmation_msg, original_msg.sender, conv_id):                    
                    confirmation_data : BatchAssignmentConfirmation = jsonpickle.decode(confirmation_msg.body)
                    
                    #await self.rtt_logger.end_request(
                    #    id_prop,
                    #     response_performative=FIPAPerformatives.INFORM,
                    #     message_size=getsizeof(confirmation_msg.body),
                    #     success=True,
                    #     ontology="room-assignment"
                    # )

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
            #await self.rtt_logger.end_request(
            #    conv_id,
            #     "ERROR",
            #     0,
            #     success=False,
            #     extra_info={"error": str(e)},
            #     ontology="room-assignment"
            # )
            self.agent.log.error(f"Error in send_batch_assignment: {str(e)}")
    
        return False
    
    def is_valid_confirm(self, confirm : Message, og_sender : JID, conv_id : str) -> bool:
        return confirm.get_metadata("performative") == FIPAPerformatives.INFORM and\
        confirm.sender == og_sender and confirm.get_metadata("conversation-id") == conv_id
        
    async def handle_proposal_failure(self):
        """Handle proposal failure with proper error recovery"""
        try:
            self.parent.retry_count += 1
            self.agent.log.info(f"Handling proposal failure (retry {self.parent.retry_count}/{self.MAX_RETRIES})")
            
            if self.parent.retry_count >= self.MAX_RETRIES:
                if self.parent.assignation_data.has_sala_asignada():
                    self.parent.assignation_data.set_sala_asignada(None)
                else:
                    await self.agent.move_to_next_subject()
                self.parent.retry_count = 0
                self.set_next_state(NegotiationStates.SETUP)
            else:
                # Add timeout for retry
                try:
                    async with asyncio.timeout(5):
                        backoff_time = 2 ** self.parent.retry_count * self.parent.BACKOFF_OFFSET
                        self.parent.timeout = self.parent.BASE_TIMEOUT + backoff_time
                        
                        await self.send_cfp_messages()
                        self.set_next_state(NegotiationStates.COLLECTING)
                except asyncio.TimeoutError:
                    self.agent.log.error("Timeout during retry")
                    self.set_next_state(NegotiationStates.SETUP)
                    
        except Exception as e:
            # NOTE: Also this shouldn't happen.
            self.agent.log.error(f"Error in handle_proposal_failure: {str(e)}")
            self.set_next_state(NegotiationStates.SETUP)

class FinishedState(State):
    def __init__(self, parent: NegotiationFSM):
        self.parent = parent
        super().__init__()
    
    async def run(self):
        self.agent.log.info("Entering FinishedState")
        try:
            # Add more granular timeouts for better diagnosis
            async with asyncio.timeout(5):
                self.agent.log.info("Starting finish_negotiations()")
                await self.finish_negotiations()
                self.agent.log.info("finish_negotiations() completed, killing state")
                self.kill()
                self.agent.log.info("State killed successfully")
        except asyncio.TimeoutError as e:
            self.agent.log.error(f"Timeout during negotiation finish: {str(e)}")
            # Force kill on timeout
            self.kill()
            self.agent.log.info("State killed after timeout")
        except Exception as e:
            self.agent.log.error(f"Error in FinishedState: {str(e)}", exc_info=True)
            # Force kill on exception
            self.kill()
            self.agent.log.info("State killed after exception")
        
    async def finish_negotiations(self):
        """Handle finished state and cleanup"""
        try:
            # Record completion time
            total_time = (datetime.now() - self.parent.negotiation_start_time).total_seconds() * 1000
            self.agent.log.info(
                f"Professor {self.agent.nombre} completed all negotiations in {total_time} ms"
            )

            # Set agent state to finished
            self.agent.log.info("All subjects processed, finalizing agent")
            
            # Start cleanup with proper error handling and await it
            try:
                if self.agent.metrics_monitor:
                    await self.agent.metrics_monitor._flush_all()
                    
                # Perform cleanup
                await self.agent.cleanup()
                self.agent.log.info("Cleanup completed successfully")
                
                # Only notify next professor after cleanup is done
                await self.notify_next_professor()
                
            except Exception as e:
                self.agent.log.error(f"Error during cleanup: {str(e)}")
                
        except Exception as e:
            self.agent.log.error(f"Error in finish_negotiations: {str(e)}")
            
    async def notify_next_professor(self) -> bool:
        """Notify next professor and return success status"""
        try:
            next_orden = self.agent.orden + 1
            
            # Search for next professor
            professors = await self.agent._kb.search(
                service_type="profesor",
                properties={"orden": next_orden}
            )
            
            if professors:
                next_professor = professors[0]
                
                # Create START message with acknowledgment request
                msg = Message(to=str(next_professor.jid))
                msg.set_metadata("performative", FIPAPerformatives.INFORM)
                msg.set_metadata("conversation-id", "negotiation-start")
                msg.set_metadata("nextOrden", str(next_orden))
                # msg.set_metadata("require-ack", "true")
                msg.body = "START"
                
                await self.send(msg)
                self.agent.log.info(f"Notified next professor with order: {next_orden}.")
            
                return False
            else:
                # No next professor means we're done - trigger system shutdown
                self.agent.log.info("No next professor found - all professors completed")
                
                # Final metrics flush before shutdown
                if self.agent.metrics_monitor:
                    await self.agent.metrics_monitor._flush_all()
                
                # Notify supervisor to begin shutdown
                try:
                    supervisor_agents = await self.agent._kb.search(service_type="supervisor")
                    if supervisor_agents:
                        supervisor = supervisor_agents[0]
                        shutdown_msg = Message(to=str(supervisor.jid))
                        shutdown_msg.set_metadata("performative", FIPAPerformatives.INFORM)
                        shutdown_msg.set_metadata("ontology", "system-control")
                        shutdown_msg.set_metadata("content", "SHUTDOWN")
                        
                        await self.send(shutdown_msg)
                        self.agent.log.info("Sent shutdown signal to supervisor")
                        return True
                    else:
                        self.agent.log.error("Could not find supervisor agent for shutdown")
                except Exception as e:
                    self.agent.log.error(f"Error sending supervisor shutdown: {str(e)}")
                
                # Even without supervisor notification, proceed with cleanup
                return False
                
        except Exception as e:
            self.agent.log.error(f"Error in notify_next_professor: {str(e)}")
            return False