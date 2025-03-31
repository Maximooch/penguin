"""
PenguinCore acts as the central nervous system for the Penguin AI assistant, orchestrating interactions between various subsystems.

Key Systems:
- ConversationManager: Handles messages, context, conversation persistence, and formatting
- ToolManager: Manages available tools and capabilities
- ActionExecutor: Routes and executes actions using appropriate handlers
- ProjectManager: Handles project and task management
- Diagnostic System: Monitors performance and resource usage

The core acts as a coordinator rather than implementing functionality directly:
- Routes messages and actions between subsystems
- Manages initialization and cleanup
- Handles error conditions and recovery
- Provides unified interface for external interaction

Key Features:
- Modular architecture allowing easy extension
- Robust error handling and logging
- Configurable diagnostic tracking
- Support for multiple conversation modes
- Flexible tool integration system
- Project and task management capabilities

API Specification:

Core Methods:
    @classmethod
    async create(
        cls,
        config: Optional[Config] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace_path: Optional[str] = None,
        enable_cli: bool = False,
    ) -> Union["PenguinCore", Tuple["PenguinCore", "PenguinCLI"]]:
        Factory method for creating PenguinCore instance with optional CLI

    __init__(
        config: Optional[Config] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None,
        model_config: Optional[ModelConfig] = None
    ) -> None:
        Initialize PenguinCore with optional config and components

    async process_message(
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        streaming: bool = False
    ) -> str:
        Process a user message and return formatted response

    async process(
        input_data: Union[Dict[str, Any], str],
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        max_iterations: int = 5,
        context_files: Optional[List[str]] = None,
        streaming: Optional[bool] = None
    ) -> Dict[str, Any]:
        Process input with multi-step reasoning and action execution

    async get_response(
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None
    ) -> Tuple[Dict[str, Any], bool]:
        Generate response using conversation context
        Returns response data and continuation flag

    async start_run_mode(
        name: Optional[str] = None,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        continuous: bool = False,
        time_limit: Optional[int] = None
    ) -> None:
        Start autonomous run mode for task execution

Conversation Management:
    list_conversations(limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        List available conversations with pagination

    get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
        Get a specific conversation by ID

    create_conversation() -> str:
        Create a new conversation and return its ID

    delete_conversation(conversation_id: str) -> bool:
        Delete a conversation by ID

    get_conversation_stats() -> Dict[str, Any]:
        Get statistics about conversations

    list_context_files() -> List[Dict[str, Any]]:
        List all available context files

State Management:
    reset_context() -> None:
        Reset conversation context and diagnostics

    async reset_state() -> None:
        Reset core state including messages, tools, and external resources

    set_system_prompt(prompt: str) -> None:
        Set system prompt for conversation

    register_progress_callback(callback: Callable[[int, int, Optional[str]], None]) -> None:
        Register a callback for progress updates

Properties:
    total_tokens_used -> int:
        Get total tokens used in current session

    get_token_usage() -> Dict[str, Dict[str, int]]:
        Get detailed token usage statistics

Action Handling:
    async execute_action(action) -> Dict[str, Any]:
        Execute an action and return structured result

Usage:
The core should be initialized with required configuration and subsystems before use.
It provides high-level methods for message processing, task execution, and system control.

Example:
    core = await PenguinCore.create(config=config)
    response = await core.process_message("Hello!")
    await core.start_run_mode(name="coding_task")
"""

import asyncio
import logging
import time
import traceback
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, Callable
import asyncio

from dotenv import load_dotenv  # type: ignore
from rich.console import Console  # type: ignore
from tenacity import (  # type: ignore
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from tqdm import tqdm

# Configuration
from penguin.config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    TASK_COMPLETION_PHRASE,
    WORKSPACE_PATH,
    Config,
)

# LLM and API
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig

# Local task manager
from penguin.local_task.manager import ProjectManager

# RunMode
from penguin.run_mode import RunMode

# Core systems
from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory

# System Prompt
from penguin.system_prompt import SYSTEM_PROMPT
# Workflow Prompt
from penguin.prompt_workflow import PENGUIN_WORKFLOW

# Tools and Processing
from penguin.tools import ToolManager
from penguin.utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
from penguin.utils.log_error import log_error
from penguin.utils.parser import ActionExecutor, parse_action


if TYPE_CHECKING:
    from penguin.chat.cli import PenguinCLI

logger = logging.getLogger(__name__)
console = Console()


