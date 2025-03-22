import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List

from ..utils.diagnostics import diagnostics
from .model_config import ModelConfig


class ProviderAdapter(ABC):
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config

    @abstractmethod
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        pass

    def supports_conversation_id(self) -> bool:
        return False

    def format_messages_with_id(
        self, conversation_id: str, message: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("This adapter does not support conversation IDs")

    def get_conversation_id(self, response: Any) -> str:
        raise NotImplementedError("This adapter does not support conversation IDs")

    def count_tokens(self, text: str) -> int:
        return diagnostics.count_tokens(text)

    def supports_system_messages(self) -> bool:
        """Return True if provider natively supports system role messages"""
        return True  # Default to supporting system messages

    @property
    @abstractmethod
    def provider(self) -> str:
        """Return lowercase provider name string"""
        pass


# TODO: implement streaming abstraction


class OpenAIAdapter(ProviderAdapter):
    @property
    def provider(self) -> str:
        return "openai"

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted_messages = []
        for message in messages:
            content = message.get("content", "")

            # Handle list-type content (like image messages)
            if isinstance(content, list):
                # Ensure each content part has proper format
                formatted_content = []
                for part in content:
                    if isinstance(part, dict):
                        if "image_path" in part:
                            # Handle image paths by encoding them to base64
                            try:
                                image_path = part["image_path"]
                                
                                # Encode the image here
                                import base64
                                from PIL import Image # type: ignore
                                import io
                                import os
                                
                                # Check if file exists
                                if not os.path.exists(image_path):
                                    logging.error(f"Image file not found: {image_path}")
                                    formatted_content.append({
                                        "type": "text", 
                                        "text": f"[Image not found: {image_path}]"
                                    })
                                    continue
                                    
                                # Process the image
                                with Image.open(image_path) as img:
                                    # Resize if needed
                                    max_size = (1024, 1024)
                                    img.thumbnail(max_size, Image.LANCZOS)
                                    
                                    # Convert to RGB if needed
                                    if img.mode != "RGB":
                                        img = img.convert("RGB")
                                    
                                    # Save to buffer and encode
                                    buffer = io.BytesIO()
                                    img.save(buffer, format="JPEG")
                                    base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
                                
                                # Format specifically for OpenAI
                                formatted_content.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}"
                                    }
                                })
                            except Exception as e:
                                logging.error(f"Error encoding image: {str(e)}")
                                formatted_content.append({
                                    "type": "text", 
                                    "text": f"[Failed to process image: {str(e)}]"
                                })
                        elif "image_url" in part:
                            # Ensure image_url format is consistent
                            formatted_content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": part["image_url"]["url"]},
                                }
                            )
                        else:
                            formatted_content.append(part)
                    else:
                        formatted_content.append({"type": "text", "text": str(part)})
                formatted_messages.append(
                    {"role": message["role"], "content": formatted_content}
                )
            else:
                # Handle string content
                formatted_messages.append(
                    {
                        "role": message["role"],
                        "content": content,  # Keep as string for OpenAI API
                    }
                )

        return formatted_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        if self.model_config.use_assistants_api:
            return response, []
        else:
            return response["choices"][0]["message"]["content"], []


class LiteLLMAdapter(ProviderAdapter):
    @property
    def provider(self) -> str:
        return "litellm"

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{**msg, "content": str(msg["content"])} for msg in messages]

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """
        Process response from LiteLLM, handling different response formats
        """
        try:
            # Handle dictionary response
            if isinstance(response, dict):
                if "choices" in response:
                    return response["choices"][0]["message"]["content"], []
                return response.get("content", str(response)), []

            # Handle LiteLLM response object
            if hasattr(response, "choices") and len(response.choices) > 0:
                if hasattr(response.choices[0], "message"):
                    return response.choices[0].message.content, []
                if hasattr(response.choices[0], "text"):
                    return response.choices[0].text, []

            # Handle string response (some providers like Deepseek might return direct string)
            if isinstance(response, str):
                return response, []

            # If we can't handle the response format, convert to string
            return str(response), []

        except Exception as e:
            logging.error(f"Error processing LiteLLM response: {str(e)}")
            # Return the raw response as string if we can't process it
            return str(response), []


