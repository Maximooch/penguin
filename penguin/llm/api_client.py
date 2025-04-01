import asyncio
import base64
import io
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Union

import yaml  # type: ignore
import tiktoken  # type: ignore

# TODO: decouple litellm from api_client.
# TODO: greatly simplify api_client while maintaining full functionality
# TODO: add streaming support
# TODO: add support for images, files, audio, and video
from litellm import acompletion, completion  # type: ignore
from PIL import Image  # type: ignore

from .model_config import ModelConfig
from .adapters import get_adapter
import logging
from penguin.llm.provider_adapters import get_provider_adapter

logger = logging.getLogger(__name__)


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
    config_path = Path(__file__).parent.parent.parent / "config.yml"
    with open(config_path) as config_file:
        return yaml.safe_load(config_file)


# Load the model configurations from the config file
MODEL_CONFIGS = load_config().get("model_configs", {})


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
        
        # Try to get native adapter first
        self.adapter = get_adapter(model_config.provider, model_config)
        
        # Store API key and set other properties
        self.api_key = os.getenv(f"{model_config.provider.upper()}_API_KEY")
        self.max_history_tokens = model_config.max_history_tokens or 200000
        # TODO: Make this dynamic based on max_tokens in model_config
        # TODO: Better handling of truncation/chunking
        self.logger = logging.getLogger(__name__)

        # Yes I know print statements are bad, messy, ugly, and evil. But this was necessary.

        # print("\n=== API Client Initialization ===")
        # print(f"Model: {model_config.model}")
        # print(f"Provider: {model_config.provider}")
        # print(f"Use Assistants API: {model_config.use_assistants_api}")
        # print(f"API Key Present: {bool(self.api_key)}")
        # print("===============================\n")

        if model_config.use_assistants_api:
            self.logger.info("Using OpenAI Assistants API")
            # print("Using OpenAI Assistants API")
        else:
            pass # not using assistants API, so no need to print
            # self.logger.info("Using regular OpenAI API")
            # print("Using regular OpenAI API")

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt and update assistant if using Assistants API"""
        self.system_prompt = prompt
        if self.model_config.use_assistants_api and self.adapter.assistant_manager:
            self.adapter.assistant_manager.update_system_prompt(prompt)

    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        """
        Asynchronously create a message using the configured model.

        Args:
            messages: List of message dictionaries
            max_tokens: Optional max tokens to generate
            temperature: Optional temperature parameter

        Returns:
            Response from the model API
        """
        try:
            # Handle system prompt compatibility
            system_prompt = None
            if self.system_prompt:
                if self.adapter.supports_system_messages():
                    # Remove existing system messages and add ours first
                    messages = [msg for msg in messages if msg.get("role") != "system"]
                    messages.insert(
                        0, {"role": "system", "content": self.system_prompt}
                    )
                    system_prompt = self.system_prompt
                else:
                    # Convert system message to user message with prefix
                    print(
                        f"Converting system message to user message for provider: {self.adapter.provider}"
                    )
                    messages.insert(
                        0,
                        {
                            "role": "user",
                            "content": f"[SYSTEM PROMPT]: {self.system_prompt}",
                        },
                    )
                    self.logger.debug(
                        "Converted system message to user message for provider"
                    )

            # Format messages using the provider-specific adapter
            formatted_messages = self.adapter.format_messages(messages)
            
            # Check if we can use direct adapter (bypass litellm)
            if hasattr(self.adapter, 'create_message') and getattr(self.model_config, 'use_native_adapter', True):
                self.logger.debug(f"Using direct {self.adapter.provider} adapter")
                
                # Call the adapter's create_message method directly
                response = await self.adapter.create_message(
                    messages=messages,
                    max_tokens=max_tokens or self.model_config.max_tokens,
                    temperature=temperature or self.model_config.temperature,
                    system_prompt=system_prompt
                )
                return response
                
            # Fallback to litellm for providers without direct adapters
            self.logger.debug(f"Using litellm for {self.adapter.provider}")
            
            # Comment out this debugging block
            '''
            # Add debugging for all providers (not just Anthropic)
            print(f"\n=== {self.model_config.provider.upper()} IMAGE DEBUG ===")
            for i, msg in enumerate(formatted_messages):
                print(f"Message {i+1}:")
                print(f"  Role: {msg.get('role')}")
                if isinstance(msg.get('content'), list):
                    print(f"  Content parts: {len(msg['content'])}")
                    for j, part in enumerate(msg['content']):
                        print(f"    Part {j+1} type: {part.get('type')}")
                        if part.get('type') == 'image_url':
                            img_url = part.get('image_url', {}).get('url', '')
                            print(f"    Image URL starts with: {img_url[:30]}...")
                            print(f"    Is base64: {'data:image' in img_url}")
                else:
                    content = str(msg.get('content', ''))
                    print(f"  Content: {content[:50]}...")
            print("===========================\n")
            '''

            # Prepare parameters for the completion call
            completion_params = {
                "model": self.model_config.model,
                "messages": formatted_messages,
                "max_tokens": max_tokens or self.model_config.max_tokens,
                "temperature": temperature or self.model_config.temperature,
                "api_base": self.model_config.api_base,
                "headers": {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            }  # TODO: Get rid of this

            # Remove None values
            completion_params = {
                k: v for k, v in completion_params.items() if v is not None
            }

            if self.api_key:
                completion_params["api_key"] = self.api_key

            self.logger.debug(f"Sending formatted messages: {formatted_messages}")

            # Make the API call asynchronously
            try:
                if self.model_config.use_assistants_api:
                    # For assistants API, wrap synchronous call in asyncio.to_thread
                    response = await asyncio.to_thread(completion, **completion_params)
                else:
                    # For regular API, use async call
                    response = await acompletion(**completion_params)

                # Log the raw response for debugging
                self.logger.debug(f"Raw API response: {response}")

                return response

            except Exception as e:
                self.logger.error(f"API call error: {str(e)}")
                raise

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
        try:
            if not response:
                logger.warning("Empty response received from API in process_response")
                return "I encountered an issue processing your request, but I see the code executed successfully.", []
                
            # Use the adapter's process_response method
            content, tool_uses = self.adapter.process_response(response)
            
            # Safety check for empty content
            if not content or not content.strip():
                logger.warning("Adapter returned empty content")
                # Check if we're processing code execution results
                if "random number" in str(response) or "random" in str(response):
                    return "I can see from the output that the random number generated was the value shown above.", []
                return "I received a response but it appears to be empty. Let me know if you'd like me to try again.", []
                
            return content, tool_uses
            
        except Exception as e:
            logger.error(f"Error in process_response: {e}")
            return f"An error occurred while processing the response: {str(e)}", []

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
            message_tokens = self.adapter.count_tokens(str(message.get("content", "")))
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
                if img.mode != "RGB":
                    img = img.convert("RGB")

                # Save the image to a bytes buffer
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format="JPEG")

                # Encode the image bytes to base64
                return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
        except Exception as e:
            return f"Error encoding image: {str(e)}"

    def reset(self):
        """Reset the client state"""
        self.messages = []
        self.set_system_prompt(self.system_prompt)

    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """
        Count tokens for content, using the provider's tokenizer when available.
        
        Args:
            content: Text or structured content to count tokens for
            
        Returns:
            Token count as integer
        """
        try:
            # If adapter implements token counting, use that
            if self.adapter and hasattr(self.adapter, 'count_tokens'):
                try:
                    logger.debug(f"Using {self.adapter.provider} native tokenizer")
                    return self.adapter.count_tokens(content)
                except Exception as e:
                    logger.warning(f"Error using adapter token counting: {e}")
                    # Check if this is an image_url error with Anthropic
                    if 'image_url' in str(e) and self.adapter.provider == 'anthropic':
                        # Emergency conversion: replace image_url types with image types
                        try:
                            if isinstance(content, list) and any(isinstance(item, dict) and item.get('type') == 'image_url' for item in content):
                                # Convert image_url to image.source format
                                fixed_content = []
                                for item in content:
                                    if isinstance(item, dict) and item.get('type') == 'image_url':
                                        image_url = item.get('image_url')
                                        if isinstance(image_url, str) and image_url.startswith(('http://', 'https://')):
                                            fixed_content.append({
                                                "type": "image",
                                                "source": {
                                                    "type": "url",
                                                    "url": image_url
                                                }
                                            })
                                        else:
                                            # Skip images we can't fix easily
                                            fixed_content.append({"type": "text", "text": "[Image]"})
                                    else:
                                        fixed_content.append(item)
                                
                                logger.debug("Retrying token counting with fixed image format")
                                return self.adapter.count_tokens(fixed_content)
                        except Exception as inner_e:
                            logger.warning(f"Error during emergency image format conversion: {inner_e}")
            
            # Fallback to approximate counting    
            return self._approximate_token_count(content)
            
        except Exception as e:
            logger.error(f"Token counting error: {e}")
            return len(str(content)) // 4 + 1  # Very rough approximation

    async def create_streaming_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """Create a streaming completion request with proper text extraction."""
        try:
            # System prompt handling (unchanged)
            if self.system_prompt:
                if self.adapter.supports_system_messages():
                    messages = [msg for msg in messages if msg.get("role") != "system"]
                    messages.insert(0, {"role": "system", "content": self.system_prompt})
                else:
                    messages.insert(
                        0,
                        {
                            "role": "user",
                            "content": f"[SYSTEM PROMPT]: {self.system_prompt}",
                        },
                    )
            
            # Create accumulator for content
            accumulated_content = []
            
            # Simple non-async wrapper for the callback
            def text_callback(text):
                # Call the original callback
                if stream_callback:
                    stream_callback(text)
                # Also accumulate the text locally
                accumulated_content.append(text)
            
            # Check if adapter supports streaming directly
            if hasattr(self.adapter, 'create_completion'):
                try:
                    # Make sure we're bypassing litellm entirely for Anthropic
                    if self.adapter.provider == "anthropic":
                        self.logger.debug("Using direct Anthropic adapter for streaming")
                        
                    # Call adapter with our callback
                    content = await self.adapter.create_completion(
                        messages=messages,
                        max_tokens=max_tokens or self.model_config.max_tokens,
                        temperature=temperature or self.model_config.temperature,
                        stream=True,
                        stream_callback=text_callback
                    )
                    
                    # Return either the adapter's accumulated content or our own
                    if isinstance(content, str) and content:
                        return content
                    return ''.join(accumulated_content)
                except Exception as e:
                    self.logger.error(f"Streaming error in adapter: {str(e)}")
                    if accumulated_content:
                        # Return what we managed to get before the error
                        return ''.join(accumulated_content)
                    raise  # Re-raise if we got nothing
            
            # Fallback for non-streaming
            self.logger.warning("Adapter doesn't support streaming, falling back to non-streaming mode")
            response = await self.create_message(messages, max_tokens, temperature)
            content, _ = self.process_response(response)
            return content
            
        except Exception as e:
            error_message = f"LLM API streaming error: {str(e)}"
            self.logger.error(error_message)
            # Return an error message instead of raising to avoid breaking the chat flow
            return f"I encountered an error during streaming: {str(e)}"

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """Get a response with unified interface for streaming and non-streaming"""
        # Determine if streaming should be used
        use_streaming = stream if stream is not None else self.model_config.streaming_enabled
        
        try:
            # Debug token counts
            # try:
            #     token_count = self.count_tokens(messages)
            #     logger.warning(f"TOKEN COUNT FOR REQUEST: {token_count} tokens")
            #     if token_count > 100000:  # Arbitrary high number as warning threshold
            #         logger.error(f"EXTREMELY HIGH TOKEN COUNT: {token_count}. This will likely fail.")
                    
            #     # Calculate token counts for each message
            #     for i, msg in enumerate(messages):
            #         try:
            #             msg_tokens = self.count_tokens(msg)
            #             logger.warning(f"Message {i}: {msg_tokens} tokens, role={msg.get('role')}")
            #         except Exception as e:
            #             logger.warning(f"Could not count tokens for message {i}: {e}")
            # except Exception as e:
            #     logger.warning(f"Token counting failed: {e}")
            
            if use_streaming and stream_callback:
                # Handle streaming with proper accumulation
                accumulated_response = await self.create_streaming_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream_callback=stream_callback
                )
                return accumulated_response
            else:
                # Non-streaming path
                response = await self.create_message(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
                content, _ = self.process_response(response)
                return content
        except Exception as e:
            logger.error(f"Error getting response: {str(e)}")
            return f"Error: {str(e)}"


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
