"""
PenguinCore acts as the central nervous system for the Penguin AI assistant, orchestrating interactions between various subsystems.

Key Systems:
- Cognition System: Handles reasoning, decision making, and response generation using LLM models
- Conversation System: Manages message history, context tracking, and conversation formatting
- Memory System: Provides persistent storage and retrieval of context, knowledge, and conversation history
- Processor System: Coordinates tool execution and action handling through:
    - Tool Manager: Central registry for available tools and capabilities
    - Action Executor: Routes and executes actions using appropriate handlers
    - Notebook Executor: Manages code execution in IPython environments
- Task System: Handles project and task management, including:
    - Task creation and status tracking
    - Project organization and execution
    - Progress monitoring and reporting
- Diagnostic System: Monitors and reports on:
    - Token usage and costs
    - Performance metrics
    - Error rates and types
    - System health indicators

The core acts as a coordinator rather than implementing functionality directly:
- Maintains overall system state and flow control
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
    __init__(
        config: Optional[Config] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None
    ) -> None:
        Initialize PenguinCore with optional config and components

    async process_message(
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None
    ) -> str:
        Process a user message and return formatted response

    async process_input(
        input_data: Dict[str, Any]
    ) -> None:
        Process structured input data including text/images

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

State Management:
    reset_context() -> None:
        Reset conversation context and diagnostics

    reset_state() -> None:
        Reset core state including messages and tools

    set_system_prompt(prompt: str) -> None:
        Set system prompt for conversation

Properties:
    total_tokens_used -> int:
        Get total tokens used in current session

    get_token_usage() -> Dict[str, Dict[str, int]]:
        Get detailed token usage statistics

Usage:
The core should be initialized with required configuration and subsystems before use.
It provides high-level methods for message processing, task execution, and system control.

Example:
    core = PenguinCore(config=config)
    response = await core.process_message("Hello!")
    await core.start_run_mode(name="coding_task")
"""

# test

# TODO: Have conversation loading things here.
# Conversation.py should or may have something similar to OpenAI's threads. Long term thing.

# TODO: Some sort of interface to support things beyond CLI. Web, Core-library, etc.

import logging
import time
import traceback
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, Callable
import asyncio

