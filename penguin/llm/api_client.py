from anthropic import Anthropic
from .model_config import ModelConfig
from PIL import Image
import io
import base64

class ClaudeAPIClient:
    def __init__(self, api_key: str, model_config: ModelConfig):
        self.client = Anthropic(api_key=api_key)
        self.model_config = model_config

    def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice
            )
            return response
        except Exception as e:
            raise Exception(f"Error calling Claude API: {str(e)}")

    def process_response(self, response):
        assistant_response = ""
        tool_uses = []
        
        for content_block in response.content:
            if content_block.type == "text":
                assistant_response += content_block.text
            elif content_block.type == "tool_use":
                tool_uses.append({
                    "name": content_block.name,
                    "input": content_block.input,
                    "id": content_block.id
                })
        
        return assistant_response, tool_uses

    def encode_image_to_base64(self, image_path):
        try:
            with Image.open(image_path) as img:
                max_size = (1024, 1024)
                img.thumbnail(max_size, Image.DEFAULT_STRATEGY)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG')
                return base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        except Exception as e:
            return f"Error encoding image: {str(e)}"

# Example usage:
# model_config = ModelConfig()
# api_client = ClaudeAPIClient("your-api-key-here", model_config)
# response = api_client.create_message(
#     model=model_config.model,
#     max_tokens=model_config.max_tokens,
#     system="You are a helpful AI assistant.",
#     messages=[{"role": "user", "content": "Hello, how are you?"}],
#     tools=[],
#     tool_choice={"type": "auto"}
# )
# assistant_response, tool_uses = api_client.process_response(response)
# print(assistant_response)
# print(tool_uses)