import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from spade.message import Message
from spade.agent import Agent
from aioxmpp import JID
from datetime import datetime

# Import your agent classes and dependencies
from src.agents.profesor_redux import AgenteProfesor
from src.agents.sala_agent import AgenteSala, ResponderSolicitudesBehaviour
from src.objects.asignation_data import Asignatura, AsignacionSala
from src.objects.static.agent_enums import Day, Actividad, TipoContrato
from src.objects.knowledge_base import AgentKnowledgeBase, AgentCapability
from src.behaviours.fsm_negotiation_states import NegotiationFSM, NegotiationStates
from src.fipa.acl_message import FIPAPerformatives
import json
import jsonpickle

class BaseTestCase(unittest.TestCase):
    """Base test case for SPADE agents with common setup and teardown"""
    
    async def asyncSetUp(self):
        """Setup knowledge base and common mocks"""
        # Create mock knowledge base
        self.kb = MagicMock(spec=AgentKnowledgeBase)
        self.kb.register_agent = AsyncMock(return_value=True)
        self.kb.deregister_agent = AsyncMock(return_value=True)
        self.kb.search = AsyncMock(return_value=[])
        self.kb.update_heartbeat = AsyncMock(return_value=True)
        
    async def asyncTearDown(self):
        """Clean up after test"""
        # Clean up any running tasks
        pending = asyncio.all_tasks()
        for task in pending:
            if not task.done() and task != asyncio.current_task():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                
class AgenteSalaTest(BaseTestCase):
    """Tests for the Sala Agent"""
    
    async def asyncSetUp(self):
        """Set up before each test"""
        await super().asyncSetUp()
        
        # Create a sala agent
        self.sala = AgenteSala(
            jid="sala1@localhost", 
            password="password",
            codigo="A101",
            campus="Kaufmann",
            capacidad=30,
            turno=1
        )
        self.sala.set_knowledge_base(self.kb)
        
        # Mock the storage
        self.storage_mock = MagicMock()
        self.storage_mock.update_schedule = AsyncMock()
        self.sala.set_storage(self.storage_mock)
        
        # Initialize schedule
        self.sala.initialize_schedule()
        
        # Access the responder behavior directly
        self.responder = self.sala.responder_behaviour
        # Mock RTT logger
        self.responder.rtt_logger = MagicMock()
        self.responder.rtt_logger.start_request = AsyncMock()
        self.responder.rtt_logger.end_request = AsyncMock()
        self.responder.rtt_initialized = True
        
    async def test_sala_initialization(self):
        """Test that the sala agent initializes correctly"""
        await self.sala.setup()
        # Verify KB registration was called
        self.kb.register_agent.assert_called_once()
        
        # Verify schedule was initialized
        for day in Day:
            self.assertIn(day, self.sala.horario_ocupado)
            self.assertEqual(len(self.sala.horario_ocupado[day]), 9)  # 9 blocks per day
        
    async def test_process_request(self):
        """Test processing a CFP request"""
        # Create a mock message
        cfp_msg = Message(
            to="sala1@localhost",
            sender="profesor1@localhost"
        )
        cfp_msg.set_metadata("performative", FIPAPerformatives.CFP)
        cfp_msg.set_metadata("conversation-id", "test-conversation")
        
        # Create request body
        request_data = {
            "nombre": "Algebra",
            "vacantes": 25,
            "nivel": 3,
            "campus": "Kaufmann",
            "bloques_pendientes": 2,
            "sala_asignada": "",
            "ultimo_dia": "",
            "ultimo_bloque": -1
        }
        cfp_msg.body = json.dumps(request_data)
        
        # Process the request
        await self.responder.process_request(cfp_msg)
        
        # Verify the RTT logger was called
        self.responder.rtt_logger.end_request.assert_called_once()
        
    async def test_confirm_assignment(self):
        """Test confirming an assignment"""
        # Create assignment request
        from objects.helper.batch_requests import AssignmentRequest, BatchAssignmentRequest
        assignment_req = AssignmentRequest(
            day=Day.LUNES,
            block=1,
            subject_name="Algebra",
            satisfaction=8,
            classroom_code="A101",
            vacancy=25
        )
        batch_req = BatchAssignmentRequest([assignment_req])
        
        # Create mock message
        msg = Message(
            to="sala1@localhost",
            sender="profesor1@localhost"
        )
        msg.set_metadata("performative", FIPAPerformatives.ACCEPT_PROPOSAL)
        msg.set_metadata("conversation-id", "test-conversation")
        msg.body = jsonpickle.encode(batch_req)
        
        # Mock the send method
        self.responder.send = AsyncMock()
        
        # Confirm the assignment
        await self.responder.confirm_assignment(msg)
        
        # Verify the slot was assigned
        self.assertIsNotNone(self.sala.horario_ocupado[Day.LUNES][0])
        self.assertEqual(self.sala.horario_ocupado[Day.LUNES][0].nombre_asignatura, "Algebra")
        
        # Verify response was sent
        self.responder.send.assert_called_once()
        
        # Verify storage was updated
        self.storage_mock.update_schedule.assert_called_once()

