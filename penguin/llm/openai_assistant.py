import os
import time
from openai import OpenAI
from .model_config import ModelConfig

class OpenAIAssistantManager:
    def __init__(self, model_config: ModelConfig):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.assistant_id = None
        self.model_config = model_config
        self._initialize_assistant()

    def _initialize_assistant(self):
        assistants = self.client.beta.assistants.list()
        if assistants.data:
            self.assistant_id = assistants.data[0].id
        else:
            # Create a new assistant if none exists
            timestamp = int(time.time())
            assistant_name = f"Penguin-{timestamp}-Assistant"
            assistant = self.client.beta.assistants.create(
                model=self.model_config.model,
                name=assistant_name,
                instructions="You are a helpful AI assistant.",
            )
            self.assistant_id = assistant.id

    def get_assistant_id(self):
        return self.assistant_id