class PenguinCore:
    """
    Central coordinator for the Penguin AI assistant.
    
    Acts as an integration point between:
    - ConversationManager: Handles messages, context, and conversation state
    - ToolManager: Provides access to available tools and actions
    - ActionExecutor: Executes actions and processes results
    - ProjectManager: Manages projects and tasks
    
    This class focuses on coordination rather than direct implementation,
    delegating most functionality to specialized components.
    
    Attributes:
        conversation_manager (ConversationManager): Manages conversations and context
        tool_manager (ToolManager): Manages available tools
        action_executor (ActionExecutor): Executes actions from LLM responses
        project_manager (ProjectManager): Manages projects and tasks
        api_client (APIClient): Handles API communication
        config (Config): System configuration
        model_config (ModelConfig): Model-specific configuration
    """
    
    @classmethod
    async def create(
        cls,
        config: Optional[Config] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace_path: Optional[str] = None,
        enable_cli: bool = False,
    ) -> Union["PenguinCore", Tuple["PenguinCore", "PenguinCLI"]]:
        """
        Factory method for creating PenguinCore instance.
        Returns either PenguinCore alone or with CLI if enable_cli=True
        """
        try:
            # Initialize progress bar
            steps = [
                "Loading environment",
                "Setting up logging",
                "Loading configuration",
                "Creating model config",
                "Initializing API client",
                "Creating tool manager",
                "Creating core instance",
            ]
            if enable_cli:
                steps.append("Initializing CLI")

            pbar = tqdm(steps, desc="Initializing Penguin", unit="step")

            # Track start time
            start_time = time.time()

            # Step 1: Load environment
            pbar.set_description("Loading environment")
            load_dotenv()
            pbar.update(1)

            # Step 2: Initialize logging
            pbar.set_description("Setting up logging")
            logging.basicConfig(level=logging.WARNING)
            for logger_name in [
                "httpx",
                "sentence_transformers",
                "LiteLLM",
                "tools",
                "llm",
            ]:
                logging.getLogger(logger_name).setLevel(logging.WARNING)
            logging.getLogger("chat").setLevel(logging.DEBUG)
            pbar.update(1)

            # Load configuration
            pbar.set_description("Loading configuration")
            config = config or Config.load_config()
            pbar.update(1)

            # Initialize model configuration
            pbar.set_description("Creating model config")
            model_config = ModelConfig(
                model=model or DEFAULT_MODEL,
                provider=provider or DEFAULT_PROVIDER,
                api_base=config.api.base_url,
                use_assistants_api=config.model.get("use_assistants_api", False),
                use_native_adapter=config.model.get("use_native_adapter", True),
                streaming_enabled=config.model.get("streaming_enabled", True)
            )
            pbar.update(1)

            # Create API client
            pbar.set_description("Initializing API client")
            api_client = APIClient(model_config=model_config)
            api_client.set_system_prompt(SYSTEM_PROMPT)
            pbar.update(1)

            # Initialize tool manager
            pbar.set_description("Creating tool manager")
            tool_manager = ToolManager(log_error)
            pbar.update(1)

            # Create core instance
            pbar.set_description("Creating core instance")
            instance = cls(
                config=config, 
                api_client=api_client, 
                tool_manager=tool_manager, 
                model_config=model_config
            )
            pbar.update(1)

            if enable_cli:
                # Import CLI only when needed
                pbar.set_description("Initializing CLI")
                from penguin.chat.cli import PenguinCLI
                cli = PenguinCLI(instance)
                pbar.update(1)

            # Close progress bar
            pbar.close()

            # Show total initialization time
            init_time = time.time() - start_time
            logger.info(f"Initialization completed in {init_time:.2f} seconds")

            return instance if not enable_cli else (instance, cli)

        except Exception as e:
            # Close progress bar on error
            if "pbar" in locals():
                pbar.close()
            error_msg = f"Failed to initialize PenguinCore: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def __init__(
        self,
        config: Optional[Config] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None,
        model_config: Optional[ModelConfig] = None,
    ):
        """Initialize PenguinCore with required components."""
        self.config = config or Config.load_config()
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.model_config = model_config
        self._interrupted = False
        self.progress_callbacks = []
        self.token_callbacks = []
        self._active_contexts = set()  # Track active execution contexts

        # Set system prompt from import
        self.system_prompt = SYSTEM_PROMPT

        # Initialize project manager with workspace path from config
        self.project_manager = ProjectManager(workspace_root=WORKSPACE_PATH)

        # Initialize diagnostics based on config
        if not self.config.diagnostics.enabled:
            disable_diagnostics()
        
        # Ensure model_config max_tokens is consistent - fix for test failures
        if model_config and not hasattr(model_config, 'max_tokens'):
            model_config.max_tokens = self.config.model.get("max_tokens", 8000)
        elif model_config and model_config.max_tokens is None:
            model_config.max_tokens = self.config.model.get("max_tokens", 8000)

        # Initialize conversation manager (replaces conversation system)
        self.conversation_manager = ConversationManager(
            model_config=model_config,
            api_client=api_client,
            workspace_path=WORKSPACE_PATH,
            system_prompt=SYSTEM_PROMPT,
            max_messages_per_session=5000,
            max_sessions_in_memory=20,
            auto_save_interval=60
        )

        # Initialize action executor with project manager and conversation manager
        self.action_executor = ActionExecutor(
            tool_manager=self.tool_manager, 
            task_manager=self.project_manager,
            conversation_system=self.conversation_manager.conversation
        )

        # Initialize core systems (commented out during refactoring)
        # TODO: Cognition system is temporarily disabled while refactoring conversation architecture
        # self.cognition = CognitionSystem(
        #     api_client=self.api_client, 
        #     diagnostics=diagnostics
        # )

        # State
        self.initialized = True
        logger.info("PenguinCore initialized successfully")

        # Ensure error log directory exists
        self.validate_path(Path(WORKSPACE_PATH))

        # Add an accumulated token counter
        self.accumulated_tokens = {"prompt": 0, "completion": 0, "total": 0}

        # Disable LiteLLM debugging
        try:
            from litellm import _logging # type: ignore
            _logging._disable_debugging()
            # Also set these to be safe
            import litellm # type: ignore
            litellm.set_verbose = False
            litellm.drop_params = False
        except Exception as e:
            logger.warning(f"Failed to disable LiteLLM debugging: {e}")

        # Add these attributes
        self.current_stream = None
        self.stream_lock = asyncio.Lock()

    def validate_path(self, path: Path):
        """Validate and create a directory path if needed."""
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.W_OK):
            raise PermissionError(f"No write access to {path}")

    def register_progress_callback(self, callback: Callable[[int, int, Optional[str]], None]) -> None:
        """Register a callback for progress updates during multi-step processing."""
        self.progress_callbacks.append(callback)

    def notify_progress(self, iteration: int, max_iterations: int, message: Optional[str] = None) -> None:
        """Notify all registered callbacks about progress."""
        for callback in self.progress_callbacks:
            callback(iteration, max_iterations, message)

    def reset_context(self):
        """
        Reset conversation context and diagnostics.
        
        This method clears the current conversation state and resets all
        tools and diagnostics. Use this between different conversation
        sessions.
        """
        diagnostics.reset()
        self._interrupted = False
        
        # Reset conversation via manager
        self.conversation_manager.reset()
        
        # Reset tools
        if self.tool_manager:
            self.tool_manager.reset()
        if self.action_executor:
            self.action_executor.reset()

    @property
    def total_tokens_used(self) -> int:
        """Get total tokens used via conversation manager"""
        try:
            token_usage = self.conversation_manager.get_token_usage()
            return token_usage.get("total", 0)
        except Exception:
            return 0

    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        """Get token usage via conversation manager"""
        try:
            usage = self.conversation_manager.get_token_usage()
            return {"main_model": {"prompt": usage.get("total", 0), "completion": 0, "total": usage.get("total", 0)}}
        except Exception:
            return {"main_model": {"prompt": 0, "completion": 0, "total": 0}}

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt for both core and API client."""
        self.system_prompt = prompt
        if self.api_client:
            self.api_client.set_system_prompt(prompt)
        self.conversation_manager.set_system_prompt(prompt)

    def _check_interrupt(self) -> bool:
        """Check if execution has been interrupted"""
        return self._interrupted

    async def process_message(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        streaming: bool = False
    ) -> str:
        """
        Process a message with optional conversation support.
        
        Args:
            message: The user message to process
            context: Optional additional context for processing
            conversation_id: Optional ID to continue an existing conversation
            context_files: Optional list of context files to load
            streaming: Whether to use streaming mode for responses
        """
        try:
            # Add context if provided
            if context:
                for key, value in context.items():
                    self.conversation_manager.add_context(f"{key}: {value}")
                    
            # Process through conversation manager (handles context files)
            return await self.conversation_manager.process_message(
                message=message,
                conversation_id=conversation_id,
                streaming=streaming,
                context_files=context_files
            )
            
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "process_message",
                    "message": message
                },
            )
            return error_msg

    async def get_response(
        self,
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Generate a response using the conversation context and execute any actions.
        
        Args:
            current_iteration: Current iteration number for multi-step processing
            max_iterations: Maximum iterations for multi-step processing
            
        Returns:
            Tuple of (response data, exit continuation flag)
        """
        try:
            # Add iteration marker if in multi-step processing
            if current_iteration is not None and max_iterations is not None:
                self.conversation_manager.conversation.add_iteration_marker(
                    current_iteration, max_iterations
                )
            
            # Get formatted messages from conversation manager
            messages = self.conversation_manager.conversation.get_formatted_messages()
            
            # Maximum retry attempts for empty responses
            max_retries = 2
            retry_count = 0
            
            while retry_count <= max_retries:
                # Acquire stream lock and handle any active stream
                async with self.stream_lock:
                    if self.current_stream and not self.current_stream.done():
                        try:
                            logger.debug("Cancelling previous stream")
                            self.current_stream.cancel()
                            # Give it a moment to clean up
                            await asyncio.sleep(0.1)
                        except Exception as e:
                            logger.debug(f"Error cancelling previous stream: {e}")
                        self.current_stream = None
                
                # Start new stream and store reference
                logger.debug("Starting new API response stream")
                self.current_stream = asyncio.create_task(
                    self.api_client.get_response(messages=messages)
                )
                
                try:
                    # Wait for stream to complete
                    assistant_response = await self.current_stream
                except asyncio.CancelledError:
                    logger.warning("Response stream was cancelled")
                    assistant_response = None
                except Exception as e:
                    logger.error(f"Error in response stream: {str(e)}")
                    assistant_response = None
                finally:
                    self.current_stream = None
                
                # Validate response
                if not assistant_response or not assistant_response.strip():
                    retry_count += 1
                    if retry_count <= max_retries:
                        logger.warning(f"Empty response from API (attempt {retry_count}/{max_retries}), retrying...")
                        # Small exponential backoff
                        await asyncio.sleep(1 * retry_count)
                        continue
                    else:
                        logger.warning(f"Empty response from API after {max_retries} attempts")
                        assistant_response = "I apologize, but I encountered an issue generating a response. Please try again."
                        break
                else:
                    # We got a valid response, break the retry loop
                    break
            
            # Add assistant response to conversation
            self.conversation_manager.conversation.add_assistant_message(assistant_response)
            
            # Parse actions and continue with action handling
            actions = parse_action(assistant_response)
            
            # Check for task completion
            exit_continuation = TASK_COMPLETION_PHRASE in assistant_response
            
            # Execute actions with interrupt checking
            action_results = []
            for action in actions:
                if self._check_interrupt():
                    action_results.append({
                        "action": action.action_type.value,
                        "result": "Action skipped due to interrupt",
                        "status": "interrupted",
                    })
                    continue

                try:
                    result = await self.action_executor.execute_action(action)
                    if result is not None:
                        action_results.append({
                            "action": action.action_type.value,
                            "result": str(result),
                            "status": "completed",
                        })
                        
                        # Update conversation with action result
                        self.conversation_manager.add_action_result(
                            action_type=action.action_type.value,
                            result=str(result),
                            status="completed"
                        )
                except Exception as e:
                    error_result = {
                        "action": action.action_type.value,
                        "result": f"Error executing action: {str(e)}",
                        "status": "error",
                    }
                    action_results.append(error_result)
                    self.conversation_manager.add_action_result(
                        action_type=action.action_type.value,
                        result=f"Error executing action: {str(e)}",
                        status="error"
                    )
                    logger.error(f"Action execution error: {str(e)}")

            # Save the updated conversation state
            self.conversation_manager.save()
            
            # Construct the final response payload
            full_response = {
                "assistant_response": assistant_response,
                "actions": actions,
                "action_results": action_results,
                "metadata": {
                    "iteration": current_iteration,
                    "max_iterations": max_iterations,
                },
            }

            return full_response, exit_continuation

        except Exception as e:
            error_data = log_error(
                e,
                context={
                    "component": "core",
                    "method": "get_response",
                    "iteration": current_iteration,
                    "max_iterations": max_iterations,
                },
            )
            return {
                "assistant_response": f"I apologize, but an error occurred: {str(e)}",
                "action_results": [],
            }, False

    async def execute_action(self, action) -> Dict[str, Any]:
        """Execute an action and return structured result"""
        try:
            # result = await super().execute_action(action)
            result = await self.action_executor.execute_action(action)
            return {
                "action": action.action_type.value,
                "result": str(result) if result is not None else "",
                "status": "completed",
            }
        except Exception as e:
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "execute_action",
                    "action": action.action_type.value,
                },
            )
            return {
                "action": action.action_type.value,
                "result": f"Error: {str(e)}",
                "status": "error",
            }

    async def reset_state(self):
        """
        Reset the core state completely.
        
        This method performs a more comprehensive reset than reset_context:
        - Resets all conversation state
        - Clears interrupt flags
        - Closes external resources like browser instances
        
        Use this when switching between entirely different tasks or at
        application shutdown.
        """
        self.reset_context()
        self._interrupted = False
        
        # Close browser if it was initialized
        from penguin.tools.browser_tools import browser_manager
        asyncio.create_task(browser_manager.close())
        
    def list_context_files(self) -> List[Dict[str, Any]]:
        """List all available context files"""
        return self.conversation_manager.list_context_files()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
        retry=retry_if_exception_type(Exception),
        retry_error_callback=lambda retry_state: None 
            if isinstance(retry_state.outcome.exception(), KeyboardInterrupt) 
            else retry_state.outcome.exception()
    )
    async def process(
        self,
        input_data: Union[Dict[str, Any], str],
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        max_iterations: int = 5,
        context_files: Optional[List[str]] = None,
        streaming: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Process a message with Penguin.
        
        This method serves as the primary interface for external systems 
        (CLI, API, etc.) to interact with Penguin's capabilities. It handles:
        - Input preprocessing
        - Conversation loading/management
        - Delegating to multi-step processing
        - Error handling and retries
        
        Args:
            input_data: Either a dictionary with a 'text' key or a string message directly
            context: Optional additional context for processing
            conversation_id: Optional ID for conversation continuity
            max_iterations: Maximum reasoning-action cycles (default: 5)
            context_files: Optional list of context files to load
            streaming: Whether to use streaming mode for responses
            
        Returns:
            Dict containing assistant response and action results
        """
        # Handle flexible input format
        if isinstance(input_data, str):
            message = input_data
            image_path = None
        else:
            message = input_data.get("text", "")
            image_path = input_data.get("image_path")
            
        if not message and not image_path:
            return {"assistant_response": "No input provided", "action_results": []}
            
        try:
            # Load conversation if ID provided
            if conversation_id:
                if not self.conversation_manager.load(conversation_id):
                    logger.warning(f"Failed to load conversation {conversation_id}")
                    
            # Load context files if specified
            if context_files:
                for file_path in context_files:
                    self.conversation_manager.load_context_file(file_path)
            
            # Check if we're in run mode by looking at the core state
            in_run_mode = hasattr(self, '_continuous_mode') and self._continuous_mode
            
            # If we're in run mode, bypass multi_step_process
            if in_run_mode:
                # Direct approach for run mode
                self.conversation_manager.conversation.prepare_conversation(message, image_path)
                response, _ = await self.get_response()
                return response
            else:
                # Standard multi-step processing for normal operation
                return await self.multi_step_process(
                    message=message,
                    image_path=image_path,
                    context=context,
                    max_iterations=max_iterations,
                    streaming=streaming
                )
            
        except Exception as e:
            error_msg = f"Error in process method: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            log_error(e, context={"method": "process", "input_data": input_data})
            return {
                "assistant_response": "I apologize, but an error occurred while processing your request.",
                "action_results": [],
                "error": str(e)
            }

    async def multi_step_process(
        self,
        message: str,
        image_path: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 5,
        streaming: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Process a message with multi-step reasoning and action execution.
        
        This method handles the core logic of:
        - Multi-step reasoning
        - Action execution
        - Progress tracking
        
        Args:
            message: The text message to process
            image_path: Optional path to an image to include
            context: Optional additional context for processing
            max_iterations: Maximum reasoning-action cycles
            streaming: Whether to use streaming mode for responses
            
        Returns:
            Dict containing assistant response and action results
        """
        try:
            # Process context if provided
            if context:
                for key, value in context.items():
                    self.conversation_manager.add_context(f"{key}: {value}")
            
            # Multi-step processing loop
            final_response = None
            iterations = 0
            action_results_all = []
            
            # Prepare conversation with user input (only done once)
            self.conversation_manager.conversation.prepare_conversation(message, image_path)
            
            # Multi-step processing loop
            while iterations < max_iterations:
                iterations += 1
                
                # Notify progress callbacks
                self.notify_progress(iterations, max_iterations, f"Processing step {iterations}/{max_iterations}...")
                
                # Get the next response (which may contain actions)
                response_data, exit_continuation = await self.get_response(
                    current_iteration=iterations, 
                    max_iterations=max_iterations
                )
                
                # Extract assistant response and action results
                assistant_response = response_data.get("assistant_response", "")
                current_action_results = response_data.get("action_results", []) # TODO: I wonder if the empty response issue is due to duplicative action results, look into this
                
                # Add action results to overall collection
                action_results_all.extend(current_action_results)
                
                # Check if we should break the loop
                if not parse_action(assistant_response) or exit_continuation or iterations >= max_iterations:
                    final_response = assistant_response
                    break
                    
                # If continuing, notify of next iteration
                self.notify_progress(iterations, max_iterations, "Proceeding to next iteration...")
            
            # Save the final conversation state
            self.conversation_manager.save()
            
            # Return the final response with all action results
            return {
                "assistant_response": final_response if final_response is not None else "",
                "action_results": action_results_all
            }
            
        except Exception as e:
            error_msg = f"Error in multi_step_process method: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            log_error(e, context={"method": "multi_step_process", "message": message})
            return {
                "assistant_response": "I apologize, but an error occurred during multi-step processing.",
                "action_results": [],
                "error": str(e)
            }

    def list_conversations(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """
        List available conversations.
        
        Args:
            limit: Maximum number of conversations to return
            offset: Offset for pagination
            
        Returns:
            List of conversations with metadata
        """
        return self.conversation_manager.list_conversations(limit=limit, offset=offset)
        
    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific conversation by ID.
        
        Args:
            conversation_id: ID of the conversation to retrieve
            
        Returns:
            Conversation data or None if not found
        """
        if self.conversation_manager.load(conversation_id):
            session = self.conversation_manager.get_current_session()
            if not session:
                return None
                
            return {
                "id": session.id,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp
                    }
                    for msg in session.messages
                ],
                "created_at": session.created_at,
                "last_active": session.last_active,
                "metadata": session.metadata
            }
        return None
        
    def create_conversation(self) -> str:
        """
        Create a new conversation.
        
        Returns:
            ID of the new conversation
        """
        return self.conversation_manager.create_new_conversation()
        
    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation.
        
        Args:
            conversation_id: ID of the conversation to delete
            
        Returns:
            True if successful, False otherwise
        """
        return self.conversation_manager.delete_conversation(conversation_id)
        
    def get_conversation_stats(self) -> Dict[str, Any]:
        """
        Get statistics about conversations.
        
        Returns:
            Dictionary with conversation statistics
        """
        return self.conversation_manager.get_session_stats()

    async def start_run_mode(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        continuous: bool = False,
        time_limit: Optional[int] = None,
    ) -> None:
        """
        Start autonomous run mode for executing a task.
        
        Args:
            name: Name of the task (existing or new)
            description: Optional description if creating a new task
            context: Optional additional context or parameters
            continuous: Whether to run in continuous mode
            time_limit: Optional time limit in minutes
        """
        try:
            run_mode = RunMode(self, time_limit=time_limit)
            self._continuous_mode = continuous
            run_mode.continuous_mode = continuous

            # Add run mode start to conversation
            self.conversation_manager.conversation.add_message(
                "system",
                f"Starting {'24/7' if continuous else 'task'} mode: {name if name else 'No specific task'}",
                MessageCategory.SYSTEM
            )

            if continuous:
                await run_mode.start_continuous()
            else:
                await run_mode.start(
                    name=name, description=description, context=context
                )

        except Exception as e:
            # Reset continuous mode and cleanup
            self._continuous_mode = False
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "start_run_mode",
                    "task_name": name,
                    "description": description,
                    "context": context,
                },
            )
            raise
        finally:
            # Ensure state is cleaned up
            if not continuous:
                self._continuous_mode = False
        Path("errors_log").mkdir(exist_ok=True)

        self._continuous_mode = False
        self.run_mode_messages = []
