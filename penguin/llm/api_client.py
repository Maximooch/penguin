from typing import List, Dict, Any
from litellm import completion
from .model_config import ModelConfig
from .provider_adapters import get_provider_adapter
import os
import yaml
from pathlib import Path

def load_config():
    config_path = Path(__file__).parent.parent.parent / 'config.yml'
    with open(config_path, 'r') as config_file:
        return yaml.safe_load(config_file)

MODEL_CONFIGS = load_config().get('model_configs', {})

from PIL import Image 
import base64
import io



class APIClient:
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self.system_prompt = None
        self.adapter = get_provider_adapter(model_config.provider, model_config)
        self.api_key = os.getenv(f"{model_config.provider.upper()}_API_KEY")
        self.max_history_tokens = model_config.max_history_tokens or 1000

    def set_system_prompt(self, prompt):
        self.system_prompt = prompt

    def create_message(self, messages: List[Dict[str, Any]], max_tokens: int = None, temperature: float = None) -> Any:
        try:
            model_specific_config = MODEL_CONFIGS.get(self.model_config.model, {})
            
            if self.adapter.supports_conversation_id():
                if not self.adapter.thread_id:
                    formatted_messages = self.adapter.format_messages(messages)
                else:
                    formatted_messages = self.adapter.format_messages_with_id(self.adapter.thread_id, messages[-1])
            else:
                formatted_messages = self.adapter.format_messages(self._truncate_history(messages))
            
            if self.system_prompt and not self.adapter.supports_conversation_id():
                formatted_messages = [{"role": "system", "content": self.system_prompt}] + formatted_messages

            completion_params = {
                "model": self.model_config.model,
                "messages": formatted_messages,
                "max_tokens": max_tokens or self.model_config.max_tokens or model_specific_config.get('max_tokens'),
                "temperature": temperature or self.model_config.temperature or model_specific_config.get('temperature'),
                "api_key": self.api_key,
                "api_base": self.model_config.api_base or model_specific_config.get('api_base'),
            }

            completion_params = {k: v for k, v in completion_params.items() if v is not None}

            response = self.adapter.process_response(completion_params)

            return response
        except Exception as e:
            raise Exception(f"LiteLLM API error: {str(e)}")

    def _truncate_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        total_tokens = 0
        truncated_messages = []
        for message in reversed(messages):
            message_tokens = self.adapter.count_tokens(str(message.get('content', '')))
            if total_tokens + message_tokens > self.max_history_tokens:
                break
            total_tokens += message_tokens
            truncated_messages.insert(0, message)
        return truncated_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        return self.adapter.process_response(response)

    # def count_tokens(self, text):
    #     # Implement a simple token counting method
    #     return len(text.split()) + len(text) // 4

    def encode_image_to_base64(self, image_path):
        try:
            with Image.open(image_path) as img:
                max_size = (1024, 1024)
                img.thumbnail(max_size, Image.LANCZOS)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG')
                return base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        except Exception as e:
            return f"Error encoding image: {str(e)}"


# class BaseAPIClient:
#     def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
#         raise NotImplementedError

#     def process_response(self, response):
#         raise NotImplementedError

#     def count_tokens(self, text):
#         raise NotImplementedError    

# class OpenAIClient(BaseAPIClient):
#     def __init__(self, api_key: str):
#         openai.api_key = api_key

#     def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
#         try:
#             response = openai.Completion.create(
#                 model=model,
#                 max_tokens=max_tokens,
#                 prompt=system + "\n" + "\n".join([msg["content"] for msg in messages])
#             )
#             return response
#         except Exception as e:
#             raise Exception(f"Error calling OpenAI API: {str(e)}")

#     def process_response(self, response):
#         assistant_response = response.choices[0].text.strip()
#         tool_uses = []  # OpenAI might not have tool uses in the same way
#         return assistant_response, tool_uses

#     def count_tokens(self, text):
#         try:
#             token_count = len(openai.Completion.create(model="text-davinci-003", prompt=text, max_tokens=1).choices[0].logprobs.tokens)
#             return token_count
#         except Exception as e:
#             print(f"Error counting tokens: {str(e)}")
#             return 0


