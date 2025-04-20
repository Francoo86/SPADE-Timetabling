from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from typing import Dict, List
import json
import asyncio

from objects.asignation_data import AsignacionSala
from objects.helper.batch_proposals import ClassroomAvailability
from objects.helper.batch_requests import BatchAssignmentRequest
from objects.helper.confirmed_assignments import BatchAssignmentConfirmation, ConfirmedAssignment

from fipa.acl_message import FIPAPerformatives
import jsonpickle

from performance.rtt_stats import RTTLogger
from sys import getsizeof

class ResponderSolicitudesBehaviour(CyclicBehaviour):
    """Enhanced room responder behaviour to work with FSM professors"""
    def __init__(self):
        super().__init__()
        self.rtt_logger = None
        self.rtt_initialized = False
        
    async def on_start(self):
        """Initialize RTT logger on behaviour start"""
        if self.rtt_initialized:
            return
        
        self.rtt_logger = RTTLogger(str(self.agent.jid), self.agent.scenario)
        self.rtt_initialized = True
        await self.rtt_logger.start()

    async def run(self):
        """Main behaviour loop with improved message handling"""
        try:
            # Wait for a message with short timeout for responsiveness
            msg = await self.receive(timeout=0.1)
            if not msg:
                await asyncio.sleep(0.1)
                return

            performative = msg.get_metadata("performative")
            # conversation_id = msg.get_metadata("conversation-id")

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
                
                self.rtt_logger.record_message_received(
                    conversation_id=msg.get_metadata("rtt-id"),
                    performative=FIPAPerformatives.CFP,
                    sender=str(msg.sender),
                    ontology="classroom-availability",
                    message_size=getsizeof(msg.body)
                )
                
                if available_blocks:
                    availability = ClassroomAvailability(
                        codigo=self.agent.codigo,
                        campus=self.agent.campus,
                        capacidad=self.agent.capacidad,
                        available_blocks=available_blocks
                    )

                    reply = self.__create_reply(msg, FIPAPerformatives.PROPOSE)
                    reply.body = jsonpickle.encode(availability)
                    
                    self.rtt_logger.record_message_sent(
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
                    
                    self.rtt_logger.record_message_sent(
                        conversation_id=msg.get_metadata("rtt-id"),
                        performative=FIPAPerformatives.REFUSE,
                        sender=str(msg.sender),
                        ontology="classroom-availability",
                        message_size=getsizeof(reply.body)
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
            for block_idx, assignment in enumerate(assignments):
                if assignment is None:
                    free_blocks.append(block_idx + 1)
            if free_blocks:
                available_blocks[day.name] = free_blocks
        return available_blocks


    async def confirm_assignment(self, msg: Message):
        """Handle assignment confirmation with improved verification"""
        try:
            # Parse batch assignment request
            request_data : BatchAssignmentRequest = jsonpickle.decode(msg.body)
            assignments = []
            
            # Process assignments with validation
            async with asyncio.timeout(1.0):
                for assignment in request_data.get_assignments():
                    if assignment.classroom_code != self.agent.codigo:
                        self.agent.log.debug(f"Skipping request for different room: {assignment.classroom_code}")
                        continue

                    day = assignment.day
                    block = assignment.block - 1
                    subject_name = assignment.subject_name
                    satisfaction = assignment.satisfaction

                    # Verify block availability
                    if block < 0 or block >= len(self.agent.horario_ocupado[day]):
                        self.agent.log.warning(f"Invalid block requested: {block + 1}")
                        continue

                    if self.agent.horario_ocupado[day][block] is not None:
                        self.agent.log.warning(f"Block {block + 1} already assigned")
                        continue

                    # Create and store assignment
                    new_assignment = AsignacionSala(
                        subject_name,
                        satisfaction,
                        float(assignment.vacancy) / self.agent.capacidad
                    )
                    
                    self.agent.horario_ocupado[day][block] = new_assignment
                    
                    assignments.append(ConfirmedAssignment(
                        day,
                        block + 1,
                        self.agent.codigo,
                        satisfaction
                    ))

                # Send confirmation for successful assignments
                if assignments:
                    confirmation = BatchAssignmentConfirmation(assignments)
                    reply = msg.make_reply()
                    reply.set_metadata("performative", FIPAPerformatives.INFORM)
                    reply.set_metadata("ontology", "room-assignment")
                    reply.set_metadata("conversation-id", msg.get_metadata("conversation-id"))
                    reply.body = jsonpickle.encode(confirmation)
                    
                    # rtt_id = msg.get_metadata("rtt-id")
                    # await self.rtt_logger.end_request(
                    #     rtt_id,
                    #     response_performative=FIPAPerformatives.INFORM,  # Performative de respuesta
                    #     message_size=getsizeof(reply.body),
                    #     success=True,
                    #     ontology="room-assignment"
                    # )
            
                    await self.send(reply)
                    
                    asyncio.create_task(self.update_schedule_storage())
                    
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