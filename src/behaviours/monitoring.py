from spade.behaviour import CyclicBehaviour

class InitialWaitBehaviour(CyclicBehaviour):
    """Special wait behaviour for first professor"""
    def __init__(self):
        super().__init__()

    async def run(self):
        msg = await self.receive(timeout=10)
        if msg:
            await self.agent.message_logger.log_message_received(
                self.agent.representative_name, msg
            )
            self.agent.prepare_behaviours()
            self.kill()