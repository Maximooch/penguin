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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

from dotenv import load_dotenv  # type: ignore
from rich.console import Console  # type: ignore
from tenacity import (  # TODO: try this out. # type: ignore
    retry,
    stop_after_attempt,
    wait_exponential,
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
from penguin.workflow_prompt import PENGUIN_WORKFLOW



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
                config=config, api_client=api_client, tool_manager=tool_manager
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
    ):
        """Initialize PenguinCore with required components."""
        self.config = config or Config.load_config()
        self.api_client = api_client
        self.tool_manager = tool_manager
        self._interrupted = False

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

        # Initialize conversation system
        self.conversation_system = ConversationSystem(
            tool_manager=self.tool_manager,
            diagnostics=diagnostics,
            base_path=Path(WORKSPACE_PATH),
        )

        # Initialize action executor with project manager
        self.action_executor = ActionExecutor(
            tool_manager=self.tool_manager, task_manager=self.project_manager
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
        return message

    def _check_interrupt(self) -> bool:
        """Check if execution has been interrupted"""
        return self._interrupted

    async def process_message(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None
    ) -> str:
        """Process a message with optional conversation support and token tracking.

        If a conversation_id is provided, load the corresponding conversation
        so that the new message is appended to its history. Otherwise, a new conversation
        will be started.
        """
        try:
            # Track input tokens for the message.
            diagnostics.update_tokens("main_model", message)
            
            # If a conversation_id is passed, load the existing conversation.
            if conversation_id:
                self.conversation_system.load(conversation_id)
            
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

            # Process response format
            if self.api_client.model_config.use_assistants_api:
                if isinstance(response, dict):
                    assistant_response = response.get("assistant_response", "") or str(response)
                else:
                    assistant_response = str(response)
            else:
                assistant_response = response.choices[0].message.content

            # Count output tokens and update diagnostics
            diagnostics.update_tokens("main_model", "", assistant_response)

            # Check for task completion
            exit_continuation = TASK_COMPLETION_PHRASE in str(assistant_response)

            # Parse actions without executing
            actions = parse_action(assistant_response)

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
                # Also add each tool output as a system message
                for result in action_results:
                    self.conversation_system.add_message("system",
                        f"Action executed: {result['action']}\nResult: {result['result']}"
                    )

            # Update conversation with assistant response and aggregated tool outputs
            full_assistant_response = assistant_response
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
                self.conversation_system.add_message(
                    "system",
                    f"Code saved to: {file_path}"
                )

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
                "assistant_response": "I apologize, but an error occurred. It has been logged for investigation.",
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

    def reset_state(self):
        """Reset the core state"""
        self.messages = []
        self._interrupted = False
        self.conversation_system.reset()
        self.tool_manager.reset()
        self.action_executor.reset()

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
    )
    async def process(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None
    ) -> str:
        """Process a message with optional conversation support.

        When a conversation_id is provided, load the corresponding conversation so that
        new messages are appended to its history. Otherwise, process as a new conversation.
        """
        try:
            # If a conversation ID is provided, load the corresponding conversation.
            if conversation_id:
                self.conversation_system.load(conversation_id)
            
            # Prepare the conversation context with the new message.
            self.conversation_system.prepare_conversation(message)
            
            # Generate response using the associated systems.
            response_data, _ = await self.get_response()
            
            # (Optional) Update or perform any post-processing on the conversation state.
            self.conversation_system.save()
            
            # Format the response based on the type of output received.
            if isinstance(response_data, dict):
                response = response_data.get("assistant_response", "")
            else:
                response = str(response_data)
            
            return response

        except Exception as e:
            log_error(e, context={"method": "process", "message": message, "conversation_id": conversation_id})
            raise
