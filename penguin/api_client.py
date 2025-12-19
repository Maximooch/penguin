"""
Penguin API Client - Programmatic interface to Penguin AI functionality.

This module provides a high-level, easy-to-use Python client for accessing
all Penguin AI functionality programmatically, including:

- Chat and conversation management
- Checkpoint creation, rollback, and branching  
- Model management and switching
- Task execution and run mode
- System diagnostics and monitoring
- Multi-modal capabilities (images, vision)

Example Usage:
    ```python
    from penguin.api_client import PenguinClient
    
    # Initialize client
    client = PenguinClient()
    await client.initialize()
    
    # Basic chat
    response = await client.chat("How can I optimize this Python code?")
    
    # Checkpoint workflow
    checkpoint = await client.create_checkpoint("Before optimization")
    # ... make changes ...
    await client.rollback_to_checkpoint(checkpoint)
    
    # Model management
    models = await client.list_models()
    await client.switch_model("anthropic/claude-3-sonnet-20240229")
    
    # Task execution
    result = await client.execute_task("Create a web scraper", continuous=False)
    ```
"""
# Where's the workspace path?

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union, Callable, AsyncGenerator
from dataclasses import dataclass

from .core import PenguinCore
from .config import config
from .llm.model_config import ModelConfig
from .system.checkpoint_manager import CheckpointType
from penguin.constants import get_engine_max_iterations_default

logger = logging.getLogger(__name__)


@dataclass
class ChatOptions:
    """Options for chat interactions."""
    conversation_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    context_files: Optional[List[str]] = None
    streaming: bool = False
    max_iterations: Optional[int] = None  # Uses config default if None
    image_path: Optional[str] = None
    agent_id: Optional[str] = None


@dataclass  
class TaskOptions:
    """Options for task execution."""
    name: Optional[str] = None
    description: Optional[str] = None
    continuous: bool = False
    time_limit: Optional[int] = None
    context: Optional[Dict[str, Any]] = None
    max_iterations: Optional[int] = None


@dataclass
class CheckpointInfo:
    """Information about a checkpoint."""
    id: str
    name: Optional[str]
    description: Optional[str]
    created_at: str
    type: str
    session_id: str


@dataclass
class ModelInfo:
    """Information about a model."""
    id: str
    name: str
    provider: str
    vision_enabled: bool
    max_output_tokens: Optional[int]
    current: bool


