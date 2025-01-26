from spade.behaviour import CyclicBehaviour

class InitialWaitBehaviour(CyclicBehaviour):
    """Special wait behaviour for first professor"""
    def __init__(self, state_behaviour, message_collector):
        super().__init__()
        self.state_behaviour = state_behaviour
        self.message_collector = message_collector
        
    async def run(self):
        msg = await self.receive(timeout=10)
        if msg:
            self.agent.prepare_behaviours()
            self.kill()