from spade.behaviour import PeriodicBehaviour, FSMBehaviour
from spade.message import Message
from spade.template import Template
from datetime import datetime, timedelta
import asyncio
from typing import Dict, List, Optional
from collections import defaultdict
import json
from aioxmpp import JID

from objects.static.agent_enums import NegotiationState, Day, TipoContrato
from objects.helper.batch_proposals import BatchProposal, BlockProposal
from objects.helper.confirmed_assignments import BatchAssignmentConfirmation
from objects.helper.batch_requests import AssignmentRequest, BatchAssignmentRequest
from objects.asignation_data import AssignationData, Asignatura
from evaluators.timetabling_evaluator import TimetablingEvaluator
from evaluators.constraint_evaluator import ConstraintEvaluator
from objects.knowledge_base import AgentKnowledgeBase
from objects.helper.quick_rejector import RoomQuickRejectFilter
from objects.asignation_data import Actividad
# from agents.profesor_redux import AgenteProfesor
import jsonpickle
# import dataclass
from dataclasses import dataclass
from fipa.acl_message import FIPAPerformatives

@dataclass
class BatchProposalScore:
    """Helper class to store proposal with its score"""
    proposal: BatchProposal
    score: int

# CRITICAL: Replace with FSM behaviour and remove Message Collector
class NegotiationStateBehaviour(PeriodicBehaviour):
    MEETING_ROOM_THRESHOLD = 10
    TIMEOUT_PROPUESTA = 1
    MAX_RETRIES = 3
    # En JADE teniamos 500 ms
    JADE_BASE_PERIOD = 0.5

    def __init__(self, profesor, batch_proposals : asyncio.Queue):
        """Initialize the negotiation state behaviour."""
        super().__init__(period=self.JADE_BASE_PERIOD)
        self.profesor = profesor
        self.propuestas = batch_proposals
        self.current_state = NegotiationState.SETUP
        self.assignation_data = AssignationData()
        self.negotiation_start_time = None
        self.proposal_timeout = None
        self.retry_count = 0
        self.proposal_received = False
        self.bloques_pendientes = 0
        self.subject_negotiation_times = {}
        
        self.cleanup_lock = asyncio.Lock()
        self.room_filter = RoomQuickRejectFilter()
        self.constraint_evaluator = ConstraintEvaluator(professor_agent=profesor, fsm_behaviour=self)

    async def run(self):
        """Main behaviour loop"""
        try:
            if self.current_state == NegotiationState.SETUP:
                await self.handle_setup_state()
            elif self.current_state == NegotiationState.COLLECTING_PROPOSALS:
                await self.handle_collecting_state()
            elif self.current_state == NegotiationState.EVALUATING_PROPOSALS:
                await self.handle_evaluating_state()
            elif self.current_state == NegotiationState.FINISHED:
                await self.on_end()
            
            await asyncio.sleep(0.1)

        except Exception as e:
            self.profesor.log.error(f"Error in NegotiationState: {str(e)}")
    
    async def on_end(self):
        """Safe behavior cleanup"""
        try:
            self.profesor.mark_negotiation_done()
        except Exception as e:
            self.profesor.log.error(f"Error in negotiation cleanup: {str(e)}")
    
    async def handle_setup_state(self):
        """Handle the SETUP state"""
        if not self.profesor.can_use_more_subjects():
            self.current_state = NegotiationState.FINISHED
            await self.finish_negotiations()
            return

        current_subject = self.profesor.get_current_subject()
        if current_subject:
            self.bloques_pendientes = current_subject.get_horas()
            self.assignation_data.clear()
            self.negotiation_start_time = datetime.now()

            self.profesor.log.info(
                f"Starting assignment for {current_subject.get_nombre()} "
                f"(Code: {current_subject.get_codigo_asignatura()}) - "
                f"Required hours: {current_subject.get_horas()}"
            )

            await self.send_proposal_requests()
            self.proposal_timeout = datetime.now() + timedelta(seconds=self.TIMEOUT_PROPUESTA)
            self.current_state = NegotiationState.COLLECTING_PROPOSALS
            self.proposal_received = False
        else:
            self.current_state = NegotiationState.FINISHED

    async def handle_collecting_state(self):
        """Handle the COLLECTING_PROPOSALS state"""
        if self.proposal_received and not self.propuestas.empty():
            self.current_state = NegotiationState.EVALUATING_PROPOSALS
            return

        if datetime.now() > self.proposal_timeout:
            if not self.propuestas.empty():
                self.current_state = NegotiationState.EVALUATING_PROPOSALS
            else:
                await self.handle_no_proposals()

    async def handle_no_proposals(self):
        """Handle the case when no proposals are received"""
        self.retry_count += 1
        if self.retry_count >= self.MAX_RETRIES:
            if self.bloques_pendientes == self.profesor.get_current_subject().get_horas():
                # If no blocks assigned yet for this subject, move to next subject
                await self.profesor.move_to_next_subject()
            else:
                # If some blocks assigned, try different room
                self.assignation_data.set_sala_asignada(None)
            self.retry_count = 0
            self.current_state = NegotiationState.SETUP
        else:
            # Add exponential backoff
            backoff_time = 2 ** self.retry_count
            self.proposal_timeout = datetime.now() + timedelta(seconds=self.TIMEOUT_PROPUESTA + backoff_time)
            await self.send_proposal_requests()

    async def handle_proposal_failure(self):
        """Handle proposal failure with retry logic"""
        self.retry_count += 1
        if self.retry_count >= self.MAX_RETRIES:
            if self.assignation_data.has_sala_asignada():
                # Try different room if current one isn't working
                self.assignation_data.set_sala_asignada(None)
            else:
                # If we've tried different rooms without success, move on
                await self.profesor.move_to_next_subject()
            self.retry_count = 0
            self.current_state = NegotiationState.SETUP
        else:
            self.current_state = NegotiationState.COLLECTING_PROPOSALS
            backoff_time = 2 ** self.retry_count
            self.proposal_timeout = datetime.now() + timedelta(seconds=self.TIMEOUT_PROPUESTA + backoff_time)
            await self.send_proposal_requests()

    async def handle_evaluating_state(self):
        """Handle the EVALUATING_PROPOSALS state"""
        current_batch_proposals = []
        while not self.propuestas.empty():
            bp = await self.propuestas.get()
            if bp:
                current_batch_proposals.append(bp)

        valid_proposals = await self.constraint_evaluator.filter_and_sort_proposals(current_batch_proposals)

        if valid_proposals and await self.try_assign_batch_proposals(valid_proposals):
            self.retry_count = 0
            if self.bloques_pendientes == 0:
                await self.profesor.move_to_next_subject()
                self.current_state = NegotiationState.SETUP
            else:
                await self.send_proposal_requests()
                self.proposal_timeout = datetime.now() + timedelta(seconds=self.TIMEOUT_PROPUESTA)
                self.current_state = NegotiationState.COLLECTING_PROPOSALS
        else:
            await self.handle_proposal_failure()

    async def send_proposal_requests(self):
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
                
                await self.send(msg)  # Using behaviour's send method
                self.profesor.log.debug(f"Sent CFP to filtered room {room.jid}")

            self.profesor.log.info(f"Sent CFPs to {len(filtered_rooms)} rooms out of {len(rooms)} total rooms")

        except Exception as e:
            self.profesor.log.error(f"Error sending proposal requests: {str(e)}")
            
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

    async def send_batch_assignment(
        self,
        requests: List[AssignmentRequest],
        original_msg: Message
    ) -> bool:
        """Send batch assignment request and wait for confirmation"""
        if self.bloques_pendientes - len(requests) < 0:
            self.profesor.log.warning("Assignment would exceed required hours")
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
                        await self.profesor.update_schedule_info(
                            dia=assignment.get_day(),
                            sala=assignment.get_classroom_code(),
                            bloque=assignment.get_block(),
                            nombre_asignatura=self.profesor.get_current_subject().get_nombre(),
                            satisfaccion=assignment.get_satisfaction()
                        )

                        self.bloques_pendientes -= 1
                        self.assignation_data.assign(
                            assignment.get_day(),
                            assignment.get_classroom_code(),
                            assignment.get_block()
                        )

                    return True

                await asyncio.sleep(0.05)

        except Exception as e:
            self.profesor.log.error(f"Error in send_batch_assignment: {str(e)}")
            
        return False
    
    def is_valid_confirm(self, confirm : Message, og_sender : JID, conv_id : str) -> bool:
        return confirm.get_metadata("performative") == FIPAPerformatives.INFORM and\
        confirm.sender == og_sender and confirm.get_metadata("conversation-id") == conv_id

    @staticmethod
    def sanitize_subject_name(name: str) -> str:
        """Sanitize subject name removing special characters"""
        return ''.join(c for c in name if c.isalnum())

    async def finish_negotiations(self):
        """Handle finished state and cleanup"""
        try:
            # Record completion time
            total_time = (datetime.now() - self.negotiation_start_time).total_seconds() * 1000
            self.profesor.log.info(
                f"Professor {self.profesor.nombre} completed all negotiations in {total_time} ms"
            )
            
            # Log individual subject times 
            for subject, time in self.subject_negotiation_times.items():
                self.profesor.log.info(f"Subject {subject} negotiation took {time} ms")

            # Notify next professor first
            await self.notify_next_professor()
            
            # Kill this behavior
            self.kill()
                
            # Start cleanup with small delay to allow next prof to start
            await asyncio.sleep(0.5)
            await self.profesor.cleanup()
            
        except Exception as e:
            self.profesor.log.error(f"Error in finish_negotiations: {str(e)}")
            
    async def notify_proposal_received(self):
        """Notify state behaviour that a proposal has been received"""
        self.proposal_received = True
        self.profesor.log.debug("Proposal received - notifying state behaviour")
            
    async def notify_next_professor(self):
        try:
            next_orden = self.profesor.orden + 1
            
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