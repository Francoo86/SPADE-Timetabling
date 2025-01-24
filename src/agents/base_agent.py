from spade.agent import Agent

class TimeTablingAgent(Agent):
    """Base class for all agents in the timetabling system"""
    
    def __init__(self, jid: str, password: str, name: str):
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