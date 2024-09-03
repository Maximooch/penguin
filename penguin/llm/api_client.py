from typing import List, Dict, Any
from litellm import completion
from .model_config import ModelConfig
from .provider_adapters import LiteLLMAdapter
import os
from PIL import Image 
import base64 
import io

class APIClient:
    def __init__(self, api_key: str, model_config: ModelConfig):
        self.api_key = api_key
        self.model_config = model_config
        self.adapter = LiteLLMAdapter()  # Use the appropriate adapter based on the provider

    def create_message(self, messages: List[Dict[str, Any]], max_tokens: int = None, temperature: float = None) -> Any:
        try:
            formatted_messages = self.adapter.format_messages(messages)
            response = completion(
                model=self.model_config.model,
                messages=formatted_messages,
                max_tokens=max_tokens or self.model_config.max_tokens,
                temperature=temperature or self.model_config.temperature,
                api_key=self.api_key,
                api_base=self.model_config.api_base,
                request_timeout=600,
            )
            # Remove the provider list message entirely
            if isinstance(response, dict) and 'choices' in response:
                content = response['choices'][0]['message']['content']
                if isinstance(content, str):
                    if "Provider List:" in content:
                        content = content.split("Provider List:", 1)[0].strip()
                elif isinstance(content, list):
                    content = [item for item in content if "Provider List:" not in item.get('text', '')]
                response['choices'][0]['message']['content'] = content
            return response
        except Exception as e:
            raise Exception(f"LiteLLM API error: {str(e)}")

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


