from spade.behaviour import FSMBehaviour, State

class CollectingState(State):
    async def run(self):
        print("Collecting data...")