class AnthropicAdapter(ProviderAdapter):
    @property
    def provider(self) -> str:
        return "anthropic"

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format messages for Anthropic API with proper image handling.
        """
        formatted_messages = []
        for message in messages:
            content = message.get("content", "")
            role = message.get("role", "user")

            # Handle list-type content (for structured content)
            if isinstance(content, list):
                # Process structured content with images
                formatted_content = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            # Text part - pass through
                            formatted_content.append(part)
                        elif "image_path" in part:
                            # Image path needs to be encoded for Anthropic
                            try:
                                image_path = part["image_path"]
                                
                                # Encode the image here - THIS is where encoding belongs
                                import base64
                                from PIL import Image # type: ignore
                                import io
                                import os
                                
                                # Check if file exists
                                if not os.path.exists(image_path):
                                    logging.error(f"Image file not found: {image_path}")
                                    formatted_content.append({
                                        "type": "text", 
                                        "text": f"[Image not found: {image_path}]"
                                    })
                                    continue
                                    
                                # Process the image
                                with Image.open(image_path) as img:
                                    # Resize if needed
                                    max_size = (1024, 1024)
                                    img.thumbnail(max_size, Image.LANCZOS)
                                    
                                    # Convert to RGB if needed
                                    if img.mode != "RGB":
                                        img = img.convert("RGB")
                                    
                                    # Save to buffer and encode
                                    buffer = io.BytesIO()
                                    img.save(buffer, format="JPEG")
                                    base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
                                
                                # Format specifically for Anthropic
                                formatted_content.append({
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}"
                                    }
                                })
                            except Exception as e:
                                logging.error(f"Error encoding image: {str(e)}")
                                formatted_content.append({
                                    "type": "text", 
                                    "text": f"[Failed to process image: {str(e)}]"
                                })
                        else:
                            # Other content types - pass through
                            formatted_content.append(part)
                    else:
                        # Handle non-dict parts
                        formatted_content.append({"type": "text", "text": str(part)})
                
                # Use the formatted content
                formatted_messages.append({"role": role, "content": formatted_content})
            else:
                # Simple string content
                formatted_messages.append({"role": role, "content": [{"type": "text", "text": str(content)}]})
        
        return formatted_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """Process Anthropic API response"""
        try:
            logging.debug(f"Processing Anthropic response of type: {type(response)}")
            
            # Handle ModelResponse from LiteLLM
            if hasattr(response, 'choices') and response.choices:
                message = response.choices[0].message
                if hasattr(message, 'content'):
                    return message.content, []
            
            # Handle dictionary response
            if isinstance(response, dict):
                if "choices" in response and response["choices"]:
                    message = response["choices"][0].get("message", {})
                    content = message.get("content", "")
                    return content, []
                elif "content" in response:
                    return response["content"], []
            
            # Last resort fallback for string content
            if isinstance(response, str):
                return response, []
            
            # If we've reached here, we can't extract properly
            error_msg = f"Could not extract content from response: {str(response)[:100]}..."
            logging.error(error_msg)
            return error_msg, []
            
        except Exception as e:
            logging.error(f"Error in process_response: {str(e)}")
            return f"Error processing response: {str(e)}", []

    def supports_system_messages(self) -> bool:
        return True


class OllamaAdapter(ProviderAdapter):
    @property
    def provider(self) -> str:
        return "ollama"

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Ollama's LLaVA models accept the same format as OpenAI
        return messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        return response["message"]["content"], []


class DeepseekAdapter(ProviderAdapter):
    @property
    def provider(self) -> str:
        return "deepseek"

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Extract FIRST system message only (Deepseek allows 1 system message at start)
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        other_messages = [msg for msg in messages if msg.get("role") != "system"]

        formatted = []
        if system_messages:
            # Use first system message as-is
            formatted.append(system_messages[0])
            # Convert subsequent system messages to user with prefix
            for extra_system in system_messages[1:]:
                other_messages.insert(
                    0,
                    {
                        "role": "user",
                        "content": f"[ADDITIONAL SYSTEM CONTEXT]: {extra_system['content']}",
                    },
                )

        # Process all other messages with strict role alternation
        current_role = None
        for msg in other_messages:
            role = msg.get("role", "user")
            content = str(msg.get("content", ""))

            if role == current_role:
                # Merge with previous message
                formatted[-1]["content"] += f"\n{content}"
            else:
                formatted.append({"role": role, "content": content})
                current_role = role

        return formatted

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """Process Deepseek API response"""
        try:
            if hasattr(response, "choices"):
                return response.choices[0].message.content, []
            return str(response), []
        except Exception as e:
            logging.error(f"Error processing Deepseek response: {str(e)}")
            return str(response), []

    def supports_system_messages(self) -> bool:
        return True  # Now properly supports single system message


def get_provider_adapter(provider: str, model_config: ModelConfig) -> ProviderAdapter:
    adapters = {
        "openai": OpenAIAdapter(model_config),
        "litellm": LiteLLMAdapter(model_config),
        "anthropic": AnthropicAdapter(model_config),
        "ollama": OllamaAdapter(model_config),
        "deepseek": DeepseekAdapter(model_config),
    }
    return adapters.get(
        provider.lower(), LiteLLMAdapter(model_config)
    )  # Default to LiteLLMAdapter if provider not found
