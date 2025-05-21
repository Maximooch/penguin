import os
import logging
import asyncio
from typing import List, Dict, Optional, Any, Union, Callable, AsyncIterator

# --- Added Imports for Vision Handling ---
import base64
import io
import mimetypes
from PIL import Image as PILImage # Use alias for PIL Image # type: ignore
# --- End Added Imports ---

import openai # type: ignore
import tiktoken # type: ignore
from openai import AsyncOpenAI, APIError # type: ignore

# Assuming ModelConfig is in the same directory or adjust import path
try:
    from .model_config import ModelConfig
except ImportError:
    # Handle case where script might be run directly or structure changes
    from model_config import ModelConfig # type: ignore

logger = logging.getLogger(__name__)

class OpenRouterGateway:
    """
    A gateway to interact with the OpenRouter API using the OpenAI SDK compatibility.

    Handles chat completions (streaming and non-streaming) and token counting.
    """

    def __init__(
        self,
        model_config: ModelConfig,
        site_url: Optional[str] = None,
        site_title: Optional[str] = None,
        **kwargs: Any
    ):
        """
        Initializes the OpenRouterGateway.

        Args:
            model_config: Configuration object for the model.
            site_url: Optional site URL for OpenRouter leaderboards ('HTTP-Referer').
            site_title: Optional site title for OpenRouter leaderboards ('X-Title').
            **kwargs: Additional keyword arguments.
        """
        self.model_config = model_config
        self.logger = logging.getLogger(__name__)
        self.site_url = site_url or os.getenv("OPENROUTER_SITE_URL")
        self.site_title = site_title or os.getenv("OPENROUTER_SITE_TITLE", "Penguin_AI_Agent")

        # --- API Key Handling ---
        api_key = model_config.api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            self.logger.error("OpenRouter API key not found in model_config or OPENROUTER_API_KEY env var.")
            raise ValueError("Missing OpenRouter API Key.")

        # --- Initialize OpenAI Client for OpenRouter ---
        try:
            self.client = AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
            self.logger.info(f"OpenRouterGateway initialized for model: {model_config.model}")
            self.logger.info(f"Site URL: {self.site_url}, Site Title: {self.site_title}")

        except Exception as e:
            self.logger.error(f"Failed to initialize AsyncOpenAI client for OpenRouter: {e}", exc_info=True)
            raise ValueError(f"Could not initialize OpenRouter client: {e}") from e

        # --- Prepare Headers ---
        self.extra_headers = {}
        if self.site_url:
            self.extra_headers["HTTP-Referer"] = self.site_url
        if self.site_title:
            self.extra_headers["X-Title"] = self.site_title
        if not self.extra_headers:
             self.logger.debug("No extra headers (Site URL/Title) provided for OpenRouter.")
        else:
             self.logger.debug(f"Using extra headers: {self.extra_headers}")

    async def _encode_image(self, image_path: str) -> Optional[str]:
        """Encodes an image file to a base64 data URI."""
        if not os.path.exists(image_path):
            self.logger.error(f"Image path does not exist: {image_path}")
            return None
        try:
            logger.debug(f"Encoding image from path: {image_path}")
            with PILImage.open(image_path) as img:
                max_size = (1024, 1024) # Configurable?
                img.thumbnail(max_size, PILImage.LANCZOS)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG") # Use JPEG for efficiency
                image_bytes = buffer.getvalue()

            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type or not mime_type.startswith("image"):
                mime_type = "image/jpeg"
            data_uri = f"data:{mime_type};base64,{base64_image}"
            self.logger.debug(f"Encoded image to data URI (length: {len(data_uri)})")
            return data_uri
        except FileNotFoundError:
            self.logger.error(f"Image file not found during encoding: {image_path}")
            return None
        except Exception as e:
            self.logger.error(f"Error encoding image {image_path}: {e}", exc_info=True)
            return None

    async def _process_messages_for_vision(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Processes messages to encode images specified by 'image_path'."""
        processed_messages = []
        for message in messages:
            if isinstance(message.get("content"), list):
                new_content = []
                image_processed = False
                for item in message["content"]:
                    if isinstance(item, dict) and item.get("type") == "image_url" and "image_path" in item:
                        image_path = item["image_path"]
                        data_uri = await self._encode_image(image_path)
                        if data_uri:
                            # Replace item with OpenAI format
                            new_content.append({
                                "type": "image_url",
                                "image_url": {"url": data_uri}
                            })
                            image_processed = True
                        else:
                            # Failed to encode, maybe add a text note?
                            new_content.append({"type": "text", "text": f"[Error: Could not load image at {image_path}]"})
                    else:
                        # Keep other content parts as is
                        new_content.append(item)
                
                # If an image was processed, update the message content
                if image_processed:
                    processed_messages.append({**message, "content": new_content})
                else:
                    # No image processed, keep original message
                    processed_messages.append(message)
            else:
                # Not a list content, keep message as is
                processed_messages.append(message)
        return processed_messages

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any  # Allow passing other params like tools, tool_choice
    ) -> str:
        """
        Gets a chat completion response from OpenRouter.

        Args:
            messages: List of message dictionaries (OpenAI format).
            max_tokens: Optional max tokens for the response.
            temperature: Optional sampling temperature.
            stream: Whether to stream the response. If None, uses model_config default.
            stream_callback: Callback function for handling streaming chunks (required if stream=True).
            **kwargs: Additional parameters to pass to the OpenAI `create` call (e.g., 'tools', 'tool_choice').

        Returns:
            The complete response text content.
            Returns an error string "[Error: ...]" if an API call fails.
        """
        self.logger.info(f"[OpenRouterGateway] ENTERING get_response: stream_arg={stream}, stream_callback_arg={stream_callback}, model_config_streaming={self.model_config.streaming_enabled}")

        # Determine if streaming should be used *based on the passed flag first*
        # If stream is explicitly False, don't stream, even if config says yes.
        # If stream is explicitly True, try to stream.
        # If stream is None, fall back to config.
        use_streaming = stream if stream is not None else self.model_config.streaming_enabled
        
        # If streaming is decided but no callback is provided, log warning and disable
        if use_streaming and stream_callback is None:
            self.logger.warning("Streaming requested/configured but no stream_callback provided. Falling back to non-streaming mode.")
            use_streaming = False

        # --- Process messages for vision --- 
        try:
            processed_messages = await self._process_messages_for_vision(messages)
        except Exception as e:
            self.logger.error(f"Error processing messages for vision: {e}", exc_info=True)
            return f"[Error: Failed to process message content - {str(e)}]"
        # --- End vision processing ---

        request_params = {
            "model": self.model_config.model,
            "messages": processed_messages, # Use processed messages
            "max_tokens": max_tokens or self.model_config.max_tokens,
            "temperature": temperature if temperature is not None else self.model_config.temperature,
            "stream": use_streaming,
            "extra_headers": self.extra_headers,
            **kwargs # Pass through other arguments like tools
        }
        # Filter out None values for cleaner API calls
        request_params = {k: v for k, v in request_params.items() if v is not None}

        self.logger.debug(f"Calling OpenRouter chat completion with params: "
                          f"model={request_params.get('model')}, "
                          f"stream={use_streaming}, "
                          f"max_tokens={request_params.get('max_tokens')}, "
                          f"temp={request_params.get('temperature')}, "
                          f"headers={request_params.get('extra_headers')}, "
                          f"other_keys={list(kwargs.keys())}")

        full_response_content = ""
        try:
            completion = await self.client.chat.completions.create(**request_params)

            if use_streaming:
                self.logger.info("[OpenRouterGateway] Starting stream processing loop.")
                chunk_index = 0
                # internal_accumulator for this specific call, to ensure clean deltas to the external callback
                _gateway_accumulated_text = ""
                async for chunk in completion:
                    content_delta = chunk.choices[0].delta.content
                    tool_calls_delta = chunk.choices[0].delta.tool_calls

                    try:
                        chunk_log = f"[OpenRouterGateway] Raw Chunk {chunk_index}: ID={chunk.id}, Model={chunk.model}, FinishReason={chunk.choices[0].finish_reason}, DeltaContent='{content_delta}', DeltaTools='{tool_calls_delta}'"
                    except Exception:
                        chunk_log = f"[OpenRouterGateway] Raw Chunk {chunk_index} (Minimal Log): DeltaContent='{content_delta}'"
                    self.logger.debug(chunk_log)
                    chunk_index += 1

                    if content_delta:
                        # Determine the truly new part of the content_delta
                        new_text_segment = ""
                        if content_delta.startswith(_gateway_accumulated_text):
                            new_text_segment = content_delta[len(_gateway_accumulated_text):]
                        else:
                            # This case implies the chunking is not purely accumulative from the start,
                            # or there was a disconnect. For robustness, treat current content_delta as new if unsure.
                            # However, many SDKs send the full accumulated text. If this happens often, 
                            # it might indicate the provider sends deltas, and this logic needs adjustment.
                            # For OpenRouter with OpenAI SDK, it often sends accumulated text.
                            # A simpler approach if all chunks are full accumulated: new_text_segment = content_delta if not _gateway_accumulated_text else content_delta[len(_gateway_accumulated_text):] (if len > prev)
                            # Let's assume for now content_delta might be a pure new segment or fully accumulated.
                            # If content_delta is a segment that should be appended:
                            if not _gateway_accumulated_text.endswith(content_delta):
                                new_text_segment = content_delta # Or more complex diff if needed
                        
                        if new_text_segment:
                            _gateway_accumulated_text += new_text_segment
                            if stream_callback: # Call the EXTERNAL callback with ONLY the new segment
                                try:
                                    if new_text_segment.strip(): # Avoid sending empty/whitespace-only updates
                                        self.logger.debug(f"[OpenRouterGateway] Calling stream_callback with new segment: '{new_text_segment}'")
                                        await stream_callback(new_text_segment)
                                except Exception as cb_err:
                                    self.logger.error(f"[OpenRouterGateway] Error in stream_callback: {cb_err}", exc_info=True)
                        full_response_content = _gateway_accumulated_text # The overall full response

                    elif tool_calls_delta:
                         self.logger.debug(f"[OpenRouterGateway] Received tool_calls delta: {tool_calls_delta}.")
                         # Tool call streaming logic would go here if needed for external callback
                    else:
                        self.logger.debug(f"[OpenRouterGateway] Chunk {chunk_index-1} had no text/tool delta.")

                self.logger.info(f"[OpenRouterGateway] Finished stream. Accumulated text length: {len(full_response_content)}")
                return full_response_content

            else: # Not streaming
                # Extract content
                if completion.choices and completion.choices[0].message:
                     response_message = completion.choices[0].message
                     full_response_content = response_message.content

                     # TODO: Handle tool calls in non-streaming response
                     if response_message.tool_calls:
                          self.logger.info(f"Received tool calls: {response_message.tool_calls}")
                          # How should this be returned? The current interface expects only a string.
                          # This needs coordination with api_client and core.
                          # For now, we prioritize returning the text content if available.
                          if not full_response_content:
                               # Maybe return a placeholder or representation of the tool call?
                               full_response_content = f"[Tool Calls Received: {len(response_message.tool_calls)}]"

                if not full_response_content:
                     self.logger.warning(f"OpenRouter non-streaming response had no text content. Response: {completion}")
                     # Check if there's an error in the response object
                     error_info = getattr(completion, 'error', None)
                     if error_info:
                         error_code = error_info.get('code', 'unknown')
                         error_message = error_info.get('message', 'Unknown error')
                         provider_info = error_info.get('metadata', {}).get('provider_name', 'unknown provider')
                         
                         # Handle provider-specific errors
                         if 'quota' in error_message.lower() or error_code == 429:
                             return f"[Error: Provider quota exceeded ({provider_info}). {error_message}]"
                         
                         return f"[Error: Provider error ({provider_info}, code {error_code}). {error_message}]"
                     
                     # If no error but still empty content (common with some Gemini models)
                     # Check usage to see if it was actually completed
                     usage = getattr(completion, 'usage', None)
                     completion_tokens = getattr(usage, 'completion_tokens', 0) if usage else 0
                     
                     if completion_tokens > 0:
                         # Something was generated but response is empty (happens with some models)
                         self.logger.info(f"Model generated {completion_tokens} tokens but returned empty content")
                         return "[Note: Model processed the request but returned empty content. Try rephrasing your query.]"
                         
                     # Check finish reason?
                     finish_reason = completion.choices[0].finish_reason if completion.choices else "unknown"
                     provider = getattr(completion, 'provider', 'Unknown')
                     
                     # Return a placeholder message instead of empty string for debugging
                     self.logger.warning(f"Model finished (reason: {finish_reason}) but returned no content and generated 0 completion tokens.")
                     return f"[Model finished with no content from {provider}. Please try again or try with a different model.]"

                self.logger.debug(f"Non-streaming response received. Content length: {len(full_response_content or '')}")
                return full_response_content or "" # Ensure string return

        except APIError as e:
            self.logger.error(f"OpenRouter API error: {e}", exc_info=True)
            return f"[Error: OpenRouter API Error - {e.status_code} - {e.message}]"
        except Exception as e:
            self.logger.error(f"Unexpected error during OpenRouter API call: {e}", exc_info=True)
            return f"[Error: Unexpected error communicating with OpenRouter - {str(e)}]"

    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """
        Counts tokens using tiktoken, assuming GPT-4o encoding as per OpenRouter's norm.

        Args:
            content: Text string, a list of message dicts, or a single message dict.

        Returns:
            The number of tokens.
        """
        if not self.model_config.enable_token_counting:
             self.logger.debug("Token counting disabled in ModelConfig.")
             return 0

        model_for_counting = "gpt-4o" # Use OpenRouter's standard for normalized counting
        try:
            encoding = tiktoken.encoding_for_model(model_for_counting)
        except Exception as e:
            self.logger.warning(f"Failed to get tiktoken encoding for '{model_for_counting}', falling back to cl100k_base: {e}")
            try:
                 encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as fallback_e:
                 self.logger.error(f"Failed to get cl100k_base encoding: {fallback_e}. Falling back to rough estimate.")
                 return len(str(content)) // 4 # Very rough estimate

        num_tokens = 0
        if isinstance(content, str):
            num_tokens = len(encoding.encode(content))
        elif isinstance(content, list): # Assume list of messages
            # Based on OpenAI cookbook examples for counting tokens for chat messages
            tokens_per_message = 3
            tokens_per_name = 1
            for message in content:
                num_tokens += tokens_per_message
                for key, value in message.items():
                    # Ensure value is a string before encoding
                    value_str = str(value) if not isinstance(value, (str, list)) else value # Handle potential non-strings crudely

                    if isinstance(value_str, str): # Encode strings
                        num_tokens += len(encoding.encode(value_str))
                    elif isinstance(value_str, list) and key == 'content': # Handle multimodal content list
                         for item in value_str:
                              if isinstance(item, dict) and item.get('type') == 'text':
                                   num_tokens += len(encoding.encode(item.get('text', '')))
                              # Vision tokens are harder to count accurately here, skip for now
                              # elif isinstance(item, dict) and item.get('type') == 'image_url':
                              #      pass # Placeholder for vision token counting logic if needed

                    if key == "name": # If there's a name associated with the message
                        num_tokens += tokens_per_name
            num_tokens += 3  # Every reply is primed with <|im_start|>assistant<|im_sep|>
        elif isinstance(content, dict): # Assume single message dict
             # Simplified count for single dict, better to use list format
             num_tokens = len(encoding.encode(str(content))) # Rough estimate for single dict
        else:
            self.logger.warning(f"Unsupported type for token counting: {type(content)}. Using rough estimate.")
            num_tokens = len(encoding.encode(str(content)))

        return num_tokens

    def supports_system_messages(self) -> bool:
        """OpenRouter (via OpenAI SDK format) supports system messages."""
        return True

    def supports_vision(self) -> bool:
        """Check if the configured model likely supports vision based on ModelConfig."""
        # Rely on the determination made in ModelConfig
        return self.model_config.vision_enabled

    # --- Optional: Method to list models ---
    async def get_available_models(self) -> List[str]:
        """
        Fetches the list of available models from OpenRouter.

        Returns:
            A list of model ID strings. Returns empty list on failure.
        """
        try:
            models_response = await self.client.models.list()
            model_ids = [model.id for model in models_response.data]
            self.logger.info(f"Fetched {len(model_ids)} models from OpenRouter.")
            return model_ids
        except APIError as e:
            self.logger.error(f"Failed to list OpenRouter models (API Error): {e}", exc_info=True)
            return []
        except Exception as e:
            self.logger.error(f"Failed to list OpenRouter models (Unexpected Error): {e}", exc_info=True)
            return [] 