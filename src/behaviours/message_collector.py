from spade.agent import Agent
from spade.behaviour import CyclicBehaviour
from spade.message import Message
from spade.template import Template
from typing import Dict, List, Optional
import queue
import json
import asyncio

class MessageCollectorBehaviour(CyclicBehaviour):
    def __init__(self, batch_proposals: queue.Queue, negotiation_behaviour = None):
        super().__init__()
        # is a shared queue between the negotiation behaviour and the message collector
        self.batch_proposals = batch_proposals
        self.negotiation_behaviour = negotiation_behaviour
        