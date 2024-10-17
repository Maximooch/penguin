from typing import List, Dict, Any
from litellm import completion
from .model_config import ModelConfig
from .provider_adapters import get_provider_adapter
import os
import yaml
from pathlib import Path
import logging
from PIL import Image 
import base64
import io

def load_config() -> Dict[str, Any]:
    """
    Load the configuration from the config.yml file.

    This function reads the config.yml file located two directories up from the current file.
    It uses the yaml library to parse the YAML content into a Python dictionary.

    Returns:
        Dict[str, Any]: A dictionary containing the configuration data.
                        If 'model_configs' key is not present, it returns an empty dictionary for that key.

    Raises:
        FileNotFoundError: If the config.yml file is not found.
        yaml.YAMLError: If there's an error parsing the YAML content.
    """
    config_path = Path(__file__).parent.parent.parent / 'config.yml'
    with open(config_path, 'r') as config_file:
        return yaml.safe_load(config_file)

# Load the model configurations from the config file
MODEL_CONFIGS = load_config().get('model_configs', {})

class APIClient:
    """
    A client for interacting with various AI model APIs.

    This class provides methods to send requests to AI models, process their responses,
    and manage conversation history.

    Attributes:
        model_config (ModelConfig): Configuration for the AI model.
        system_prompt (str): The system prompt to be sent with each request.
        adapter: The provider-specific adapter for formatting messages and processing responses.
        api_key (str): The API key for the model provider.
        max_history_tokens (int): Maximum number of tokens to keep in conversation history.
        logger (logging.Logger): Logger for this class.
    """

    def __init__(self, model_config: ModelConfig):
        """
        Initialize the APIClient.

        Args:
            model_config (ModelConfig): Configuration for the AI model.
        """
        self.model_config = model_config
        self.system_prompt = None
        self.adapter = get_provider_adapter(model_config.provider, model_config)
        self.api_key = os.getenv(f"{model_config.provider.upper()}_API_KEY")
        self.max_history_tokens = model_config.max_history_tokens or 200000 
        # TODO: Make this dynamic based on max_tokens in model_config
        # TODO: Better handling of truncation/chunking
        self.logger = logging.getLogger(__name__)

    def set_system_prompt(self, prompt: str) -> None:
        """
        Set the system prompt to be used in future requests.

        Args:
            prompt (str): The system prompt to set.
        """
        self.system_prompt = prompt

    def create_message(self, messages: List[Dict[str, Any]], max_tokens: int = None, temperature: float = None) -> Any:
        """
        Create a message to send to the AI model.

        This method prepares the message, including the conversation history and system prompt,
        and sends it to the AI model using the litellm library.

        Args:
            messages (List[Dict[str, Any]]): The conversation history.
            max_tokens (int, optional): Maximum number of tokens in the response. Defaults to None.
            temperature (float, optional): Sampling temperature for response generation. Defaults to None.

        Returns:
            Any: The raw response from the AI model.

        Raises:
            Exception: If there's an error in calling the LLM API.
        """
        try:
            # Get model-specific configuration
            model_specific_config = MODEL_CONFIGS.get(self.model_config.model, {})
            
            # Format messages using the provider-specific adapter
            formatted_messages = self.adapter.format_messages(self._truncate_history(messages))
            
            # Add system prompt if it exists
            if self.system_prompt:
                formatted_messages = [{"role": "system", "content": self.system_prompt}] + formatted_messages

            # Prepare parameters for the completion call
            completion_params = {
                "model": self.model_config.model,
                "messages": formatted_messages,
                "max_tokens": max_tokens or self.model_config.max_tokens or model_specific_config.get('max_tokens'),
                "temperature": temperature or self.model_config.temperature or model_specific_config.get('temperature'),
                "api_base": self.model_config.api_base or model_specific_config.get('api_base'),
            }

            # Remove None values from the parameters
            completion_params = {k: v for k, v in completion_params.items() if v is not None}
            
            # Add API key if it exists
            if self.api_key:
                completion_params["api_key"] = self.api_key

            # Make the API call
            response = completion(**completion_params)
            return response

        except Exception as e:
            error_message = f"LLM API error: {str(e)}"
            self.logger.error(error_message)
            raise Exception(error_message)
        
    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """
        Process the raw response from the AI model.

        This method uses the provider-specific adapter to extract the relevant information
        from the API response.

        Args:
            response (Any): The raw response from the AI model.

        Returns:
            tuple[str, List[Any]]: A tuple containing the processed response text and any tool uses.
        """
        return self.adapter.process_response(response)

    def _truncate_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Truncate the conversation history to fit within the maximum token limit.

        This method iterates through the messages in reverse order, adding them to the truncated
        history until the token limit is reached.

        Args:
            messages (List[Dict[str, Any]]): The full conversation history.

        Returns:
            List[Dict[str, Any]]: The truncated conversation history.
        """
        total_tokens = 0
        truncated_messages = []
        for message in reversed(messages):
            message_tokens = self.adapter.count_tokens(str(message.get('content', '')))
            if total_tokens + message_tokens > self.max_history_tokens:
                break
            total_tokens += message_tokens
            truncated_messages.insert(0, message)
        return truncated_messages

    def encode_image_to_base64(self, image_path: str) -> str:
        """
        Encode an image file to a base64 string.

        This method opens an image file, resizes it if necessary, converts it to RGB format,
        and then encodes it to a base64 string.

        Args:
            image_path (str): The path to the image file.

        Returns:
            str: The base64-encoded string of the image, or an error message if encoding fails.
        """
        try:
            with Image.open(image_path) as img:
                # Resize the image if it's larger than 1024x1024
                max_size = (1024, 1024)
                img.thumbnail(max_size, Image.LANCZOS)
                
                # Convert to RGB if it's not already
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Save the image to a bytes buffer
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format='JPEG')
                
                # Encode the image bytes to base64
                return base64.b64encode(img_byte_arr.getvalue()).decode('utf-8')
        except Exception as e:
            return f"Error encoding image: {str(e)}"

# The following code is commented out and represents an older version of the API client.
# It's kept for reference but is not currently in use.
"""
class BaseAPIClient:
    def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
        raise NotImplementedError

    def process_response(self, response):
        raise NotImplementedError

    def count_tokens(self, text):
        raise NotImplementedError    

class OpenAIClient(BaseAPIClient):
    def __init__(self, api_key: str):
        openai.api_key = api_key

    def create_message(self, model, max_tokens, system, messages, tools, tool_choice):
        try:
            response = openai.Completion.create(
                model=model,
                max_tokens=max_tokens,
                prompt=system + "\n" + "\n".join([msg["content"] for msg in messages])
            )
            return response
        except Exception as e:
            raise Exception(f"Error calling OpenAI API: {str(e)}")

    def process_response(self, response):
        assistant_response = response.choices[0].text.strip()
        tool_uses = []  # OpenAI might not have tool uses in the same way
        return assistant_response, tool_uses

    def count_tokens(self, text):
        try:
            token_count = len(openai.Completion.create(model="text-davinci-003", prompt=text, max_tokens=1).choices[0].logprobs.tokens)
            return token_count
        except Exception as e:
            print(f"Error counting tokens: {str(e)}")
            return 0
"""
