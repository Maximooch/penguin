from .agent_system import Agent, CognitiveCapability
from cognition.cognition import CognitionSystem
from memory.memory_system import MemorySystem
from system.action_system import ActionSystem
from system.perception import PerceptionSystem

class PenguinAgent(Agent):
    def __init__(self, core: "PenguinCore"):
        super().__init__(
            cognition_system=CognitionAdapter(core.cognition),
            memory_system=MemoryAdapter(core.memory),
            action_system=ActionAdapter(core.action_executor),
            perception_system=PerceptionAdapter(core.conversation)
        )
        self.core = core

class CognitionAdapter(CognitiveCapability):
    def __init__(self, cognition: CognitionSystem):
        self.cognition = cognition
    
    async def process(self, context: AgentContext) -> Dict[str, Any]:
        # Adapt core cognition system to new interface
        return await self.cognition.process(context) 