from dotenv import load_dotenv  # type: ignore
from rich.console import Console  # type: ignore
from tenacity import (  # TODO: try this out. # type: ignore
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from tqdm import tqdm

from penguin.cognition.cognition import CognitionSystem

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
from penguin.system.conversation import ConversationSystem

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
            config = config or Config.load_config()

            # Initialize model configuration
            model_config = ModelConfig(
                model=model or DEFAULT_MODEL,  # Use default if not provided
                provider=provider or DEFAULT_PROVIDER,
                api_base=config.api.base_url,
                use_assistants_api=False,  # Default to False
            )

            # Create API client
            api_client = APIClient(model_config=model_config)
            api_client.set_system_prompt(SYSTEM_PROMPT)

            # Initialize tool manager
            tool_manager = ToolManager(log_error)

            # Create core instance
            instance = cls(
                config=config, api_client=api_client, tool_manager=tool_manager, model_config=model_config
            )

            if enable_cli:
                # Import CLI only when needed
                from chat.cli import PenguinCLI

                cli = PenguinCLI(instance)

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
        model_config=None,
    ):
        """Initialize PenguinCore with required components."""
        self.config = config or Config.load_config()
        self.api_client = api_client
        self.tool_manager = tool_manager
        self._interrupted = False
        self.progress_callbacks = []
        self.token_callbacks = []
        self._active_contexts = set()  # Track active execution contexts

        # Set system prompt from import
        self.system_prompt = SYSTEM_PROMPT

        # Initialize project manager with workspace path from config
        self.project_manager = ProjectManager(workspace_root=WORKSPACE_PATH)

        # Initialize diagnostics based on config
        # Don't touch this file in edits!
        # Don't touch this file in edits!
        if not self.config.diagnostics.enabled:
            disable_diagnostics()
        # Why is it initializing tool manager, diagnostics, and base_path here?

        # Initialize conversation system with token budgeting
        self.conversation_system = ConversationSystem(
            tool_manager=self.tool_manager,
            diagnostics=diagnostics,
            base_path=Path(WORKSPACE_PATH),
            model_config=model_config
        )

        # Initialize action executor with project manager
        self.action_executor = ActionExecutor(
            tool_manager=self.tool_manager, 
            task_manager=self.project_manager,
            conversation_system=self.conversation_system
        )
        # It's not really using api_client, seems like a duplication, until it's actually used.
        self.messages = []

        # Initialize core systems
        self.cognition = CognitionSystem(
            api_client=self.api_client, diagnostics=diagnostics
        )

        # State
        self.initialized = True
        logger.info("PenguinCore initialized successfully")

        # Ensure error log directory exists
        self.validate_path(Path(WORKSPACE_PATH))

        # Add an accumulated token counter
        self.accumulated_tokens = {"prompt": 0, "completion": 0, "total": 0}

    def validate_path(self, path: Path):
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.W_OK):
            raise PermissionError(f"No write access to {path}")

    def _setup_diagnostics(self):
        """Initialize diagnostics based on config"""
        if self.config.diagnostics.enabled:
            enable_diagnostics()
            if self.config.diagnostics.log_to_file and self.config.diagnostics.log_path:
                # Setup file logging if configured
                log_path = Path(self.config.diagnostics.log_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                logging.basicConfig(
                    filename=str(log_path),
                    level=logging.WARNING,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                )
        else:
            disable_diagnostics()

    def register_progress_callback(self, callback: Callable[[int, int, Optional[str]], None]) -> None:
        """Register a callback for progress updates during multi-step processing.
        
        Args:
            callback: Function that takes (iteration, max_iterations, message) as parameters
        """
        self.progress_callbacks.append(callback)

    def notify_progress(self, iteration: int, max_iterations: int, message: Optional[str] = None) -> None:
        """Notify all registered callbacks about progress.
        
        Args:
            iteration: Current iteration number
            max_iterations: Maximum number of iterations
            message: Optional status message
        """
        for callback in self.progress_callbacks:
            callback(iteration, max_iterations, message)

    def reset_context(self):
        """Reset context and diagnostics"""
        # What if this wasn't reset at the end of every session, to help with long term memory?
        diagnostics.reset()
        self.messages = []
        self._interrupted = False
        self.conversation_system.reset()
        if self.tool_manager:
            self.tool_manager.reset()
        if self.action_executor:
            self.action_executor.reset()

    @property
    def total_tokens_used(self) -> int:
        """Get total tokens used in current session"""
        return diagnostics.get_total_tokens()

    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        """Get detailed token usage statistics"""
        return {
            name: tracker.tokens.copy()
            for name, tracker in diagnostics.token_trackers.items()
        }

    def prepare_conversation(
        self, message: str, tool_outputs: Optional[List[Dict[str, Any]]] = None
    ):
        """Prepare conversation context with tool outputs"""
        self.add_message("user", message)
        if tool_outputs:
            tool_output_text = "\n".join(
                f"{output['action']}: {output['result']}" for output in tool_outputs
            )
            self.add_message("system", f"Tool outputs:\n{tool_output_text}")

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt for both core and API client."""
        self.system_prompt = prompt
        if self.api_client:
            self.api_client.set_system_prompt(prompt)

    def get_system_message(
        self,
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None,
    ) -> str:
        """Get the system message including iteration info if provided."""
        message = self.system_prompt
        if current_iteration is not None and max_iterations is not None:
            message += f"\n\nCurrent iteration: {current_iteration}/{max_iterations}"
            if current_iteration > 1:
                message += "\nYou are in a multi-step reasoning process. Review the action results from your previous steps and decide what to do next. You can take additional actions or provide a final response."
            else:
                message += "\nYou are starting a multi-step reasoning process. You can analyze the user's request and take actions, then review the results to determine next steps."
        return message

    def _check_interrupt(self) -> bool:
        """Check if execution has been interrupted"""
        return self._interrupted

    async def process_message(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        context_files: Optional[List[str]] = None
    ) -> str:
        """Process a message with optional conversation support and token tracking.

        If a conversation_id is provided, load the corresponding conversation
        so that the new message is appended to its history. Otherwise, a new conversation
        will be started.
        
        Args:
            message: The user message to process
            context: Optional additional context for processing
            conversation_id: Optional ID to continue an existing conversation
            context_files: Optional list of context files to load before processing
        """
        try:
            # Track input tokens for the message.
            diagnostics.update_tokens("main_model", message)
            
            # If a conversation_id is passed, load the existing conversation.
            if conversation_id:
                self.conversation_system.load(conversation_id)
            
            # Load additional context files if provided
            if context_files:
                loaded_files = []
                for file_path in context_files:
                    success = self.conversation_system.load_context_file(file_path)
                    if success:
                        loaded_files.append(file_path)
                        
                if loaded_files:
                    logger.info(f"Loaded {len(loaded_files)} context files before processing message")
            
            # Prepare the conversation context by adding the new user message.
            self.conversation_system.prepare_conversation(message)
            
            # Obtain the assistant's response including tool outputs.
            response_data, _ = await self.get_response()
            
            # Format the final response.
            if isinstance(response_data, dict):
                response = response_data.get("assistant_response", "")
                action_results = response_data.get("action_results", [])
                formatted_response = response + "\n\n"
                if action_results:
                    formatted_response += "Tool outputs:\n"
                    for result in action_results:
                        formatted_response += f"- {result['action']}: {result['result']}\n"
            else:
                formatted_response = str(response_data)
            
            # Update diagnostic tokens for the response.
            diagnostics.update_tokens("main_model", "", formatted_response)
            diagnostics.log_token_usage()

            # Save the updated conversation state.
            self.conversation_system.save()
            
            return formatted_response
        except Exception as e:
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "process_message",
                    "message": message,
                    "context": context,
                    "conversation_id": conversation_id,
                },
            )
            raise

    async def process_input(self, input_data: Dict[str, Any]) -> None:
        """Process user input and update token count"""
        try:
            # Count input tokens
            if "text" in input_data:
                diagnostics.update_tokens("main_model", input_data["text"])

            # Extract input parameters
            user_input = input_data.get("text", "")
            image_path = input_data.get("image_path")

            # Prepare conversation context
            self.conversation_system.prepare_conversation(user_input, image_path)

        except Exception as e:
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "process_input",
                    "input_data": input_data,
                },
            )
            raise

    async def process_input_with_image(self, input_data: Dict) -> None:
        try:
            user_input = input_data.get("text", "")
            image_path = input_data.get("image_path")

            if image_path:
                base64_image = self.tool_manager.encode_image(image_path)
                message_content = [
                    {"type": "text", "text": user_input},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    },
                ]
            else:
                message_content = user_input

            response = self.api_client.create_message(
                messages=[{"role": "user", "content": message_content}]
            )

            # Process the response...

        except Exception as e:
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "process_input_with_image",
                    "input_data": input_data,
                },
            )
            raise

    async def get_response(
        self,
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Generate a response using the current conversation context.

        This method handles the LLM interaction and response processing,
        ensuring that tool execution is properly isolated.

        Returns:
            Tuple[Dict[str, Any], bool]: Response data and continuation flag
        """
        try:
            # Get raw response through API
            response = await self.api_client.create_message(
                messages=self.conversation_system.get_history(),
                max_tokens=None,
                temperature=None,
            )
            logger.debug(f"Raw API response: {response}")

            # Modified response handling
            assistant_response = None
            if response and hasattr(response, 'choices') and response.choices:
                assistant_response = response.choices[0].message.content
            elif isinstance(response, dict):
                assistant_response = response.get('assistant_response', '')
            
            # Remove empty response logging
            if not assistant_response:
                pass  # No longer log empty responses

            # Update token tracking only for non-empty content
            if assistant_response:
                diagnostics.update_tokens("main_model", "", assistant_response)

            # Check for task completion
            exit_continuation = TASK_COMPLETION_PHRASE in str(assistant_response or "")

            # Parse actions without executing
            # Add null check to handle None responses
            actions = parse_action(assistant_response) if assistant_response is not None else []

            # Execute actions with interrupt checking
            action_results = []
            for action in actions:
                if self._check_interrupt():
                    action_results.append(
                        {
                            "action": action.action_type.value,
                            "result": "Action skipped due to interrupt",
                            "status": "interrupted",
                        }
                    )
                    continue

                try:
                    result = await self.action_executor.execute_action(action)
                    if result is not None:
                        action_results.append(
                            {
                                "action": action.action_type.value,
                                "result": str(result),
                                "status": "completed",
                            }
                        )
                except Exception as e:
                    action_results.append(
                        {
                            "action": action.action_type.value,
                            "result": f"Error executing action: {str(e)}",
                            "status": "error",
                        }
                    )
                    logger.error(f"Action execution error: {str(e)}")

            # If execution was interrupted, return an early response
            if self._check_interrupt():
                aggregated = "Operation interrupted during action execution"
                return {
                    "assistant_response": aggregated,
                    "action_results": action_results,
                    "metadata": {
                        "interrupted": True,
                        "completed_actions": len([a for a in action_results if a["status"] == "completed"]),
                    },
                }, True

            # Aggregate tool action results into a readable block
            aggregated_tool_outputs = ""
            if action_results:
                lines = [f"- {r['action']}: {r['result']}" for r in action_results]
                aggregated_tool_outputs = "Tool outputs:\n" + "\n".join(lines)
                # Also add each tool output as an action result
                for result in action_results:
                    self.conversation_system.add_action_result(
                        action_type=result['action'],
                        result=result['result'],
                        status=result.get('status', 'completed')
                    )

            # Update conversation with assistant response and aggregated tool outputs
            full_assistant_response = assistant_response if assistant_response is not None else "No response generated"
            if aggregated_tool_outputs:
                full_assistant_response += "\n\n" + aggregated_tool_outputs
            self.conversation_system.add_message("assistant", full_assistant_response)

            # Construct the final response payload
            full_response = {
                "assistant_response": full_assistant_response,
                "action_results": action_results,
                "metadata": {
                    "iteration": current_iteration,
                    "max_iterations": max_iterations,
                },
            }

            diagnostics.log_token_usage()

            # Update task progress
            # await self._update_task_progress(assistant_response)

            # Add automatic code saving
            code_actions = [a for a in action_results if a['action'] == 'execute_code']
            for code_action in code_actions:
                file_path = Path(WORKSPACE_PATH) / f"generated_{int(time.time())}.py"
                file_path.write_text(code_action['result'])
                self.conversation_system.add_action_result(
                    action_type="save_code",
                    result=f"Code saved to: {file_path}"
                )

            # Add this before returning
            self._notify_token_usage()

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
        """Reset the core state"""
        self.messages = []
        self._interrupted = False
        self.conversation_system.reset()
        self.tool_manager.reset()
        self.action_executor.reset()
        
        # Close browser if it was initialized
        from penguin.tools.browser_tools import browser_manager
        asyncio.create_task(browser_manager.close())
        
    def list_context_files(self) -> List[Dict[str, Any]]:
        """List all available context files"""
        return self.conversation_system.list_context_files()

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
            self.conversation_system.add_message(
                "system",
                f"Starting {'24/7' if continuous else 'task'} mode: {name if name else 'No specific task'}",
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
        retry=retry_if_exception_type(Exception),
        retry_error_callback=lambda retry_state: None if isinstance(retry_state.outcome.exception(), KeyboardInterrupt) else retry_state.outcome.exception()
    )
    async def process(
        self,
        input_data: Union[Dict[str, Any], str],
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        max_iterations: int = 5,  # Prevent infinite loops
        context_files: Optional[List[str]] = None  # Context files to load
    ) -> Dict[str, Any]:
        """Process a message with multi-step reasoning and action execution.
        
        This method implements a reasoning-action loop that allows Penguin to:
        1. Generate a response and identify actions
        2. Execute those actions
        3. Analyze the results
        4. Decide whether to take more actions or provide a final response
        
        Args:
            input_data: Either a dictionary with a 'text' key or a string message directly
            context: Optional additional context for processing
            conversation_id: Optional ID for conversation continuity
            max_iterations: Maximum reasoning-action cycles (default: 5)
        
        Returns:
            Dict containing assistant response and action results
        """
        try:
            # Handle flexible input - accept either string or dict
            if isinstance(input_data, str):
                message = input_data
            else:
                message = input_data.get("text", "")
            
            if not message:
                return {"assistant_response": "No input provided", "action_results": []}
            
            # If a conversation ID is provided, load the corresponding conversation.
            if conversation_id:
                self.conversation_system.load(conversation_id)
                
            # Load additional context files if provided
            if context_files:
                loaded_files = []
                for file_path in context_files:
                    success = self.conversation_system.load_context_file(file_path)
                    if success:
                        loaded_files.append(file_path)
                        
                if loaded_files:
                    logger.info(f"Loaded {len(loaded_files)} context files before processing message")
            
            # Prepare the conversation context with the new message.
            self.conversation_system.prepare_conversation(message)
            
            # Add token notifications after key operations
            self._notify_token_usage()  # After processing input
            
            # Rest of the method remains unchanged
            final_response = None
            iterations = 0
            action_results_all = []
            
            # Multi-step processing loop
            while iterations < max_iterations:
                iterations += 1
                
                # Notify progress callbacks with more detailed status
                status_message = f"Processing step {iterations}/{max_iterations}..."
                self.notify_progress(iterations, max_iterations, status_message)
                logger.debug(status_message)
                
                # Add iteration marker to conversation
                self.conversation_system.add_iteration_marker(iterations, max_iterations)
                
                # Get the next response (which may contain actions)
                try:
                    response_data, exit_continuation = await self.get_response(
                        current_iteration=iterations, 
                        max_iterations=max_iterations
                    )
                    
                    # Extract the assistant's response text
                    assistant_response = response_data.get("assistant_response", "")
                    current_action_results = response_data.get("action_results", [])
                    
                    # Add action results to the overall collection
                    action_results_all.extend(current_action_results)
                    
                    # Modified response validation
                    if not assistant_response:
                        logger.warning("Empty response received from API")
                        break  # Continue processing with available data
                    
                    # Parse any actions in the response
                    actions = parse_action(assistant_response)
                    logger.debug(f"Iteration {iterations}: Found {len(actions)} actions")
                    
                    # Break conditions - this is the key fix: more explicit logging and checks
                    should_break = False
                    break_reason = ""
                    
                    if not actions:
                        break_reason = "No actions found in response"
                        should_break = True
                    elif exit_continuation:
                        break_reason = "Exit continuation flag is set"
                        should_break = True
                    elif iterations >= max_iterations:
                        break_reason = "Maximum iterations reached"
                        should_break = True
                        
                    if should_break:
                        logger.debug(f"Breaking loop: {break_reason}")
                        self.notify_progress(iterations, max_iterations, f"Finalizing: {break_reason}")
                        final_response = assistant_response
                        break
                    
                    # If we're continuing, notify of action execution
                    if actions:
                        self.notify_progress(iterations, max_iterations, f"Executing {len(actions)} actions...")
                    
                    # Add action results to conversation for the next iteration
                    if current_action_results:
                        result_message = "\n".join([
                            f"Action: {r['action']}\nResult: {r['result']}\nStatus: {r['status']}"
                            for r in current_action_results
                        ])
                        self.conversation_system.add_message(
                            "system", 
                            f"Action Results:\n{result_message}"
                        )
                except Exception as e:
                    logger.error(f"Error in iteration {iterations}: {str(e)}")
                    self.notify_progress(iterations, max_iterations, "Error in processing")
                    # Add error to conversation
                    self.conversation_system.add_message(
                        "system",
                        f"Error in processing: {str(e)}"
                    )
                    # Break the loop on error
                    final_response = f"I encountered an error during processing: {str(e)}"
                    break
            
            # Save the final conversation state
            self.conversation_system.save()
            
            # Final progress notification for completion
            final_message = "Finalizing: Processing complete"
            self.notify_progress(max_iterations, max_iterations, final_message)
            self._notify_token_usage()
            
            # Return the final response with all action results
            return {
                "assistant_response": final_response if final_response is not None else "",
                "action_results": action_results_all
            }
            
        except Exception as e:
            error_msg = f"Error in process method: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            log_error(e, context={"method": "process", "input_data": input_data, "conversation_id": conversation_id})
            self._notify_token_usage()  # Notify even on error
            return {
                "assistant_response": "I apologize, but an error occurred while processing your request.",
                "action_results": [],
                "error": str(e)
            }

    def register_token_callback(self, callback: Callable[[Dict[str, int]], None]) -> None:
        """Register a callback for token usage updates.
        
        Args:
            callback: Function that takes a token usage dictionary as a parameter
        """
        print(f"[Core] Registering token callback: {callback.__qualname__ if hasattr(callback, '__qualname__') else callback}")
        self.token_callbacks.append(callback)

    def _notify_token_usage(self):
        """Notify all registered callbacks using conversation system token budgeting."""
        try:
            # Get token usage directly from conversation system
            usage = self.conversation_system.get_current_token_usage()
            
            for callback in self.token_callbacks:
                try:
                    callback(usage)
                except Exception as e:
                    logger.error(f"Error in token callback: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error in _notify_token_usage: {str(e)}")
