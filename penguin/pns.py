from typing import Dict, List, Callable, Any
import asyncio

class PenguinNervousSystem:
    """
    Simple event bus system for inter-module communication
    """
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.running = False
        self.queue = asyncio.Queue()
        
    async def subscribe(self, event_type: str, callback: Callable):
        """Subscribe to an event type"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)
        
    async def publish(self, event_type: str, data: Any):
        """Publish an event to subscribers"""
        await self.queue.put((event_type, data))
        
    async def start(self):
        """Start processing events"""
        self.running = True
        asyncio.create_task(self._process_events())
        
    async def _process_events(self):
        """Main event processing loop"""
        while self.running:
            event_type, data = await self.queue.get()
            if event_type in self.subscribers:
                for callback in self.subscribers[event_type]:
                    try:
                        await callback(data)
                    except Exception as e:
                        # Log error but continue processing
                        print(f"Error processing event {event_type}: {e}")