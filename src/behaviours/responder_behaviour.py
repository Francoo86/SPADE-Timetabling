from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from typing import Dict, List
import json
import asyncio

from ..objects.asignation_data import AsignacionSala
from ..objects.helper.batch_proposals import ClassroomAvailability
from ..objects.helper.batch_requests import BatchAssignmentRequest
from ..objects.helper.confirmed_assignments import BatchAssignmentConfirmation, ConfirmedAssignment

from ..fipa.acl_message import FIPAPerformatives
import jsonpickle

from ..performance.rtt_stats import RTTLogger
from msgspec import json as msgspec_json

class ResponderSolicitudesBehaviour(CyclicBehaviour):
    MAX_BLOQUE_DIURNO = 9
    
    """Enhanced room responder behaviour to work with FSM professors"""
    def __init__(self):
        super().__init__()
        self.rtt_logger : 'RTTLogger' = None
        self.rtt_initialized = False
        
    async def on_start(self):
        """Initialize RTT logger on behaviour start"""
        self.rtt_logger = self.agent.rtt_logger

    async def run(self):
        """Main behaviour loop with improved message handling"""
        try:
            # Wait for a message with short timeout for responsiveness
            msg = await self.receive(timeout=0.5)
            if not msg:
                # await asyncio.sleep(0.1)
                return

            performative = msg.get_metadata("performative")

            if performative == FIPAPerformatives.CFP:
                await self.process_request(msg)
            elif performative == FIPAPerformatives.ACCEPT_PROPOSAL:
                await self.confirm_assignment(msg)

        except Exception as e:
            self.agent.log.error(f"Error in room responder: {str(e)}")
            
    def __create_reply(self, msg: Message, performative : str):
        reply = msg.make_reply()
        reply.set_metadata("performative", performative)
        reply.set_metadata("conversation-id", msg.get_metadata("conversation-id"))
        reply.set_metadata("ontology", "classroom-availability")
        reply.set_metadata("rtt-id", msg.get_metadata("rtt-id"))
        return reply

    async def process_request(self, msg: Message):
        """Process incoming room requests with improved error handling"""
        try:
            # Parse request data
            request_data = json.loads(msg.body)
            subject_name = self.agent.sanitize_subject_name(request_data["nombre"])
            vacancies = request_data["vacantes"]
            
            # Check availability with timeout protection
            async with asyncio.timeout(1.0):
                available_blocks = self.get_available_blocks(vacancies)
                
                #await self.rtt_logger.record_message_received(
                #    agent_name=self.agent.name,
                #    conversation_id=msg.get_metadata("rtt-id"),
                #    performative=FIPAPerformatives.CFP,
                #    sender=str(msg.sender),
                #    ontology="classroom-availability",
                #    message_size=len(msg.body)
                #)
                
                if available_blocks:
                    availability = ClassroomAvailability(
                        codigo=self.agent.codigo,
                        campus=self.agent.campus,
                        capacidad=self.agent.capacidad,
                        available_blocks=available_blocks
                    )

                    reply = self.__create_reply(msg, FIPAPerformatives.PROPOSE)
                    reply.body = msgspec_json.encode(availability).decode('utf-8')

                    await self.rtt_logger.record_message_sent(
                        agent_name=self.agent.name,
                        conversation_id=msg.get_metadata("rtt-id"),
                        performative=FIPAPerformatives.PROPOSE,
                        receiver=str(msg.sender),
                        ontology="classroom-availability",
                    )
                    
                    await self.send(reply)
                    self.agent.log.debug(f"Sent proposal to {msg.sender} for {subject_name}")
                else:
                    reply = self.__create_reply(msg, FIPAPerformatives.REFUSE)
                    reply.body = "No blocks available"
                    
                    await self.rtt_logger.record_message_sent(
                        agent_name=self.agent.name,
                        conversation_id=msg.get_metadata("rtt-id"),
                        performative=FIPAPerformatives.REFUSE,
                        receiver=str(msg.sender),
                        ontology="classroom-availability",
                    )
                    
                    await self.send(reply)
                    self.agent.log.debug(f"Sent refuse to {msg.sender} - no blocks available")
                    
        except asyncio.TimeoutError:
            self.agent.log.error(f"Timeout processing request from {msg.sender}")
        except Exception as e:
            self.agent.log.error(f"Error processing request: {str(e)}")
    
    def get_available_blocks(self, vacancies: int) -> Dict[str, List[int]]:
        """Get available blocks for each day"""
        available_blocks = {}
        for day, assignments in self.agent.horario_ocupado.items():
            free_blocks = []
            #for block_idx, assignment in enumerate(assignments):
            for block_idx in range(self.MAX_BLOQUE_DIURNO):
                if block_idx < len(assignments) and assignments[block_idx] is None:
                # if assignment is None:
                    free_blocks.append(block_idx + 1)
            if free_blocks:
                available_blocks[day.name] = free_blocks
        return available_blocks


    async def confirm_assignment(self, msg: Message):
        """Handle assignment confirmation with improved verification"""
        try:
            request_data : BatchAssignmentRequest = msgspec_json.decode(msg.body, type=BatchAssignmentRequest)
            confirmed_assignments = []
            
            async with asyncio.timeout(1.0):
                for assignment in request_data.get_assignments():
                    if assignment.classroom_code != self.agent.codigo:
                        self.agent.log.debug(f"[DEBUG] Skipping request for different room: {assignment.classroom_code}")
                        continue

                    block = assignment.block - 1
                    day = assignment.day
                    assignments_for_day = self.agent.horario_ocupado.get(day)

                    self.agent.log.debug(f"[DEBUG] Processing request for {assignment.subject_name} " +
                                        f"Day: {day} Block: {assignment.block}")

                    if (assignments_for_day is not None and 
                        block >= 0 and 
                        block < len(assignments_for_day) and
                        assignments_for_day[block] is None):

                        capacity_fraction = float(assignment.vacancy) / self.agent.capacidad
                        new_assignment = AsignacionSala(
                            assignment.subject_name,
                            assignment.satisfaction,
                            capacity_fraction,
                            assignment.prof_name
                        )
                        
                        assignments_for_day[block] = new_assignment
                        
                        confirmed_assignments.append(ConfirmedAssignment(
                            day,
                            assignment.block,
                            self.agent.codigo,
                            assignment.satisfaction
                        ))

                        self.agent.log.debug(f"[DEBUG] Successfully assigned {assignment.subject_name} " +
                                        f"to block {assignment.block} on {day}")
                    else:
                        self.agent.log.debug(f"[DEBUG] Could not assign - assignments_for_day is None? {assignments_for_day is None} " +
                                        f"valid block? {(block >= 0 and block < (len(assignments_for_day) if assignments_for_day is not None else 0))} " +
                                        f"block empty? {(assignments_for_day is not None and block >= 0 and block < len(assignments_for_day) and assignments_for_day[block] is None)}")

                if confirmed_assignments:
                    confirmation = BatchAssignmentConfirmation(confirmed_assignments)
                    reply = msg.make_reply()
                    reply.set_metadata("performative", FIPAPerformatives.INFORM)
                    reply.set_metadata("ontology", "room-assignment")
                    reply.set_metadata("conversation-id", msg.get_metadata("conversation-id"))
                    reply.body = msgspec_json.encode(confirmation).decode('utf-8')

                    await self.send(reply)
                    
        except asyncio.TimeoutError:
            self.agent.log.error(f"Timeout confirming assignment from {msg.sender}")
        except Exception as e:
            self.agent.log.error(f"Error confirming assignment: {str(e)}")

    async def update_schedule_storage(self):
        """Update storage with error handling"""
        try:
            schedule_data = {
                "codigo": self.agent.codigo,
                "campus": self.agent.campus,
                "horario": {
                    day.name: [
                        assignment.to_dict() if assignment else None
                        for assignment in assignments
                    ]
                    for day, assignments in self.agent.horario_ocupado.items()
                }
            }
            
            await self.agent.update_schedule_storage(schedule_data)
            
        except Exception as e:
            self.agent.log.error(f"Error updating schedule storage: {str(e)}")