from enum import Enum
from typing import Dict, Optional, List

class SystemState(Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    CHAT = "chat"
    ERROR = "error"
    SHUTDOWN = "shutdown"

class PenguinState:
    """Central state management for all systems"""
    def __init__(self):
        self.system_states: Dict[str, SystemState] = {}
        self.global_state: SystemState = SystemState.IDLE
        self.state_history: List[SystemState] = []
        self._previous_state: Optional[SystemState] = None
        
    async def update_system_state(self, system: str, state: SystemState):
        """Update individual system state"""
        self._previous_state = self.system_states.get(system)
        self.system_states[system] = state
        self.state_history.append(state)
        await self._check_global_state()
        
    async def resume_previous_state(self, system: str) -> None:
        """Resume previous state after interruption"""
        if self._previous_state:
            await self.update_system_state(system, self._previous_state)
            
    async def _check_global_state(self):
        """Update global state based on system states"""
        if any(state == SystemState.ERROR for state in self.system_states.values()):
            self.global_state = SystemState.ERROR
        elif any(state == SystemState.CHAT for state in self.system_states.values()):
            self.global_state = SystemState.CHAT
        elif all(state == SystemState.IDLE for state in self.system_states.values()):
            self.global_state = SystemState.IDLE
        else:
            self.global_state = SystemState.PROCESSING