import os
import time
from openai import OpenAI
from .model_config import ModelConfig
# from .prompts import SYSTEM_PROMPT

class OpenAIAssistantManager:
    def __init__(self, model_config: ModelConfig):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.assistant_id = None
        self.thread_id = None
        self.model_config = model_config
        self._initialize_assistant()

    def _initialize_assistant(self):
        assistants = self.client.beta.assistants.list()
        if assistants.data:
            self.assistant_id = assistants.data[0].id
        else:
            timestamp = int(time.time())
            assistant_name = f"Penguin-{timestamp}-Assistant"
            assistant = self.client.beta.assistants.create(
                model=self.model_config.model,
                name=assistant_name,
                instructions=self.model_config.system_prompt,
            )
            self.assistant_id = assistant.id

    def create_thread(self):
        thread = self.client.beta.threads.create()
        self.thread_id = thread.id

    def add_message_to_thread(self, content):
        if not self.thread_id:
            self.create_thread()
        self.client.beta.threads.messages.create(
            thread_id=self.thread_id,
            role="user",
            content=content
        )

    def run_assistant(self):
        run = self.client.beta.threads.runs.create(
            thread_id=self.thread_id,
            assistant_id=self.assistant_id
        )
        return run

    def get_response(self):
        messages = self.client.beta.threads.messages.list(thread_id=self.thread_id)
        return messages.data[0].content[0].text.value if messages.data else None

    def process_run(self, run):
        while run.status in ['queued', 'in_progress']:
            run = self.client.beta.threads.runs.retrieve(
                thread_id=self.thread_id,
                run_id=run.id
            )
            time.sleep(1)
        
        if run.status == 'completed':
            return self.get_response()
        else:
            return f"Error: Run ended with status {run.status}"