class AgenteSalaIntegrationTest(BaseTestCase):
    """Integration tests for the Sala Agent"""
    
    async def asyncSetUp(self):
        """Set up before each test"""
        await super().asyncSetUp()
        
        # Create a sala agent
        self.sala = AgenteSala(
            jid="sala1@localhost", 
            password="password",
            codigo="A101",
            campus="Kaufmann",
            capacidad=30,
            turno=1
        )
        self.sala.set_knowledge_base(self.kb)
        
        # Mock the storage
        self.storage_mock = MagicMock()
        self.storage_mock.update_schedule = AsyncMock()
        self.sala.set_storage(self.storage_mock)
        
        # Initialize the agent
        await self.sala.setup()
        
        # Access the responder behavior directly
        self.responder = self.sala.responder_behaviour
        # Add mocks to the responder
        self.responder.rtt_logger = MagicMock()
        self.responder.rtt_logger.start_request = AsyncMock()
        self.responder.rtt_logger.end_request = AsyncMock()
        self.responder.rtt_initialized = True
        self.responder.send = AsyncMock()
        self.responder.receive = AsyncMock(return_value=None)
        
    async def test_complete_negotiation_flow(self):
        """Test a complete flow from CFP to confirmation"""
        # 1. Create and process a CFP message
        cfp_msg = Message(
            to="sala1@localhost",
            sender="profesor1@localhost"
        )
        cfp_msg.set_metadata("performative", FIPAPerformatives.CFP)
        cfp_msg.set_metadata("conversation-id", "test-negotiation")
        
        request_data = {
            "nombre": "Algebra",
            "vacantes": 25,
            "nivel": 3,
            "campus": "Kaufmann",
            "bloques_pendientes": 2,
            "sala_asignada": "",
            "ultimo_dia": "",
            "ultimo_bloque": -1
        }
        cfp_msg.body = json.dumps(request_data)
        
        # Setup receive to return our message
        self.responder.receive.return_value = cfp_msg
        
        # Run the behavior once
        await self.responder.run()
        
        # Verify a proposal was sent
        propose_call = self.responder.send.call_args
        self.assertIsNotNone(propose_call)
        propose_msg = propose_call[0][0]
        self.assertEqual(propose_msg.get_metadata("performative"), FIPAPerformatives.PROPOSE)
        
        # 2. Create and process an ACCEPT_PROPOSAL message
        from objects.helper.batch_requests import AssignmentRequest, BatchAssignmentRequest
        assignment_req = AssignmentRequest(
            day=Day.LUNES,
            block=1,
            subject_name="Algebra",
            satisfaction=8,
            classroom_code="A101",
            vacancy=25
        )
        batch_req = BatchAssignmentRequest([assignment_req])
        
        accept_msg = Message(
            to="sala1@localhost",
            sender="profesor1@localhost"
        )
        accept_msg.set_metadata("performative", FIPAPerformatives.ACCEPT_PROPOSAL)
        accept_msg.set_metadata("conversation-id", "test-negotiation")
        accept_msg.body = jsonpickle.encode(batch_req)
        
        # Reset mocks for next message
        self.responder.send.reset_mock()
        self.responder.receive.return_value = accept_msg
        
        # Run the behavior again
        await self.responder.run()
        
        # Verify a confirmation was sent
        confirm_call = self.responder.send.call_args
        self.assertIsNotNone(confirm_call)
        confirm_msg = confirm_call[0][0]
        self.assertEqual(confirm_msg.get_metadata("performative"), FIPAPerformatives.INFORM)
        
        # Verify the schedule was updated
        self.assertIsNotNone(self.sala.horario_ocupado[Day.LUNES][0])
        
        # Verify storage was updated
        self.storage_mock.update_schedule.assert_called_once()

