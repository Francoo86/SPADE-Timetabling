from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from datetime import datetime, timedelta
import asyncio
from typing import Dict, List, Optional
from collections import defaultdict
import json
from queue import Queue

from objects.static.agent_enums import NegotiationState, Day, TipoContrato
from objects.helper.batch_proposals import BatchProposal, BlockProposal
from objects.helper.confirmed_assignments import BatchAssignmentConfirmation
from objects.helper.batch_requests import AssignmentRequest, BatchAssignmentRequest
from objects.asignation_data import AssignationData, Asignatura
from evaluators.timetabling_evaluator import TimetablingEvaluator
from objects.knowledge_base import AgentKnowledgeBase
# from agents.profesor_redux import AgenteProfesor
# import dataclass
from dataclasses import dataclass

@dataclass
class BatchProposalScore:
    """Helper class to store proposal with its score"""
    proposal: BatchProposal
    score: int

class NegotiationStateBehaviour(CyclicBehaviour):
    MEETING_ROOM_THRESHOLD = 10
    TIMEOUT_PROPUESTA = 1
    MAX_RETRIES = 3

    def __init__(self, profesor, batch_proposals : asyncio.Queue):
        """Initialize the negotiation state behaviour."""
        super().__init__()
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

    async def handle_setup_state(self):
        """Handle the SETUP state"""
        if not self.profesor.can_use_more_subjects():
            self.current_state = NegotiationState.FINISHED
            total_time = (datetime.now() - self.negotiation_start_time).total_seconds() * 1000
            self.profesor.log.info(f"Professor {self.profesor.nombre} completed all negotiations in {total_time} ms")
            
            for subject, time in self.subject_negotiation_times.items():
                self.profesor.log.info(f"Subject {subject} negotiation took {time} ms")
            
            await self.profesor.finalizar_negociaciones()
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
                self.profesor.move_to_next_subject()
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
                self.profesor.move_to_next_subject()
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

        valid_proposals = await self.filter_and_sort_proposals(current_batch_proposals)

        if valid_proposals and await self.try_assign_batch_proposals(valid_proposals):
            self.retry_count = 0
            if self.bloques_pendientes == 0:
                self.profesor.move_to_next_subject()
                self.current_state = NegotiationState.SETUP
            else:
                await self.send_proposal_requests()
                self.proposal_timeout = datetime.now() + timedelta(seconds=self.TIMEOUT_PROPUESTA)
                self.current_state = NegotiationState.COLLECTING_PROPOSALS
        else:
            await self.handle_proposal_failure()

    async def filter_and_sort_proposals(self, proposals: List[BatchProposal]) -> List[BatchProposal]:
        """Filter and sort batch proposals based on multiple criteria"""
        if not proposals:
            return []

        current_subject = self.profesor.get_current_subject()
        current_campus = current_subject.get_campus()
        current_nivel = current_subject.get_nivel()
        current_asignatura_nombre = current_subject.get_nombre()
        needs_meeting_room = current_subject.get_vacantes() < self.MEETING_ROOM_THRESHOLD

        # Get current schedule info
        current_schedule = self.profesor.get_blocks_by_subject(current_asignatura_nombre)
        room_usage = {}
        blocks_per_day = {}
        most_used_room = await self.calculate_most_used_room(current_schedule, blocks_per_day, room_usage)

        scored_proposals = []

        # Process each proposal
        for proposal in proposals:
            if not await self.is_valid_proposal(proposal, current_subject, current_nivel, 
                                            needs_meeting_room, current_asignatura_nombre):
                continue

            total_score = await self.calculate_total_score(
                proposal, current_subject, current_campus, current_nivel,
                needs_meeting_room, blocks_per_day, most_used_room, room_usage,
                current_schedule
            )

            if total_score > 0:
                scored_proposals.append(BatchProposalScore(proposal, total_score))

        if not scored_proposals:
            return []

        # Sort by final scores (descending)
        scored_proposals.sort(key=lambda ps: ps.score, reverse=True)
        return [ps.proposal for ps in scored_proposals]

    async def calculate_total_score(
        self,
        proposal: BatchProposal,
        current_subject: Asignatura,
        current_campus: str,
        current_nivel: int,
        needs_meeting_room: bool,
        blocks_per_day: Dict[Day, int],
        most_used_room: Optional[str],
        room_usage: Dict[str, int],
        current_schedule: Dict[Day, List[int]]
    ) -> int:
        """Calculate total score for a proposal considering all factors"""
        # Calculate base scores
        await self.calculate_satisfaction_scores(
            proposal, current_subject, current_campus,
            current_nivel, current_schedule
        )

        total_score = await self.calculate_proposal_score(
            proposal, current_campus, current_nivel, current_subject
        )

        # Apply room type scoring
        total_score = await self.apply_meeting_room_score(
            total_score, proposal, needs_meeting_room, current_subject
        )

        # Apply day-based scoring
        total_score = await self.apply_day_based_scoring(
            total_score, proposal, current_campus,
            blocks_per_day, most_used_room, room_usage
        )

        # Ensure minimum viable score
        return max(total_score, 1)

    async def apply_meeting_room_score(
        self,
        total_score: int,
        proposal: BatchProposal,
        needs_meeting_room: bool,
        current_subject: Asignatura
    ) -> int:
        """Apply scoring adjustments for meeting room requirements"""
        is_meeting_room = proposal.get_capacity() < self.MEETING_ROOM_THRESHOLD

        if needs_meeting_room:
            if is_meeting_room:
                # Perfect match - high bonus
                total_score += 15000

                # Additional bonus for optimal size match
                size_diff = abs(proposal.get_capacity() - current_subject.get_vacantes())
                if size_diff <= 2:
                    total_score += 5000
            else:
                # Using regular room for small class - apply penalty but don't reject
                oversize = proposal.get_capacity() - current_subject.get_vacantes()
                total_score -= oversize * 500  # Progressive penalty for oversized rooms

        return total_score

    async def apply_day_based_scoring(
        self,
        total_score: int,
        proposal: BatchProposal,
        current_campus: str,
        blocks_per_day: Dict[Day, int],
        most_used_room: Optional[str],
        room_usage: Dict[str, int]
    ) -> int:
        """Apply scoring adjustments based on daily schedule patterns"""
        for day, block_proposals in proposal.get_day_proposals().items():
            day_usage = blocks_per_day.get(day, 0)

            # Day-based scoring
            total_score -= day_usage * 6000  # Penalty for same-day assignments

            if day not in blocks_per_day:
                total_score += 8000  # Bonus for new days

            # Room consistency scoring
            if proposal.get_room_code() == most_used_room:
                total_score += 7000

            # Apply campus and block penalties
            total_score = await self.apply_campus_and_block_penalties(
                total_score, proposal, day, current_campus,
                day_usage, room_usage
            )

        return total_score

    async def apply_campus_and_block_penalties(
        self,
        total_score: int,
        proposal: BatchProposal,
        day: Day,
        current_campus: str,
        day_usage: int,
        room_usage: Dict[str, int]
    ) -> int:
        """Apply penalties for campus transitions and block assignments"""
        if not proposal.get_room_code().startswith(current_campus[0:1]):
            total_score -= 10000

            for block in proposal.get_day_proposals()[day]:
                prev_block = self.profesor.get_bloque_info(day, block.get_block() - 1)
                next_block = self.profesor.get_bloque_info(day, block.get_block() + 1)

                if ((prev_block and prev_block.get_campus() != current_campus) or
                    (next_block and next_block.get_campus() != current_campus)):
                    total_score -= 8000

        room_count = room_usage.get(proposal.get_room_code(), 0)
        total_score -= room_count * 1500

        if day_usage >= 2:
            total_score -= 6000

        return total_score

    async def calculate_proposal_score(
        self,
        proposal: BatchProposal,
        current_campus: str,
        nivel: int,
        subject: Asignatura
    ) -> int:
        """Calculate base proposal score"""
        score = 0

        # Campus consistency (high priority)
        if proposal.get_campus() == current_campus:
            score += 10000
        else:
            score -= 10000

        # Time preference based on year
        is_odd_year = nivel % 2 == 1
        for day, blocks in proposal.get_day_proposals().items():
            for block in blocks:
                if is_odd_year:
                    if block.get_block() <= 4:
                        score += 3000
                else:
                    if block.get_block() >= 5:
                        score += 3000

            if self.profesor.get_tipo_contrato() != TipoContrato.JORNADA_PARCIAL:
                if len(blocks) > 1:
                    sorted_blocks = sorted(blocks, key=lambda b: b.get_block())
                    for i in range(1, len(sorted_blocks)):
                        gap = sorted_blocks[i].get_block() - sorted_blocks[i-1].get_block()
                        if gap <= 2:  # Consecutive blocks or one block gap
                            score += 5000  # High bonus for compact schedules
                        else:
                            score -= 8000  # Penalty for large gaps

        # Base satisfaction score
        score += proposal.get_satisfaction_score() * 10

        # Capacity score - prefer rooms that closely match needed capacity
        capacity_diff = abs(proposal.get_capacity() - subject.get_vacantes())
        score -= capacity_diff * 100

        return score
        
            
    async def notify_proposal_received(self):
        """Notify the behaviour that a proposal was received"""
        self.proposal_received = True

    async def calculate_most_used_room(
        self,
        current_schedule: Dict[Day, List[int]],
        blocks_per_day: Dict[Day, int],
        room_usage: Dict[str, int]
    ) -> Optional[str]:
        """Calculate the most frequently used room"""
        most_used_room = None

        for day, blocks in current_schedule.items():
            blocks_per_day[day] = len(blocks)

            for block in blocks:
                info = self.profesor.get_bloque_info(day, block)
                if info:
                    room = info.get_campus()
                    count = room_usage.get(room, 0) + 1
                    room_usage[room] = count
                    if most_used_room is None or count > room_usage.get(most_used_room, 0):
                        most_used_room = room

        return most_used_room

    async def validate_consecutive_gaps(self, dia: Day, proposed_blocks: List[BlockProposal]) -> bool:
        """Validate consecutive gaps in schedule"""
        tipo_contrato = self.profesor.get_tipo_contrato()
        
        if tipo_contrato == TipoContrato.JORNADA_PARCIAL:
            return True

        bloques_asignados = self.profesor.get_blocks_by_day(dia)
        all_blocks = []

        # Add existing blocks
        for blocks in bloques_asignados.values():
            all_blocks.extend(blocks)

        # Add proposed blocks
        all_blocks.extend([block.get_block() for block in proposed_blocks])

        # Sort blocks
        all_blocks.sort()

        # Check gaps
        consecutive_gaps = 0
        for i in range(1, len(all_blocks)):
            gap = all_blocks[i] - all_blocks[i-1] - 1
            if gap > 0:
                consecutive_gaps += gap
                if consecutive_gaps > 1:
                    return False
            else:
                consecutive_gaps = 0

        return True

    async def validate_gaps_for_proposal(self, proposal: BatchProposal) -> bool:
        """Validate gaps for all days in a proposal"""
        for day, block_proposals in proposal.get_day_proposals().items():
            if not await self.validate_consecutive_gaps(day, block_proposals):
                return False
        return True

    async def is_valid_proposal(
        self,
        proposal: BatchProposal,
        current_subject: Asignatura,
        current_nivel: int,
        needs_meeting_room: bool,
        current_asignatura_nombre: str
    ) -> bool:
        """Check if a proposal is valid based on various constraints"""
        is_meeting_room = proposal.get_capacity() < self.MEETING_ROOM_THRESHOLD

        # Meeting room logic
        if needs_meeting_room:
            if not is_meeting_room and proposal.get_capacity() > current_subject.get_vacantes() * 4:
                return False
        elif is_meeting_room:
            return False

        return (await self.is_valid_proposal_fast(
            proposal, current_subject,
            current_nivel % 2 == 1, current_asignatura_nombre) and
            await self.validate_gaps_for_proposal(proposal))

    async def is_valid_proposal_fast(
        self,
        proposal: BatchProposal,
        asignatura: Asignatura,
        is_odd_year: bool,
        asignatura_nombre: str
    ) -> bool:
        """Fast validation of proposal basics"""
        if not await self.check_campus_constraints(proposal, asignatura.get_campus()):
            return False

        for day, blocks in proposal.get_day_proposals().items():
            asignaturas_en_dia = self.profesor.get_blocks_by_day(day)
            existing_blocks = asignaturas_en_dia.get(asignatura_nombre, [])

            if existing_blocks and len(existing_blocks) >= 2:
                continue

            proposed_blocks = [block.get_block() for block in blocks]

            if asignatura.get_actividad() not in ['LABORATORIO', 'TALLER']:
                sorted_blocks = sorted(proposed_blocks + (existing_blocks or []))
                continuous_count = 1
                for i in range(1, len(sorted_blocks)):
                    if sorted_blocks[i] == sorted_blocks[i-1] + 1:
                        continuous_count += 1
                        if continuous_count > 2:
                            continue

            for block in blocks:
                bloque = block.get_block()
                
                if not (1 <= bloque <= 9):  # MAX_BLOQUE_DIURNO = 9
                    continue

                if bloque == 9 and self.bloques_pendientes % 2 == 0:
                    continue

                if is_odd_year:
                    if bloque > 4 and bloque != 9:
                        continue
                elif bloque < 5 and proposal.get_satisfaction_score() < 8:
                    continue

                return True

        return False

    async def calculate_satisfaction_scores(
        self,
        proposal: BatchProposal,
        current_subject: Asignatura,
        current_campus: str,
        current_nivel: int,
        current_schedule: Dict[Day, List[int]]
    ):
        """Calculate satisfaction scores for a proposal"""
        for day_proposals in proposal.get_day_proposals().values():
            for block_proposal in day_proposals:
                satisfaction = TimetablingEvaluator.calculate_satisfaction(
                    proposal.get_capacity(),
                    current_subject.get_vacantes(),
                    current_nivel,
                    proposal.get_campus(),
                    current_campus,
                    block_proposal.get_block(),
                    current_schedule,
                    self.profesor.get_tipo_contrato(),
                    current_subject.get_actividad()
                )
                proposal.set_satisfaction_score(satisfaction)

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

            # Send CFP to each room
            for room in rooms:
                msg = Message(
                    to=str(room.jid)  # Set the recipient JID
                )
                msg.set_metadata("protocol", "fipa-contract-net")
                msg.set_metadata("performative", "cfp")
                msg.set_metadata("conversation-id", f"neg-{self.profesor.nombre}-{self.bloques_pendientes}")
                msg.body = json.dumps(solicitud_info)
                
                await self.send(msg)  # Using behaviour's send method
                self.profesor.log.debug(f"Sent CFP to room {room.jid}")

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
        
        MAX_RETRIES = 3
        retry_count = 0

        while retry_count < MAX_RETRIES:
            try:
                # Create batch request message
                msg = Message()
                msg.to = str(original_msg.sender)
                msg.set_metadata("performative", "accept-proposal")
                msg.set_metadata("ontology", "room-assignment")
                msg.set_metadata("conversation-id", original_msg.get_metadata("conversation-id"))
                msg.set_metadata("protocol", "fipa-contract-net")
                
                msg.body = json.dumps(BatchAssignmentRequest(requests).to_dict())

                # Send message and wait for confirmation
                await self.send(msg)
                
                # Wait for confirmation with timeout
                start_time = datetime.now()
                timeout = timedelta(seconds=1)

                while datetime.now() - start_time < timeout:
                    confirmation_msg = await self.receive(timeout=0.1)
                    if confirmation_msg and confirmation_msg.get_metadata("performative") == "inform":
                        confirmation_data = json.loads(confirmation_msg.body)
                        confirmation = BatchAssignmentConfirmation.from_dict(confirmation_data)

                        # Process confirmed assignments
                        for assignment in confirmation.get_confirmed_assignments():
                            await self.profesor.update_schedule_info(
                                day=assignment.get_day(),
                                classroom_code=assignment.get_classroom_code(),
                                block=assignment.get_block(),
                                subject_name=self.profesor.get_current_subject().get_nombre(),
                                satisfaction=assignment.get_satisfaction()
                            )

                            self.bloques_pendientes -= 1
                            self.assignation_data.assign(
                                assignment.get_day(),
                                assignment.get_classroom_code(),
                                assignment.get_block()
                            )

                        return True

                    await asyncio.sleep(0.05)
                    
                retry_count += 1

                # return False

            except Exception as e:
                self.profesor.log.error(f"Error in send_batch_assignment: {str(e)}")
                # return False
                retry_count += 1
            
        return False

    @staticmethod
    def sanitize_subject_name(name: str) -> str:
        """Sanitize subject name removing special characters"""
        return ''.join(c for c in name if c.isalnum())

    async def check_campus_constraints(self, proposal: BatchProposal, current_campus: str) -> bool:
        """Check if campus constraints are satisfied"""
        proposed_campus = self.get_campus_sala(proposal.get_room_code())

        # If same campus, always valid
        if proposed_campus == current_campus:
            return True

        # Check transitions for each day in the proposal
        for day, block_proposals in proposal.get_day_proposals().items():
            # Check if there's already a campus transition this day
            if await self.has_existing_transition_in_day(day):
                return False

            # Validate buffer blocks for each proposed block
            for block_proposal in block_proposals:
                if not await self.validate_transition_buffer(day, block_proposal.get_block(), proposal.get_room_code()):
                    return False

        return True

    async def validate_transition_buffer(self, day: Day, block: int, codigo_sala: str) -> bool:
        """Validate transition buffer between different campuses"""
        proposed_campus = self.get_campus_sala(codigo_sala)

        prev_block = self.profesor.get_bloque_info(day, block - 1)
        next_block = self.profesor.get_bloque_info(day, block + 1)

        # Check if there's at least one empty block between different campuses
        if prev_block and prev_block.get_campus() != proposed_campus:
            return self.profesor.is_block_available(day, block - 1)

        if next_block and next_block.get_campus() != proposed_campus:
            return self.profesor.is_block_available(day, block + 1)

        return True

    async def has_existing_transition_in_day(self, day: Day) -> bool:
        """Check if there are existing campus transitions in a day"""
        day_classes = self.profesor.get_blocks_by_day(day)
        if not day_classes:
            return False

        blocks = []
        for asignatura_blocks in day_classes.values():
            for bloque in asignatura_blocks:
                info = self.profesor.get_bloque_info(day, bloque)
                if info:
                    blocks.append(info)

        blocks.sort(key=lambda x: x.get_bloque())

        previous_campus = None
        for block in blocks:
            if previous_campus and previous_campus != block.get_campus():
                return True
            previous_campus = block.get_campus()

        return False

    @staticmethod
    def get_campus_sala(codigo_sala: str) -> str:
        """Get campus name from classroom code"""
        return "Kaufmann" if codigo_sala.startswith("KAU") else "Playa Brava"
