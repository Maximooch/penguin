from typing import Dict, Optional
from .system.state import PenguinState
from .config import PenguinConfig

class PenguinHub:
    def __init__(self, config: Optional[PenguinConfig] = None):
        self.config = config or PenguinConfig()
        self.state = PenguinState()
        self.systems: Dict = {}
        
    async def register_system(self, name: str, system: any):
        """Register a system with the hub"""
        self.systems[name] = system
        # Give system reference to hub for direct communication
        system.hub = self
        
    async def dispatch(self, from_system: str, to_system: str, message: Dict):
        """Direct system-to-system communication"""
        if to_system in self.systems:
            await self.systems[to_system].receive(from_system, message)