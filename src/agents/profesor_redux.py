from spade.agent import Agent
from spade.behaviour import CyclicBehaviour, PeriodicBehaviour
from spade.message import Message
from spade.template import Template
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from queue import Queue
import json
from behaviours.negotiation_behaviour import NegotiationStateBehaviour
from behaviours.message_collector import MessageCollectorBehaviour

class AgenteProfesor(Agent):
    def __init__(self, 
        jid: str, 
        password: str, 
    ):
        super(AgenteProfesor, self).__init__(jid, password)
        
    
    
    async def setup(self):
        batch_proposals = Queue()
        state_behaviour = NegotiationStateBehaviour(self, batch_proposals)
        
        self.add_behaviour(state_behaviour)
        self.add_behaviour(MessageCollectorBehaviour(self, batch_proposals, state_behaviour))

        