class AgentProfesorTest(BaseTestCase):
    """Tests for the Profesor Agent"""
    
    async def asyncSetUp(self):
        """Set up before each test"""
        await super().asyncSetUp()
        
        # Create test asignaturas
        self.asignaturas = [
            {
                "Nombre": "Algebra",
                "Nivel": 3,
                "Paralelo": "A",
                "Horas": 4,
                "Vacantes": 25,
                "Campus": "Kaufmann",
                "CodigoAsignatura": "MAT101",
                "Actividad": "teo"
            },
            {
                "Nombre": "Programacion",
                "Nivel": 2,
                "Paralelo": "B",
                "Horas": 6,
                "Vacantes": 30,
                "Campus": "Kaufmann",
                "CodigoAsignatura": "INF101",
                "Actividad": "lab"
            }
        ]
        
        # Create a profesor agent
        self.profesor = AgenteProfesor(
            jid="profesor1@localhost",
            password="password",
            nombre="Dr. Smith",
            asignaturas=self.asignaturas,
            orden=1
        )
        self.profesor.set_knowledge_base(self.kb)
        
        # Mock the storage
        self.storage_mock = MagicMock()
        self.storage_mock.update_schedule = AsyncMock()
        self.profesor.set_storage(self.storage_mock)
        
        # Initialize the agent
        self.profesor._initialize_data_structures()
        
        # Create mock negotiation state
        self.fsm_mock = MagicMock(spec=NegotiationFSM)
        self.profesor.negotiation_state_behaviour = self.fsm_mock
        
    async def test_profesor_initialization(self):
        """Test profesor agent initialization"""
        await self.profesor.setup()
        
        # Verify KB registration
        self.kb.register_agent.assert_called_once()
        
        # Verify data structures
        self.assertEqual(len(self.profesor.asignaturas), 2)
        self.assertEqual(self.profesor.asignatura_actual, 0)
        for day in Day:
            self.assertIn(day, self.profesor.horario_ocupado)
            self.assertEqual(len(self.profesor.horario_ocupado[day]), 0)  # Empty set
    
    async def test_get_current_subject(self):
        """Test getting the current subject"""
        current = self.profesor.get_current_subject()
        self.assertIsNotNone(current)
        self.assertEqual(current.get_nombre(), "Algebra")
        self.assertEqual(current.get_codigo_asignatura(), "MAT101")
        self.assertEqual(current.get_horas(), 4)
        
    async def test_move_to_next_subject(self):
        """Test moving to the next subject"""
        # Verify initial state
        self.assertEqual(self.profesor.asignatura_actual, 0)
        current = self.profesor.get_current_subject()
        self.assertEqual(current.get_nombre(), "Algebra")
        
        # Move to next subject
        await self.profesor.move_to_next_subject()
        
        # Verify new state
        self.assertEqual(self.profesor.asignatura_actual, 1)
        current = self.profesor.get_current_subject()
        self.assertEqual(current.get_nombre(), "Programacion")
        
    async def test_update_schedule_info(self):
        """Test updating schedule information"""
        # Add a block to the schedule
        await self.profesor.update_schedule_info(
            dia=Day.LUNES,
            sala="A101",
            bloque=1,
            nombre_asignatura="Algebra",
            satisfaccion=8
        )
        
        # Verify schedule was updated
        self.assertIn(1, self.profesor.horario_ocupado[Day.LUNES])
        
        # Verify storage was updated
        self.storage_mock.update_schedule.assert_called_once()
        
        # Get block info
        bloque_info = self.profesor.get_bloque_info(Day.LUNES, 1)
        self.assertIsNotNone(bloque_info)
        
    async def test_is_block_available(self):
        """Test checking if a block is available"""
        # Initially all blocks should be available
        self.assertTrue(self.profesor.is_block_available(Day.LUNES, 1))
        
        # Add a block to the schedule
        await self.profesor.update_schedule_info(
            dia=Day.LUNES,
            sala="A101",
            bloque=1,
            nombre_asignatura="Algebra",
            satisfaccion=8
        )
        
        # Block should no longer be available
        self.assertFalse(self.profesor.is_block_available(Day.LUNES, 1))
        
        # Other blocks still available
        self.assertTrue(self.profesor.is_block_available(Day.LUNES, 2))
        self.assertTrue(self.profesor.is_block_available(Day.MARTES, 1))

