from spade import agent
from spade.behaviour import OneShotBehaviour
from spade.message import Message
import asyncio
import time

class SenderAgent(agent.Agent):
    class SendMessageBehaviour(OneShotBehaviour):
        async def run(self):
            msg = Message(to="receiver@localhost")
            msg.body = "Hello World!"
            msg.set_metadata("performative", "inform")
            await self.send(msg)
            print(f"[{self.agent.name}] Message sent!")

    async def setup(self):
        self.add_behaviour(self.SendMessageBehaviour())

class ReceiverAgent(agent.Agent):
    class ReceiveMessageBehaviour(OneShotBehaviour):
        async def run(self):
            msg = await self.receive(timeout=10)
            if msg:
                print(f"[{self.agent.name}] Received message: {msg.body}")
                print(f"Goodbye {self.agent.name}")
            else:
                print(f"[{self.agent.name}] No message received after timeout")

    async def setup(self):
        self.add_behaviour(self.ReceiveMessageBehaviour())

async def main():
    try:
        # Create agents with auto_register=True
        sender = SenderAgent("sender@localhost", "password", verify_security=False)
        sender.web.start(hostname="127.0.0.1", port=10000)
        
        receiver = ReceiverAgent("receiver@localhost", "password", verify_security=False)
        receiver.web.start(hostname="127.0.0.1", port=10001)

        # Start agents
        await sender.start(auto_register=True)  # Enable auto-registration
        await receiver.start(auto_register=True)  # Enable auto-registration

        # Wait for agents to finish
        await asyncio.sleep(2)

        # Stop agents
        await sender.stop()
        await receiver.stop()
        
    except KeyboardInterrupt:
        await sender.stop()
        await receiver.stop()
    
    except Exception as e:
        print(f"An error occurred: {e}")
        # Ensure agents are stopped even if an error occurs
        await sender.stop()
        await receiver.stop()

if __name__ == "__main__":
    asyncio.run(main())