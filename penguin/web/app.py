"""Penguin Web Application - FastAPI-based web interface and API.

This module provides the main web application components including the FastAPI app
factory and a programmatic API class for embedding Penguin in other applications.
"""

import logging
import os
from pathlib import Path
import asyncio
from contextlib import suppress
from typing import Optional, Dict, Any, List, AsyncGenerator, Callable, Awaitable

from penguin import __version__
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
        from .routes import router, get_capabilities
        from .integrations.github_webhook import router as github_webhook_router
        from .middleware.auth import AuthenticationMiddleware, AuthConfig
    except ImportError:
        raise ImportError(
            "FastAPI and related dependencies not available. "
            "Install with: pip install penguin-ai[web]"
        )

    app = FastAPI(
        title="Penguin AI",
        description="AI Assistant with reasoning, memory, and tool use capabilities",
        version=__version__,
        docs_url="/api/docs",
        redoc_url="/api/redoc"
    )

    # Configure CORS
    origins_env = os.getenv("PENGUIN_CORS_ORIGINS", "").strip()
    origins_list = [o.strip() for o in origins_env.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Add authentication middleware (applies after CORS)
    auth_config = AuthConfig()
    app.add_middleware(AuthenticationMiddleware, config=auth_config)

    # Initialize core and attach to router
    core = get_or_create_core()
    try:
        logger.info("Model configs loaded: %s", list((getattr(core.config, "model_configs", {}) or {}).keys()))
    except Exception:
        logger.info("Model configs loaded: unknown")
    router.core = core
    github_webhook_router.core = core

    # Include API routes
    app.include_router(router)
    app.include_router(github_webhook_router)

    # Optionally include MCP HTTP router when enabled
    try:
        from penguin.integrations.mcp.server import MCPServer  # type: ignore
        from penguin.integrations.mcp.http_server import get_router as get_mcp_router  # type: ignore

        mcp_conf: Dict[str, Any] = config.get("mcp", {}) if isinstance(config, dict) else {}
        srv_conf: Dict[str, Any] = mcp_conf.get("server", {}) if isinstance(mcp_conf, dict) else {}
        http_conf: Dict[str, Any] = srv_conf.get("http", {}) if isinstance(srv_conf, dict) else {}
        # Register remote MCP servers as virtual tools (client bridge)
        servers_conf = mcp_conf.get("servers") if isinstance(mcp_conf, dict) else None
        if isinstance(servers_conf, list) and servers_conf:
            try:
                from penguin.integrations.mcp.client import MCPClientBridge  # type: ignore

                MCPClientBridge(servers_conf).register_remote_tools(core.tool_manager)
            except Exception:
                pass

        if bool(http_conf.get("enabled", False)):
            allow_patterns = srv_conf.get("allow_tools") or ["*"]
            deny_patterns = srv_conf.get("deny_tools") or [
                "browser_*",
                "pydoll_*",
                "reindex_workspace",
            ]
            mcp_server = MCPServer(
                core.tool_manager,
                allow=allow_patterns,
                deny=deny_patterns,
                confirm_required_write=True,
            )
            oauth2_conf = http_conf.get("oauth2") if isinstance(http_conf.get("oauth2"), dict) else None
            app.include_router(get_mcp_router(mcp_server, oauth2=oauth2_conf))
    except Exception:
        # MCP is optional; proceed silently if unavailable
        pass

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
            capabilities = await get_capabilities(core)
            return {
                "name": "Penguin AI API",
                "version": __version__,
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
                ],
                "capabilities": capabilities,
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
        max_iterations: int = 5000,
        on_chunk: Optional[Callable[[str, str], Awaitable[None]]] = None,
        include_reasoning: bool = False,
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
            max_iterations: The maximum number of conversational turns (default 5000).
            
        Returns:
            Dictionary containing the response and any action results
        """
        try:
            if not self.core.engine:
                return {
                    "error": "Engine not available",
                    "assistant_response": "The core Engine is not available for processing.",
                    "action_results": []
                }

            input_data: Dict[str, Any] = {"text": message}
            if image_path:
                input_data["image_path"] = image_path

            effective_streaming = streaming or include_reasoning or on_chunk is not None
            reasoning_chunks: List[str] = []
            stream_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

            if effective_streaming:
                async def _forward_chunk(chunk: str, message_type: str = "assistant") -> None:
                    if include_reasoning and message_type == "reasoning" and chunk:
                        reasoning_chunks.append(chunk)
                    if on_chunk:
                        try:
                            if asyncio.iscoroutinefunction(on_chunk):
                                await on_chunk(chunk, message_type)
                            else:
                                await asyncio.to_thread(on_chunk, chunk, message_type)
                        except TypeError:
                            if asyncio.iscoroutinefunction(on_chunk):
                                await on_chunk(chunk)  # type: ignore[misc]
                            else:
                                await asyncio.to_thread(on_chunk, chunk)
                        except Exception as cb_err:  # pragma: no cover - defensive logging
                            logger.warning("PenguinAPI chat on_chunk callback failed: %s", cb_err)

                stream_callback = _forward_chunk

            process_result = await self.core.process(
                input_data=input_data,
                conversation_id=conversation_id,
                streaming=effective_streaming,
                max_iterations=max_iterations,
                stream_callback=stream_callback,
            )

            if include_reasoning:
                process_result["reasoning"] = "".join(reasoning_chunks)

            return process_result

        except Exception as e:
            logger.error(f"Error in chat API: {str(e)}")
            return {
                "error": str(e),
                "assistant_response": "",
                "action_results": []
            }

    async def stream_chat(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        image_path: Optional[str] = None,
        max_iterations: int = 5000,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Stream chat responses as (message_type, chunk) tuples."""

        queue: asyncio.Queue[tuple[Optional[str], Optional[str]]] = asyncio.Queue()

        async def _on_chunk(chunk: str, message_type: str = "assistant") -> None:
            await queue.put((message_type, chunk))

        async def _runner() -> None:
            try:
                await self.chat(
                    message,
                    conversation_id=conversation_id,
                    image_path=image_path,
                    streaming=True,
                    max_iterations=max_iterations,
                    on_chunk=_on_chunk,
                )
            finally:
                await queue.put((None, None))

        runner_task = asyncio.create_task(_runner())
        try:
            while True:
                message_type, chunk = await queue.get()
                if message_type is None:
                    break
                yield message_type, chunk or ""
        finally:
            runner_task.cancel()
            with suppress(asyncio.CancelledError):
                await runner_task
    
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
