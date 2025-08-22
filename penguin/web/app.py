"""Penguin Web Application - FastAPI-based web interface and API.

This module provides the main web application components including the FastAPI app
factory and a programmatic API class for embedding Penguin in other applications.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from penguin.config import config, Config
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error

logger = logging.getLogger(__name__)

# Global core instance for reuse
_core_instance: Optional[PenguinCore] = None

def get_or_create_core() -> PenguinCore:
    """Get the global core instance or create it if it doesn't exist."""
    global _core_instance
    
    if _core_instance is None:
        _core_instance = _create_core()
    
    return _core_instance

def _create_core() -> PenguinCore:
    """Create a new PenguinCore instance with proper configuration."""
    try:
        # Create a proper Config object
        config_obj = Config.load_config()
        model_config = config_obj.model_config

        # Initialize components using live Config-derived model_config
        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        # Pass a stable dict derived from live Config
        config_dict = config_obj.to_dict() if hasattr(config_obj, 'to_dict') else {}
        tool_manager = ToolManager(config_dict, log_error)

        # Create core with proper Config object
        core = PenguinCore(
            config=config_obj,
            api_client=api_client, 
            tool_manager=tool_manager, 
            model_config=model_config
        )
        
        logger.info("PenguinCore initialized successfully for web interface")
        return core
        
    except Exception as e:
        logger.error(f"Failed to initialize PenguinCore: {str(e)}")
        raise


def create_app() -> "FastAPI":
    """Create and configure the FastAPI application."""
    try:
        from fastapi import FastAPI
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from fastapi.middleware.cors import CORSMiddleware
        from .routes import router
    except ImportError:
        raise ImportError(
            "FastAPI and related dependencies not available. "
            "Install with: pip install penguin-ai[web]"
        )

    app = FastAPI(
        title="Penguin AI",
        description="AI Assistant with reasoning, memory, and tool use capabilities",
        version="0.3.1",
        docs_url="/api/docs", 
        redoc_url="/api/redoc"
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify allowed origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Initialize core and attach to router
    core = get_or_create_core()
    router.core = core

    # Include API routes
    app.include_router(router)

    # Mount static files for web UI
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        
        @app.get("/")
        async def read_root():
            """Serve the main web UI."""
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return {"message": "Penguin API is running. Web UI not found."}
    else:
        @app.get("/")
        async def api_root():
            """API root endpoint with service information."""
            return {
                "name": "Penguin AI API",
                "version": "0.3.1",
                "status": "running",
                "description": "AI Assistant with reasoning, memory, and tool use capabilities",
                "endpoints": {
                    "docs": "/api/docs",
                    "redoc": "/api/redoc",
                    "chat": "/api/v1/chat/message",
                    "conversations": "/api/v1/conversations",
                    "health": "/api/v1/health"
                },
                "features": [
                    "Multi-turn conversations",
                    "Memory and context management", 
                    "Tool and action execution",
                    "Project and task management",
                    "WebSocket streaming"
                ]
            }

    return app


class PenguinAPI:
    """Programmatic API interface for Penguin.
    
    This class provides a convenient way to interact with Penguin programmatically
    from other Python applications without going through the HTTP API.
    
    Example:
        ```python
        api = PenguinAPI()
        response = await api.chat("Hello, how can you help me?")
        print(response["assistant_response"])
        ```
    """
    
    def __init__(self, core: Optional[PenguinCore] = None):
        """Initialize the API interface.
        
        Args:
            core: Optional PenguinCore instance. If not provided, a global instance will be used.
        """
        self.core = core or get_or_create_core()
        logger.info("PenguinAPI interface initialized")
    
    async def chat(
        self, 
        message: str, 
        conversation_id: Optional[str] = None,
        image_path: Optional[str] = None,
        tools_enabled: bool = True,
        streaming: bool = False,
        max_iterations: int = 10  # Add max_iterations
    ) -> Dict[str, Any]:
        """Send a chat message and get a response.
        
        This method now uses the conversational `run_response` engine for a more
        natural multi-turn chat experience.
        
        Args:
            message: The message to send
            conversation_id: Optional conversation ID to continue an existing conversation
            image_path: Optional path to an image file for vision models
            tools_enabled: Whether to enable tool use (currently respected by Engine)
            streaming: Whether to use streaming for responses
            max_iterations: The maximum number of conversational turns.
            
        Returns:
            Dictionary containing the response and any action results
        """
        try:
            # Switch to conversation if specified
            if conversation_id:
                await self.core.conversation_manager.switch_conversation(conversation_id)

            # Use the more capable run_response for conversational chat
            if not self.core.engine:
                return {
                    "error": "Engine not available",
                    "assistant_response": "The core Engine is not available for processing.",
                    "action_results": []
                }

            response = await self.core.engine.run_response(
                prompt=message,
                image_path=image_path,
                max_iterations=max_iterations,
                streaming=streaming,
                # stream_callback is not directly supported here; websockets should be used for streaming
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Error in chat API: {str(e)}")
            return {
                "error": str(e),
                "assistant_response": "",
                "action_results": []
            }
    
    async def create_conversation(self, name: Optional[str] = None) -> str:
        """Create a new conversation.
        
        Args:
            name: Optional name for the conversation
            
        Returns:
            The conversation ID
        """
        try:
            conversation_id = await self.core.conversation_manager.create_conversation(name)
            return conversation_id
        except Exception as e:
            logger.error(f"Error creating conversation: {str(e)}")
            raise
    
    async def list_conversations(self) -> List[Dict[str, Any]]:
        """List all conversations.
        
        Returns:
            List of conversation summaries
        """
        try:
            conversations = await self.core.conversation_manager.list_conversations()
            return conversations
        except Exception as e:
            logger.error(f"Error listing conversations: {str(e)}")
            raise
    
    async def get_conversation_history(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Get the message history for a conversation.
        
        Args:
            conversation_id: The conversation ID
            
        Returns:
            List of messages in the conversation
        """
        try:
            # Switch to the conversation
            await self.core.conversation_manager.switch_conversation(conversation_id)
            
            # Get the formatted messages
            messages = self.core.conversation_manager.conversation.get_formatted_messages()
            return messages
        except Exception as e:
            logger.error(f"Error getting conversation history: {str(e)}")
            raise
    
    async def run_task(
        self, 
        task_description: str, 
        max_iterations: Optional[int] = None,
        project_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run a task using the engine.
        
        Args:
            task_description: Description of the task to run
            max_iterations: Maximum number of iterations
            project_id: Optional project ID to associate the task with
            
        Returns:
            Dictionary containing task execution results
        """
        try:
            result = await self.core.engine.run_task(
                task_prompt=task_description,
                max_iterations=max_iterations,
                task_context={"project_id": project_id} if project_id else None
            )
            return result
        except Exception as e:
            logger.error(f"Error running task: {str(e)}")
            return {
                "error": str(e),
                "assistant_response": "",
                "iterations": 0,
                "status": "error"
            }
    
    def get_health(self) -> Dict[str, Any]:
        """Get health status of the API.
        
        Returns:
            Health status information
        """
        try:
            return {
                "status": "healthy",
                "core_initialized": self.core is not None,
                "api_client_ready": self.core.api_client is not None if self.core else False,
                "tool_manager_ready": self.core.tool_manager is not None if self.core else False,
                "conversation_manager_ready": self.core.conversation_manager is not None if self.core else False
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            } 