# penguin/llm/litellm_gateway.py

import asyncio
import base64
import io
import logging
import os
import traceback
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple, Union

import litellm  # type: ignore
from PIL import Image  # type: ignore

from .model_config import ModelConfig

logger = logging.getLogger(__name__)

# Configure LiteLLM logging level if desired
litellm.set_verbose = True # Uncomment for debugging LiteLLM calls


class LiteLLMGateway:
    """
    A gateway for interacting with various LLM providers using the LiteLLM library.

    This provides a unified interface for making completion requests, supporting
    multiple providers, streaming, and vision capabilities through LiteLLM's
    standardized methods. It can be used as an alternative or alongside
    direct provider integrations.
    """

    def __init__(self, model_config: ModelConfig):
        """
        Initialize the LiteLLM Gateway.

        Args:
            model_config: Configuration specific to the model being used.
                          The `model` attribute should contain the full LiteLLM
                          model identifier (e.g., 'openai/gpt-4o',
                          'anthropic/claude-3-opus-20240229').
        """
        if not model_config or not model_config.model:
            raise ValueError("Valid ModelConfig with a model identifier is required.")
        self.model_config = model_config
        logger.info(f"LiteLLMGateway initialized for model: {self.model_config.model}")

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Get a response from the configured LLM via LiteLLM.

        Args:
            messages: A list of message dictionaries (OpenAI format).
            max_tokens: The maximum number of tokens to generate.
            temperature: The sampling temperature.
            stream: Whether to stream the response.
            stream_callback: A callback function to handle streaming chunks.

        Returns:
            The complete response string from the LLM.
        """
        request_id = os.urandom(4).hex() # Generate a simple request ID for tracking
        logger.info(f"[Request:{request_id}] LiteLLMGateway.get_response called.")
        
        # Determine if streaming should be used; fall back to non-streaming if 
        # streaming is requested but no callback is provided
        use_streaming = stream and stream_callback is not None
        if stream and not stream_callback:
            logger.warning(f"[Request:{request_id}] Streaming requested but no stream_callback provided. Falling back to non-streaming mode.")
            
        try:
            # 1. Format messages (especially handle images for vision models)
            formatted_messages = self._format_messages(messages)
            logger.debug(f"[Request:{request_id}] Formatted messages prepared.")
            # Log message content safely (avoid logging full image data)
            try:
                 safe_messages_log = self._safe_log_content({"messages": formatted_messages}).get("messages", [])
                 logger.debug(f"[Request:{request_id}] Safe Formatted Messages: {safe_messages_log}")
            except Exception as log_err:
                 logger.warning(f"[Request:{request_id}] Error creating safe log for messages: {log_err}")

            # 2. Prepare parameters for LiteLLM
            litellm_params = self._prepare_litellm_params(
                formatted_messages, max_tokens, temperature
            )
            logger.debug(f"[Request:{request_id}] LiteLLM parameters prepared.")
            # Log params safely (redacts API key)
            try:
                 safe_params_log = self._safe_log_content(litellm_params)
                 logger.debug(f"[Request:{request_id}] Safe LiteLLM Params: {safe_params_log}")
            except Exception as log_err:
                 logger.warning(f"[Request:{request_id}] Error creating safe log for params: {log_err}")

            # 3. Call LiteLLM (streaming or non-streaming)
            if use_streaming:
                logger.info(f"[Request:{request_id}] Initiating STREAMING call via LiteLLM: {litellm_params.get('model', 'Unknown Model')}")
                full_response = await self._handle_streaming(
                    litellm_params, stream_callback, request_id
                )
            else:
                logger.info(f"[Request:{request_id}] Initiating NON-STREAMING call via LiteLLM: {litellm_params.get('model', 'Unknown Model')}")
                raw_response_obj = None
                try:
                    raw_response_obj = await litellm.acompletion(**litellm_params)
                    logger.info(f"[Request:{request_id}] Raw response object received from litellm.acompletion.")
                    logger.debug(f"[Request:{request_id}] Raw Response Type: {type(raw_response_obj)}")
                    if hasattr(raw_response_obj, '__dict__'):
                         logger.debug(f"[Request:{request_id}] Raw Response Attributes: {vars(raw_response_obj).keys()}")
                    elif isinstance(raw_response_obj, dict):
                         logger.debug(f"[Request:{request_id}] Raw Response Keys: {raw_response_obj.keys()}")

                except Exception as api_call_err:
                     logger.error(f"[Request:{request_id}] Error during litellm.acompletion call: {api_call_err}", exc_info=True)
                     raise

                full_response = self._process_response(raw_response_obj, request_id)

            logger.info(f"[Request:{request_id}] LiteLLMGateway.get_response finished. Response length: {len(full_response)}")
            return full_response

        except litellm.exceptions.AuthenticationError as e:
            logger.error(f"LiteLLM Authentication Error: {e}")
            return f"Error: Authentication failed. Check API key for {self.model_config.provider}."
        except litellm.exceptions.RateLimitError as e:
            logger.error(f"LiteLLM Rate Limit Error: {e}")
            return "Error: Rate limit exceeded. Please try again later."
        except litellm.exceptions.APIConnectionError as e:
            logger.error(f"LiteLLM API Connection Error: {e}")
            return f"Error: Could not connect to the API endpoint ({self.model_config.api_base or 'default'})."
        except litellm.exceptions.BadRequestError as e:
             logger.error(f"[Request:{request_id}] LiteLLM Bad Request Error: {e}")
             details = getattr(e, 'message', str(e))
             status_code = getattr(e, 'status_code', 'N/A')
             logger.error(f"[Request:{request_id}] Status Code: {status_code}, Details: {details}")
             if 'litellm_params' in locals():
                  logger.error(f"[Request:{request_id}] Problematic Params: {self._safe_log_content(litellm_params)}")
             else:
                  logger.error(f"[Request:{request_id}] Could not log problematic params (error occurred before definition).")
             return f"Error: Invalid request (Status {status_code}). Please check input parameters or model compatibility. Details: {details}"
        except Exception as e:
            logger.error(f"[Request:{request_id}] Unexpected error during LiteLLM call: {e}")
            logger.error(traceback.format_exc())
            return f"An unexpected error occurred: {str(e)}"

    def _prepare_litellm_params(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Prepare the dictionary of parameters for litellm.acompletion."""
        params = {
            "model": self.model_config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.model_config.max_tokens,
            "temperature": temperature if temperature is not None else self.model_config.temperature,
            # Add other common params if needed (top_p, presence_penalty, etc.)
        }

        # Add API key if available in config or environment
        # LiteLLM often reads from env vars automatically, but explicit passing is safer
        api_key = self.model_config.api_key or os.getenv(
            f"{self.model_config.provider.upper()}_API_KEY"
        )
        if api_key:
            params["api_key"] = api_key

        # Add API base if specified (crucial for local models or custom endpoints)
        if self.model_config.api_base:
            params["api_base"] = self.model_config.api_base

        # Add API version if specified (e.g., for Azure)
        if self.model_config.api_version:
             params["api_version"] = self.model_config.api_version

        # Remove None values to avoid sending empty params
        return {k: v for k, v in params.items() if v is not None}

    def _format_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Formats messages into OpenAI format, handling images."""
        formatted_messages = []
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")

            if isinstance(content, list):
                # Handle multimodal content (potentially with images)
                processed_content_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            processed_content_parts.append(part)
                        elif part.get("type") == "image_url" or "image_path" in part:
                            # This model might support vision, try processing image
                            if self.model_config.vision_enabled:
                                image_part = self._format_image_part(part)
                                if image_part:
                                    processed_content_parts.append(image_part)
                                else:
                                    # Failed to process, add placeholder
                                    processed_content_parts.append({"type": "text", "text": "[Image processing failed]"})
                            else:
                                # Vision not enabled, add placeholder
                                processed_content_parts.append({"type": "text", "text": "[Image ignored - Vision not enabled]"})
                        else:
                            # Pass through other potential dict types
                            processed_content_parts.append(part)
                    elif isinstance(part, str):
                        # Convert string parts to text dict
                        processed_content_parts.append({"type": "text", "text": part})
                    else:
                        logger.warning(f"Unsupported part type in message content: {type(part)}. Skipping.")

                if processed_content_parts: # Only add message if content parts were processed
                    formatted_messages.append({"role": role, "content": processed_content_parts})
                else:
                     logger.warning(f"Skipping message with role '{role}' due to empty processed content.")

            elif isinstance(content, str):
                # Simple string content
                formatted_messages.append({"role": role, "content": content})
            else:
                logger.warning(f"Unsupported content type for message: {type(content)}. Converting to string.")
                formatted_messages.append({"role": role, "content": str(content)})

        return formatted_messages

    def _format_image_part(self, part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Formats an image part into OpenAI's expected format (base64 data URI)."""
        image_path = part.get("image_path")
        image_url_data = part.get("image_url", {})
        # Handle cases where image_url is a string or dict
        image_url = image_url_data if isinstance(image_url_data, str) else image_url_data.get("url")

        source = image_path or image_url

        if not source:
            logger.error("Image part provided without 'image_path' or 'image_url'.")
            return {"type": "text", "text": "[Invalid image data]"}

        try:
            # Determine if it's a local path or URL
            is_local_path = os.path.exists(source)
            is_url = isinstance(source, str) and source.startswith(('http://', 'https://'))

            if is_local_path:
                logger.debug(f"Encoding local image: {source}")
                # Process local file
                with Image.open(source) as img:
                    # Resize if needed (optional, adjust as needed)
                    max_size = (1024, 1024)
                    img.thumbnail(max_size, Image.LANCZOS)

                    if img.mode != "RGB":
                        img = img.convert("RGB")

                    buffer = io.BytesIO()
                    # Use JPEG for broad compatibility, consider PNG if quality is paramount
                    img_format = "JPEG"
                    media_type = "image/jpeg"
                    # Determine format based on original extension?
                    # ext = os.path.splitext(source)[1].lower()
                    # if ext == ".png": img_format, media_type = "PNG", "image/png"
                    # ... etc
                    img.save(buffer, format=img_format)
                    base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')

                    return {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{base64_image}"}
                    }
            elif is_url:
                 # If it's a web URL, LiteLLM/provider *should* handle it directly.
                 # We just pass it in the OpenAI format.
                 logger.debug(f"Passing image URL directly: {source}")
                 return {
                     "type": "image_url",
                     "image_url": {"url": source}
                 }
            else:
                logger.error(f"Unsupported image source format: {source}")
                return {"type": "text", "text": f"[Unsupported image source: {source[:50]}...]"}

        except FileNotFoundError:
            logger.error(f"Image file not found: {source}")
            return {"type": "text", "text": f"[Image not found: {os.path.basename(source)}]"}
        except Exception as e:
            logger.error(f"Error processing image source {source}: {str(e)}")
            logger.error(traceback.format_exc())
            return {"type": "text", "text": f"[Image processing error: {e}]"}

    def _process_response(self, response_obj: Optional[litellm.ModelResponse], request_id: str) -> str:
        """Extracts the response content from LiteLLM's ModelResponse object."""
        if response_obj is None:
            logger.warning(f"[Request:{request_id}] _process_response received None object.")
            return "[Error: No response object received from API call]"

        try:
            logger.debug(f"[Request:{request_id}] Attempting to process response object: Type={type(response_obj)}")
            try:
                 logger.debug(f"[Request:{request_id}] Raw Response Object for Processing: {response_obj}")
            except Exception as log_err:
                 logger.warning(f"[Request:{request_id}] Could not log raw response object directly: {log_err}")

            if response_obj and response_obj.choices and response_obj.choices[0].message:
                content = response_obj.choices[0].message.content
                if content is not None:
                    logger.debug(f"[Request:{request_id}] Extracted content successfully. Length: {len(content)}")
                    stripped_content = content.strip()
                    return stripped_content if stripped_content else "[Model produced empty string content]"
                else:
                    logger.warning(f"[Request:{request_id}] LiteLLM response object had None message content.")
                    usage = getattr(response_obj, 'usage', None)
                    finish_reason = getattr(response_obj.choices[0], 'finish_reason', 'N/A')
                    logger.debug(f"[Request:{request_id}] None content details: finish_reason={finish_reason}, usage={usage}")
                    return f"[Model finished ({finish_reason}) but content was None. Usage: {usage}]"
            else:
                logger.warning(f"[Request:{request_id}] Could not extract content from LiteLLM response object structure.")
                logger.debug(f"[Request:{request_id}] Response object structure: {response_obj}")
                return "[Error: Could not parse response structure from LiteLLM]"
        except Exception as e:
            logger.error(f"[Request:{request_id}] Error processing LiteLLM response object: {e}", exc_info=True)
            logger.debug(f"[Request:{request_id}] Failing response object structure: {response_obj}")
            return f"[Error processing response: {str(e)}]"

    async def _handle_streaming(
        self,
        litellm_params: Dict[str, Any],
        stream_callback: Callable[[str], None],
        request_id: str
    ) -> str:
        """Handles the streaming response from LiteLLM."""
        accumulated_response = []
        logger.debug(f"[Request:{request_id}] Entering _handle_streaming.")
        try:
            response_stream = await litellm.acompletion(**litellm_params, stream=True)
            logger.debug(f"[Request:{request_id}] Received streaming iterator.")
            async for chunk in response_stream:
                delta_content = None
                if chunk.choices and chunk.choices[0].delta:
                     delta_content = chunk.choices[0].delta.content

                if delta_content:
                    try:
                         stream_callback(delta_content)
                         accumulated_response.append(delta_content)
                    except Exception as cb_err:
                         logger.error(f"[Request:{request_id}] Error in stream_callback: {cb_err}")
                # else:
                #     logger.debug(f"[Request:{request_id}] Stream chunk had no extractable delta content.")

        except asyncio.CancelledError:
             logger.warning(f"[Request:{request_id}] LiteLLM streaming was cancelled.")
        except Exception as e:
             logger.error(f"[Request:{request_id}] Error during LiteLLM streaming: {e}", exc_info=True)
             try:
                 stream_callback(f"\n[STREAMING ERROR: {str(e)}]")
             except Exception as cb_err:
                  logger.error(f"[Request:{request_id}] Error calling stream_callback with error message: {cb_err}")
             error_msg = f"[STREAMING ERROR: {str(e)}]"
             if accumulated_response:
                 return "".join(accumulated_response) + "\n" + error_msg
             else:
                 return error_msg
        finally:
             final_response = "".join(accumulated_response)
             logger.debug(f"[Request:{request_id}] Streaming finished. Accumulated response length: {len(final_response)}")
             return final_response

    def count_tokens(self, content: Union[str, List[Dict[str, Any]]]) -> int:
        """
        Counts tokens using LiteLLM's token counter.

        Args:
            content: A string or a list of message dictionaries.

        Returns:
            The estimated token count. Returns 0 if counting fails.
        """
        try:
            if isinstance(content, str):
                # Count tokens for a single string
                return litellm.token_counter(model=self.model_config.model, text=content)
            elif isinstance(content, list):
                 # Count tokens for a list of messages
                 # Note: Ensure messages are formatted correctly if needed by token_counter
                 # For simplicity, we assume OpenAI format is okay here.
                 return litellm.token_counter(model=self.model_config.model, messages=content)
            else:
                 logger.warning(f"Unsupported content type for token counting: {type(content)}")
                 return 0
        except Exception as e:
            logger.error(f"Error using litellm.token_counter for model {self.model_config.model}: {e}")
            # Fallback: very rough estimate
            return len(str(content)) // 4

    def _safe_log_content(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a copy of params safe for logging (removes image data)."""
        safe_params = {}
        for k, v in params.items():
            if k == "messages" and isinstance(v, list):
                safe_messages = []
                for msg in v:
                    if isinstance(msg, dict):
                        safe_msg = msg.copy()
                        if "content" in safe_msg:
                            if isinstance(safe_msg["content"], list):
                                safe_content = []
                                for part in safe_msg["content"]:
                                    if isinstance(part, dict) and part.get("type") == "image_url":
                                         # Check if it's base64 data
                                         url = part.get("image_url", {}).get("url", "")
                                         if url.startswith("data:image"):
                                             safe_content.append({"type": "image_url", "image_url": {"url": "[BASE64 DATA REDACTED]"}})
                                         else:
                                             safe_content.append(part) # Keep regular URLs
                                    else:
                                         safe_content.append(part)
                                safe_msg["content"] = safe_content
                            elif isinstance(safe_msg["content"], str):
                                # Keep text content as is for logging context
                                safe_msg["content"] = safe_msg["content"][:500] + ("..." if len(safe_msg["content"]) > 500 else "")

                        safe_messages.append(safe_msg)
                    else:
                        safe_messages.append(msg) # Should not happen based on formatting
                safe_params[k] = safe_messages
            elif k == "api_key":
                 safe_params[k] = "[REDACTED]"
            else:
                # Log other params directly (or add more redaction if needed)
                safe_params[k] = v
        return safe_params