class FSMNegotiationTest(BaseTestCase):
    """Tests for the Negotiation FSM"""
    
    async def asyncSetUp(self):
        """Set up before each test"""
        await super().asyncSetUp()
        
        # Create test asignaturas
        self.asignaturas = [
            {
                "Nombre": "Algebra",
                "Nivel": 3,
                "Paralelo": "A",
                "Horas": 4,
                "Vacantes": 25,
                "Campus": "Kaufmann",
                "CodigoAsignatura": "MAT101",
                "Actividad": "teo"
            }
        ]
        
        # Create a profesor agent
        self.profesor = AgenteProfesor(
            jid="profesor1@localhost",
            password="password",
            nombre="Dr. Smith",
            asignaturas=self.asignaturas,
            orden=1
        )
        self.profesor.set_knowledge_base(self.kb)
        
        # Mock the storage
        self.storage_mock = MagicMock()
        self.storage_mock.update_schedule = AsyncMock()
        self.profesor.set_storage(self.storage_mock)
        
        # Initialize the agent
        self.profesor._initialize_data_structures()
        
        # Create the FSM
        self.fsm = NegotiationFSM(self.profesor)
        
        # Get access to the states
        self.setup_state = self.fsm._setup_state_factory()
        self.collecting_state = self.fsm._collecting_state_factory()
        self.evaluating_state = self.fsm._evaluating_state_factory()
        
        # Mock RTT logger
        self.setup_state.rtt_logger = MagicMock()
        self.setup_state.rtt_logger.start_request = AsyncMock()
        self.setup_state.rtt_initialized = True
        
        self.collecting_state.rtt_logger = MagicMock()
        self.collecting_state.rtt_logger.end_request = AsyncMock()
        
        self.evaluating_state.rtt_logger = MagicMock()
        self.evaluating_state.rtt_logger.start_request = AsyncMock()
        self.evaluating_state.rtt_logger.end_request = AsyncMock()
        self.evaluating_state.rtt_initialized = True
        
        # Mock external methods
        self.setup_state.send = AsyncMock()
        self.collecting_state.send = AsyncMock()
        self.collecting_state.receive = AsyncMock(return_value=None)
        self.evaluating_state.send = AsyncMock()
        self.evaluating_state.receive = AsyncMock(return_value=None)
        
    async def test_fsm_setup_state(self):
        """Test the setup state"""
        # Mock the send_cfp_messages method
        self.setup_state.send_cfp_messages = AsyncMock(return_value=5)  # 5 CFPs sent
        
        # Run the setup state
        await self.setup_state.run()
        
        # Verify state transition
        self.assertEqual(self.setup_state._next_state, NegotiationStates.COLLECTING)
        
        # Verify FSM state values
        self.assertEqual(self.fsm.bloques_pendientes, 4)  # From Algebra's horas
        self.assertEqual(self.fsm.cfp_count, 5)
        
    async def test_fsm_collecting_state(self):
        """Test the collecting state"""
        # Setup FSM state
        self.fsm.bloques_pendientes = 4
        self.fsm.cfp_count = 3
        self.fsm.expected_rooms = {"room1@localhost", "room2@localhost", "room3@localhost"}
        
        # Create mock proposals
        from objects.helper.batch_proposals import ClassroomAvailability
        
        # Setup receive to return a proposal
        proposal_msg = Message(
            to="profesor1@localhost",
            sender="room1@localhost"
        )
        proposal_msg.id = "msg1"
        proposal_msg.set_metadata("performative", "propose")
        proposal_msg.set_metadata("conversation-id", "test-conv")
        proposal_msg.set_metadata("rtt-id", "rtt1")
        
        availability = ClassroomAvailability(
            codigo="A101",
            campus="Kaufmann",
            capacidad=30,
            available_blocks={"LUNES": [1, 2, 3]}
        )
        proposal_msg.body = jsonpickle.encode(availability)
        
        # Mock receive to return our message once, then None
        self.collecting_state.receive = AsyncMock(side_effect=[proposal_msg, None])
        
        # Run the collecting state
        await self.collecting_state.run()
        
        # Verify state transition
        self.assertEqual(self.collecting_state._next_state, NegotiationStates.EVALUATING)
        
        # Verify proposal was processed
        self.assertEqual(self.fsm.responding_rooms, {"room1@localhost"})
        self.assertFalse(self.fsm.proposals.empty())
        
    async def test_fsm_evaluating_state(self):
        """Test the evaluating state"""
        # Setup FSM state
        self.fsm.bloques_pendientes = 4
        
        # Add a mock proposal to the queue
        from objects.helper.batch_proposals import BatchProposal, ClassroomAvailability
        
        availability = ClassroomAvailability(
            codigo="A101",
            campus="Kaufmann",
            capacidad=30,
            available_blocks={"LUNES": [1, 2, 3]}
        )
        
        msg = Message(
            to="profesor1@localhost",
            sender="room1@localhost"
        )
        msg.set_metadata("conversation-id", "test-conv")
        
        proposal = BatchProposal(availability, msg)
        await self.fsm.proposals.put(proposal)
        
        # Mock the evaluator
        self.evaluating_state.evaluator.filter_and_sort_proposals = AsyncMock(
            return_value=[proposal]
        )
        
        # Mock try_assign_batch_proposals to return True
        self.evaluating_state.try_assign_batch_proposals = AsyncMock(return_value=True)
        
        # Run the evaluating state
        await self.evaluating_state.run()
        
        # Verify proposal was processed
        self.evaluating_state.try_assign_batch_proposals.assert_called_once()
        
        # Verify state transition (should be COLLECTING for remaining blocks)
        self.assertEqual(self.evaluating_state._next_state, NegotiationStates.COLLECTING)

