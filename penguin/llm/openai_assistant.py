import time

# Import necessary modules from litellm
import litellm
from litellm import (
    add_message,
    create_thread,
    get_assistants,
    run_thread,
)

from .model_config import ModelConfig


class OpenAIAssistantManager:
    def __init__(self, model_config: ModelConfig):
        self.assistant_id = None
        self.thread_id = None
        self.model_config = model_config
        self._initialize_assistant()

    def _initialize_assistant(self):
        try:
            print("\n=== Assistant Initialization Details ===")
            print(f"Model: {self.model_config.model}")

            if not self.model_config.model.startswith(
                "gpt-4"
            ) and not self.model_config.model.startswith("gpt-3.5"):
                raise ValueError(
                    f"Model {self.model_config.model} is not supported for Assistants API. Must be gpt-4* or gpt-3.5*"
                )

            # Use configured assistant ID if available
            if (
                hasattr(self.model_config, "assistant_id")
                and self.model_config.assistant_id
            ):
                self.assistant_id = self.model_config.assistant_id
                print(f"Using configured assistant with ID: {self.assistant_id}")
                return

            # Fallback to existing logic if no configured ID
            try:
                assistants_page = get_assistants(custom_llm_provider="openai")
                assistants = assistants_page.data
                print(f"Found existing assistants: {assistants}")

                # Find most recent Penguin assistant
                penguin_assistant = None
                for assistant in assistants:
                    if assistant.name.startswith("Penguin-"):
                        if (
                            not penguin_assistant
                            or assistant.created_at > penguin_assistant.created_at
                        ):
                            penguin_assistant = assistant

                if penguin_assistant:
                    self.assistant_id = penguin_assistant.id
                    print(
                        f"Using existing Penguin assistant with ID: {self.assistant_id}"
                    )
                else:
                    self._create_new_assistant()

            except Exception as api_error:
                raise ValueError(f"Failed to get assistants list: {str(api_error)}")
        except Exception as e:
            print(f"Error initializing OpenAI Assistant: {str(e)}")
            print("Stack trace:", e.__traceback__)
            raise

    def _create_new_assistant(self):
        timestamp = int(time.time())
        assistant_name = f"Penguin-{timestamp}-Assistant"
        print(f"Creating new assistant: {assistant_name}")
        assistant = litellm.create_assistants(
            model=self.model_config.model,
            name=assistant_name,
            instructions="You are a helpful AI assistant.",  # Basic default instruction
            tools=[],
            custom_llm_provider="openai",
        )
        self.assistant_id = assistant.id
        print(f"Created new assistant with ID: {self.assistant_id}")

    def create_thread(self):
        """Create a new thread with the required provider"""
        thread = create_thread(custom_llm_provider="openai")
        self.thread_id = thread.id

    def add_message_to_thread(self, content: str):
        """Add a message to the thread"""
        if not self.thread_id:
            self.create_thread()
        add_message(
            thread_id=self.thread_id,
            role="user",
            content=content,
            custom_llm_provider="openai",
        )

    def run_assistant(self):
        """Run the assistant on the current thread"""
        run = run_thread(
            thread_id=self.thread_id,
            assistant_id=self.assistant_id,
            instructions=self.current_instructions
            if hasattr(self, "current_instructions")
            else None,
            custom_llm_provider="openai",
        )
        return run

    def get_response(self):
        """Get the latest response from the thread"""
        try:
            messages = litellm.get_messages(
                thread_id=self.thread_id, custom_llm_provider="openai"
            )

            if not messages or not messages.data:
                print("No messages found in thread")
                return None

            print(f"Found {len(messages.data)} messages in thread")

            # Get the latest run's assistant message
            latest_assistant_message = None
            for message in messages.data:
                if message.role == "assistant":
                    latest_assistant_message = message
                    break  # Get the first (most recent) assistant message

            if latest_assistant_message and latest_assistant_message.content:
                for content in latest_assistant_message.content:
                    if content.type == "text":
                        return content.text.value

            print("No valid assistant message found")
            return None

        except Exception as e:
            print(f"Error getting response: {str(e)}")
            return None

    def process_run(self, run):
        """Process the run until completion and return the response"""
        try:
            while run.status in ["queued", "in_progress"]:
                print(f"Run status: {run.status}. Waiting...")
                time.sleep(1)
                run = litellm.get_run(
                    thread_id=self.thread_id,
                    run_id=run.id,
                    custom_llm_provider="openai",
                )

            print(f"Final run status: {run.status}")
            if run.status == "completed":
                response = self.get_response()
                if response:
                    print(f"Got response: {response[:100]}...")  # Print first 100 chars
                    return response
                else:
                    error_msg = "Error: No valid response found"
                    print(error_msg)
                    return error_msg
            else:
                error_msg = f"Error: Run ended with status {run.status}"
                print(error_msg)
                return error_msg

        except Exception as e:
            error_msg = f"Error processing run: {str(e)}"
            print(error_msg)
            return error_msg

    def update_system_prompt(self, system_prompt: str):
        """Store the system prompt for use in runs"""
        if not system_prompt:
            print("Warning: Empty system prompt provided")
            return

        self.current_instructions = system_prompt
        print("Updated system instructions for future runs")
