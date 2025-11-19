from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid

@dataclass
class StreamContext:
    """Context for a specific execution stream (e.g., a task or session)."""
    stream_id: str
    parent_stream_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class AgentState:
    """State of a single agent."""
    agent_id: str
    role: str
    status: str  # "idle", "busy", "paused", "error"
    current_task_id: Optional[str] = None
    last_active: str = field(default_factory=lambda: datetime.utcnow().isoformat())

class WorldState:
    """
    Global state container for the Penguin runtime.
    
    This object tracks the high-level state of the system, including:
    - Link Platform integration (Project ID, Journal Path)
    - Active Agents and their status
    - Global Stream Context
    """
    
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WorldState, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.project_id: Optional[str] = None
        self.journal_path: Optional[str] = None
        self.active_agents: Dict[str, AgentState] = {}
        self.active_streams: Dict[str, StreamContext] = {}
        self.global_metadata: Dict[str, Any] = {}
        self._initialized = True

    def set_project_context(self, project_id: str, journal_path: Optional[str] = None):
        """Set the Link project context."""
        self.project_id = project_id
        self.journal_path = journal_path

    def register_agent(self, agent_id: str, role: str):
        """Register a new agent in the world."""
        self.active_agents[agent_id] = AgentState(
            agent_id=agent_id,
            role=role,
            status="idle"
        )

    def update_agent_status(self, agent_id: str, status: str, task_id: Optional[str] = None):
        """Update an agent's status."""
        if agent_id in self.active_agents:
            agent = self.active_agents[agent_id]
            agent.status = status
            agent.current_task_id = task_id
            agent.last_active = datetime.utcnow().isoformat()

    def create_stream(self, parent_stream_id: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a new execution stream."""
        stream_id = str(uuid.uuid4())
        self.active_streams[stream_id] = StreamContext(
            stream_id=stream_id,
            parent_stream_id=parent_stream_id,
            metadata=metadata or {}
        )
        return stream_id

    def get_stream(self, stream_id: str) -> Optional[StreamContext]:
        return self.active_streams.get(stream_id)

# Global instance
world = WorldState()
