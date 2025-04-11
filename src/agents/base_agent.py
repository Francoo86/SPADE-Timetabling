from spade.agent import Agent
from .agent_logger import AgentLogger

class TimeTablingAgent(Agent):
    """Base class for all agents in the timetabling system"""
    
    def __init__(self, jid: str, password: str, name: str, turno: int = 0):
        """
        Initialize the agent.
        
        Args:
            jid: Agent's JID
            password: Agent's password
            name: Agent's name
        """
        super().__init__(jid, password)
        self.name = name
        self.log = None
        self.kb = None
        self.log = AgentLogger(name=name, jid=jid)
        self.storage = None
        self.turno = turno
        
    def set_knowledge_base(self, kb):
        """
        Set the agent's knowledge base.
        
        Args:
            kb: Knowledge base
        """
        self.kb = kb
        
    def set_storage(self, storage):
        """
        Set the agent's storage.
        
        Args:
            storage: Storage object
        """
        self.storage = storage
    