class EndToEndTest(BaseTestCase):
    """End-to-end tests simulating a full negotiation"""
    
    async def asyncSetUp(self):
        """Set up before each test"""
        await super().asyncSetUp()
        
        # Create a classroom agent
        self.sala = AgenteSala(
            jid="sala1@localhost", 
            password="password",
            codigo="A101",
            campus="Kaufmann",
            capacidad=30,
            turno=1
        )
        self.sala.set_knowledge_base(self.kb)
        
        # Create a professor agent
        self.asignaturas = [
            {
                "Nombre": "Algebra",
                "Nivel": 3,
                "Paralelo": "A",
                "Horas": 2,  # Only 2 hours for test simplicity
                "Vacantes": 25,
                "Campus": "Kaufmann",
                "CodigoAsignatura": "MAT101",
                "Actividad": "teo"
            }
        ]
        
        self.profesor = AgenteProfesor(
            jid="profesor1@localhost",
            password="password",
            nombre="Dr. Smith",
            asignaturas=self.asignaturas,
            orden=1
        )
        self.profesor.set_knowledge_base(self.kb)
        
        # Mock storages
        self.sala_storage = MagicMock()
        self.sala_storage.update_schedule = AsyncMock()
        self.sala.set_storage(self.sala_storage)
        
        self.prof_storage = MagicMock()
        self.prof_storage.update_schedule = AsyncMock()
        self.profesor.set_storage(self.prof_storage)
        
        # Initialize agents
        await self.sala.setup()
        await self.profesor.setup()
        
        # Setup KB to return our sala when searched
        sala_capability = AgentCapability(
            service_type="sala",
            properties={
                "codigo": "A101",
                "campus": "Kaufmann",
                "capacidad": 30,
                "turno": 1
            },
            last_updated=datetime.now()
        )
        
        sala_info = MagicMock()
        sala_info.jid = JID.fromstr("sala1@localhost")
        sala_info.capabilities = [sala_capability]
        
        self.kb.search = AsyncMock(return_value=[sala_info])
        
    async def test_end_to_end_single_assignment(self):
        """Test a complete end-to-end assignment process"""
        # 1. Start the FSM
        fsm = NegotiationFSM(self.profesor)
        self.profesor.negotiation_state_behaviour = fsm
        
        # No need to mock RTT logger for end-to-end
        fsm._setup_state_factory()
        
        # Run the FSM manually through each state
        # SETUP: Will send CFPs
        # Mock the send method to capture the message
        with patch.object(fsm._states[NegotiationStates.SETUP], 'send', new_callable=AsyncMock) as mock_send:
            await fsm._states[NegotiationStates.SETUP].run()
            
            # Verify a CFP was sent
            self.assertTrue(mock_send.called)
            cfp_msg = mock_send.call_args[0][0]
            self.assertEqual(cfp_msg.get_metadata("performative"), FIPAPerformatives.CFP)
        
        # COLLECTING: Will receive proposals
        # Create a proposal message
        from objects.helper.batch_proposals import ClassroomAvailability
        
        proposal_msg = Message(
            to="profesor1@localhost",
            sender="sala1@localhost"
        )
        proposal_msg.id = "msg1"
        proposal_msg.set_metadata("performative", "propose")
        proposal_msg.set_metadata("conversation-id", fsm.bloques_pendientes)
        proposal_msg.set_metadata("rtt-id", "rtt1")
        proposal_msg.set_metadata("ontology", "classroom-availability")
        
        availability = ClassroomAvailability(
            codigo="A101",
            campus="Kaufmann",
            capacidad=30,
            available_blocks={"LUNES": [1, 2, 3]}
        )
        proposal_msg.body = jsonpickle.encode(availability)
        
        # Mock receive to return our proposal
        with patch.object(fsm._states[NegotiationStates.COLLECTING], 'receive', 
                        new_callable=AsyncMock, return_value=proposal_msg):
            await fsm._states[NegotiationStates.COLLECTING].run()
            
            # Verify the proposal was added to the queue
            self.assertFalse(fsm.proposals.empty())
        
        # EVALUATING: Will send assignment requests
        # Mock send to capture the assignment message
        with patch.object(fsm._states[NegotiationStates.EVALUATING], 'send', 
                        new_callable=AsyncMock) as mock_send:
            
            # Also need to mock receive for the confirmation
            from objects.helper.confirmed_assignments import BatchAssignmentConfirmation, ConfirmedAssignment
            
            confirmation = BatchAssignmentConfirmation([
                ConfirmedAssignment(
                    day=Day.LUNES,
                    block=1,
                    classroom_code="A101",
                    satisfaction=8
                )
            ])
            
            confirm_msg = Message(
                to="profesor1@localhost",
                sender="sala1@localhost"
            )
            confirm_msg.set_metadata("performative", FIPAPerformatives.INFORM)
            confirm_msg.set_metadata("conversation-id", fsm.bloques_pendientes)
            confirm_msg.set_metadata("ontology", "room-assignment")
            confirm_msg.body = jsonpickle.encode(confirmation)
            
            with patch.object(fsm._states[NegotiationStates.EVALUATING], 'receive', 
                            new_callable=AsyncMock, return_value=confirm_msg):
                
                # Run the evaluating state
                await fsm._states[NegotiationStates.EVALUATING].run()
                
                # Verify an assignment request was sent
                self.assertTrue(mock_send.called)
                assign_msg = mock_send.call_args[0][0]
                self.assertEqual(assign_msg.get_metadata("performative"), 
                                FIPAPerformatives.ACCEPT_PROPOSAL)
                
                # Verify the profesor's schedule was updated
                self.assertIn(1, self.profesor.horario_ocupado[Day.LUNES])
                
                # Verify bloques_pendientes was decremented
                self.assertEqual(fsm.bloques_pendientes, 1)  # Started with 2

if __name__ == "__main__":
    unittest.main()