class PenguinClient:
    """High-level Python client for Penguin functionality."""
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace_path: Optional[str] = None
    ):
        """Initialize the Penguin client.
        
        Args:
            config_path: Path to config file (optional)
            model: Model to use (optional, overrides config)
            provider: Provider to use (optional, overrides config)
            workspace_path: Workspace directory (optional)
        """
        self.config_path = config_path
        self.model = model
        self.provider = provider
        self.workspace_path = workspace_path
        self._core: Optional[PenguinCore] = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the Penguin core and all subsystems."""
        if self._initialized:
            return
            
        try:
            # Use the factory method to create core with proper initialization
            self._core = await PenguinCore.create(
                model=self.model,
                provider=self.provider,
                workspace_path=self.workspace_path,
                fast_startup=True,  # Use fast startup for API clients
                show_progress=False  # Don't show progress bars in API mode
            )
            self._initialized = True
            logger.info("Penguin client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Penguin client: {e}")
            raise RuntimeError(f"Penguin client initialization failed: {e}") from e
    
    @property
    def core(self) -> PenguinCore:
        """Get the core instance, ensuring it's initialized."""
        if not self._initialized or not self._core:
            raise RuntimeError("Client not initialized. Call await client.initialize() first.")
        return self._core
    
    # Chat and Conversation Methods
    # ------------------------------------------------------------------
    
    async def chat(
        self,
        message: str,
        options: Optional[ChatOptions] = None
    ) -> str:
        """Send a chat message and get response.
        
        Args:
            message: The message to send
            options: Chat options (conversation_id, context, etc.)
            
        Returns:
            The assistant's response
        """
        opts = options or ChatOptions()
        
        response = await self.core.process_message(
            message=message,
            context=opts.context,
            conversation_id=opts.conversation_id,
            agent_id=opts.agent_id,
            context_files=opts.context_files,
            streaming=opts.streaming
        )
        
        return response
    
    async def stream_chat(
        self,
        message: str,
        options: Optional[ChatOptions] = None
    ) -> AsyncGenerator[str, None]:
        """Stream a chat response token by token.
        
        Args:
            message: The message to send
            options: Chat options
            
        Yields:
            Individual response tokens
        """
        opts = options or ChatOptions()
        
        # Create a queue to collect streaming tokens
        token_queue = asyncio.Queue()
        
        async def stream_callback(token: str):
            await token_queue.put(token)
        
        # Start the process task
        process_task = asyncio.create_task(
            self.core.process(
                input_data={"text": message, **({"image_path": opts.image_path} if opts.image_path else {})},
                context=opts.context,
                conversation_id=opts.conversation_id,
                agent_id=opts.agent_id,
                max_iterations=opts.max_iterations,
                context_files=opts.context_files,
                streaming=True,
                stream_callback=stream_callback
            )
        )
        
        # Yield tokens as they arrive
        try:
            while not process_task.done():
                try:
                    token = await asyncio.wait_for(token_queue.get(), timeout=0.1)
                    yield token
                except asyncio.TimeoutError:
                    continue
            
            # Get any remaining tokens
            while not token_queue.empty():
                yield token_queue.get_nowait()
                
        finally:
            if not process_task.done():
                process_task.cancel()
            
    async def list_conversations(self) -> List[Dict[str, Any]]:
        """List all conversations."""
        return self.core.list_conversations()
    
    async def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific conversation."""
        return self.core.get_conversation(conversation_id)
    
    async def create_conversation(self) -> str:
        """Create a new conversation."""
        return self.core.create_conversation()
    
    # Checkpoint Management Methods
    # ------------------------------------------------------------------
    
    async def create_checkpoint(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> str:
        """Create a conversation checkpoint.
        
        Args:
            name: Optional checkpoint name
            description: Optional checkpoint description
            
        Returns:
            Checkpoint ID
        """
        return await self.core.create_checkpoint(name=name, description=description)
    
    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        """Rollback conversation to a checkpoint.
        
        Args:
            checkpoint_id: The checkpoint ID to rollback to
            
        Returns:
            True if successful, False otherwise
        """
        return await self.core.rollback_to_checkpoint(checkpoint_id)
    
    async def branch_from_checkpoint(
        self,
        checkpoint_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> str:
        """Create a new conversation branch from a checkpoint.
        
        Args:
            checkpoint_id: The checkpoint to branch from
            name: Optional branch name
            description: Optional branch description
            
        Returns:
            New branch/conversation ID
        """
        return await self.core.branch_from_checkpoint(
            checkpoint_id, name=name, description=description
        )
    
    async def list_checkpoints(
        self,
        session_id: Optional[str] = None,
        limit: int = 50
    ) -> List[CheckpointInfo]:
        """List available checkpoints.
        
        Args:
            session_id: Optional session filter
            limit: Maximum number of checkpoints to return
            
        Returns:
            List of checkpoint information
        """
        checkpoints = self.core.list_checkpoints(session_id=session_id, limit=limit)
        
        return [
            CheckpointInfo(
                id=cp["id"],
                name=cp.get("name"),
                description=cp.get("description"),
                created_at=cp["created_at"],
                type=cp["type"],
                session_id=cp["session_id"]
            )
            for cp in checkpoints
        ]
    
    async def cleanup_checkpoints(self) -> int:
        """Clean up old checkpoints according to retention policy.
        
        Returns:
            Number of checkpoints cleaned up
        """
        return await self.core.cleanup_old_checkpoints()
    
    # Model Management Methods
    # ------------------------------------------------------------------
    
    async def list_models(self) -> List[ModelInfo]:
        """List available models.
        
        Returns:
            List of model information
        """
        models = self.core.list_available_models()
        
        return [
            ModelInfo(
                id=model["id"],
                name=model["name"],
                provider=model["provider"],
                vision_enabled=model.get("vision_enabled", False),
                max_output_tokens=model.get("max_output_tokens", model.get("max_tokens")),
                current=model.get("current", False)
            )
            for model in models
        ]
    
    async def switch_model(self, model_id: str) -> bool:
        """Switch to a different model.
        
        Args:
            model_id: The model to switch to
            
        Returns:
            True if successful, False otherwise
        """
        return await self.core.load_model(model_id)
    
    async def get_current_model(self) -> Optional[ModelInfo]:
        """Get current model information.
        
        Returns:
            Current model info, or None if no model loaded
        """
        model_data = self.core.get_current_model()
        if not model_data:
            return None
            
        return ModelInfo(
            id=model_data["model"],
            name=model_data["model"],
            provider=model_data["provider"],
            vision_enabled=model_data.get("vision_enabled", False),
            max_output_tokens=model_data.get("max_output_tokens", model_data.get("max_tokens")),
            current=True
        )
    
    # Task Execution Methods
    # ------------------------------------------------------------------
    
    async def execute_task(
        self,
        prompt: str,
        options: Optional[TaskOptions] = None
    ) -> Dict[str, Any]:
        """Execute a task using the Engine.
        
        Args:
            prompt: The task prompt/description
            options: Task execution options
            
        Returns:
            Task execution results
        """
        opts = options or TaskOptions()
        
        # Use Engine if available, fallback to process
        if hasattr(self.core, 'engine') and self.core.engine:
            return await self.core.engine.run_task(
                task_prompt=prompt,
                max_iterations=opts.max_iterations or get_engine_max_iterations_default(),
                task_name=opts.name or "API Task",
                task_context=opts.context or {},
                enable_events=True
            )
        else:
            # Fallback to regular process method
            return await self.core.process(
                input_data={"text": prompt},
                context=opts.context,
                max_iterations=opts.max_iterations or get_engine_max_iterations_default()
            )
    
    async def start_run_mode(
        self,
        options: Optional[TaskOptions] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> None:
        """Start autonomous run mode.
        
        Args:
            options: Run mode options
            event_callback: Optional callback for run mode events
        """
        opts = options or TaskOptions()
        
        await self.core.start_run_mode(
            name=opts.name,
            description=opts.description,
            context=opts.context,
            continuous=opts.continuous,
            time_limit=opts.time_limit,
            stream_event_callback=event_callback
        )
    
    # System and Diagnostics Methods
    # ------------------------------------------------------------------
    
    async def get_system_info(self) -> Dict[str, Any]:
        """Get comprehensive system information."""
        return self.core.get_system_info()
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get current system status."""
        return self.core.get_system_status()
    
    async def get_token_usage(self) -> Dict[str, Any]:
        """Get token usage statistics."""
        return self.core.get_token_usage()
    
    async def get_checkpoint_stats(self) -> Dict[str, Any]:
        """Get checkpoint system statistics."""
        return self.core.get_checkpoint_stats()
    
    # File and Context Methods
    # ------------------------------------------------------------------
    
    async def load_context_files(self, file_paths: List[str]) -> bool:
        """Load context files into the current conversation.
        
        Args:
            file_paths: List of file paths to load
            
        Returns:
            True if successful
        """
        try:
            for file_path in file_paths:
                if hasattr(self.core, "conversation_manager"):
                    self.core.conversation_manager.load_context_file(file_path)
            return True
        except Exception as e:
            logger.error(f"Failed to load context files: {e}")
            return False
    
    async def list_context_files(self) -> List[str]:
        """List available context files."""
        return self.core.list_context_files()

    # Agent management helpers
    # ------------------------------------------------------------------

    def create_agent(
        self,
        agent_id: str,
        *,
        system_prompt: Optional[str] = None,
        activate: bool = False,
        **kwargs,  # Legacy params - persona, model config, etc. stored in metadata
    ) -> None:
        """Register a new agent.

        Note: Legacy parameters (persona, model_config, etc.) are accepted but
        no longer stored in Core state. Agent config should be derived at runtime.
        """
        self.core.ensure_agent_conversation(agent_id, system_prompt=system_prompt)
        if activate:
            self.core.set_active_agent(agent_id)

    def create_sub_agent(
        self,
        agent_id: str,
        *,
        parent_agent_id: str,
        system_prompt: Optional[str] = None,
        share_session: bool = True,
        share_context_window: bool = True,
        shared_context_window_max_tokens: Optional[int] = None,
        activate: bool = False,
        **kwargs,  # Legacy params
    ) -> None:
        """Register a sub-agent bound to a parent agent."""
        self.core.create_sub_agent(
            agent_id,
            parent_agent_id=parent_agent_id,
            system_prompt=system_prompt,
            share_session=share_session,
            share_context_window=share_context_window,
            shared_context_window_max_tokens=shared_context_window_max_tokens,
        )
        if activate:
            self.core.set_active_agent(agent_id)

    def list_agents(self) -> List[str]:
        """List registered agent identifiers."""
        return self.core.list_agents()

    def list_sub_agents(self, parent_agent_id: Optional[str] = None) -> Dict[str, List[str]]:
        """List sub-agents mapped to their parent agents."""
        return self.core.list_sub_agents(parent_agent_id)

    # Agent roster and profiles
    # ------------------------------------------------------------------

    def get_agent_roster(self) -> List[Dict[str, Any]]:
        """Return detailed roster for all registered agents (JSON friendly)."""
        return self.core.get_agent_roster()

    def get_agent_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return roster information for a single agent."""
        return self.core.get_agent_profile(agent_id)

    # Agent pause/resume helpers
    # ------------------------------------------------------------------

    def pause_agent(self, agent_id: str) -> None:
        """Mark an agent as paused (engine-driven actions should be skipped)."""
        self.core.set_agent_paused(agent_id, True)

    def resume_agent(self, agent_id: str) -> None:
        """Mark an agent as resumed."""
        self.core.set_agent_paused(agent_id, False)

    async def unregister_agent(self, agent_id: str, *, preserve_conversation: bool = False) -> bool:
        """Unregister an agent and optionally remove its conversation state."""
        result = self.core.unregister_agent(agent_id, preserve_conversation=preserve_conversation)
        if asyncio.iscoroutine(result):
            result = await result
        return bool(result)

    async def send_to_agent(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Forward a structured message to an agent via MessageBus."""
        return await self.core.send_to_agent(
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    async def send_to_human(
        self,
        content: Any,
        *,
        message_type: str = "status",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Forward a structured message to the human recipient via MessageBus."""
        return await self.core.send_to_human(
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    # What if there's multiple humans? @penguin_todo_multi_humans.md 
    # I suppose we could just have a human_id and then we can have multiple humans that way for now.
    async def human_reply(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a human-authored reply to an agent via MessageBus."""
        return await self.core.human_reply(
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    async def get_telemetry_summary(self) -> Dict[str, Any]:
        """Fetch aggregated telemetry summary."""
        return await self.core.get_telemetry_summary()

    def get_conversation_history(
        self,
        conversation_id: str,
        *,
        include_system: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve detailed conversation history annotated with agent metadata."""
        return self.core.get_conversation_history(
            conversation_id,
            include_system=include_system,
            limit=limit,
        )
    
    # Utility Methods
    # ------------------------------------------------------------------
    
    async def close(self) -> None:
        """Clean up resources and close the client."""
        if self._core and hasattr(self._core, 'cleanup'):
            await self._core.cleanup()
        self._initialized = False
        self._core = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# Convenience function for quick setup
async def create_client(
    model: Optional[str] = None,
    provider: Optional[str] = None,
    workspace_path: Optional[str] = None
) -> PenguinClient:
    """Create and initialize a Penguin client.
    
    Args:
        model: Model to use (optional)  
        provider: Provider to use (optional)
        workspace_path: Workspace directory (optional)
        
    Returns:
        Initialized PenguinClient
    """
    client = PenguinClient(
        model=model,
        provider=provider,
        workspace_path=workspace_path
    )
    await client.initialize()
    return client
