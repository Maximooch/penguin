import os
import logging
import asyncio
import json
from typing import List, Dict, Optional, Any, Union, Callable, AsyncIterator

# --- Added Imports for Vision Handling ---
import base64
import io
import mimetypes
from PIL import Image as PILImage # Use alias for PIL Image # type: ignore
# --- End Added Imports ---

import httpx # type: ignore
import openai # type: ignore
import tiktoken # type: ignore
from openai import AsyncOpenAI, APIError # type: ignore

# Assuming ModelConfig is in the same directory or adjust import path
try:
    from .model_config import ModelConfig
    # from .debug_utils import get_debugger, debug_request, debug_stream_start, debug_stream_chunk, debug_stream_complete, debug_error
except ImportError:
    # Handle case where script might be run directly or structure changes
    from model_config import ModelConfig # type: ignore
    # # Mock debug functions for standalone usage
    # def get_debugger(): return None
    # def debug_request(*args, **kwargs): return f"debug_{id(args)}"
    # def debug_stream_start(*args, **kwargs): pass
    # def debug_stream_chunk(*args, **kwargs): pass  
    # def debug_stream_complete(*args, **kwargs): pass
    # def debug_error(*args, **kwargs): pass

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
    
    def _contains_penguin_action_tags(self, content: str) -> bool:
        """
        Check if content contains any Penguin action tags using the same logic as parser.py
        """
        try:
            # Import here to avoid circular imports
            from penguin.utils.parser import ActionType
            import re
            
            # Generate pattern from ActionType enum (exactly like parser.py does)
            action_tag_pattern = "|".join([action_type.value for action_type in ActionType])
            # Use same regex pattern as parser: full tag pairs only, case-insensitive but strict
            action_tag_regex = f"<({action_tag_pattern})>.*?</\\1>"
            
            return bool(re.search(action_tag_regex, content, re.DOTALL | re.IGNORECASE))
        except ImportError:
            # Fallback to basic check if import fails
            return any(f"<{tag}>" in content.lower() and f"</{tag}>" in content.lower() 
                      for tag in ['execute', 'search', 'memory_search'])
    
    def _clean_conversation_format(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Reformat conversation to be compatible with OpenAI SDK while preserving all content.
        
        This aggressively converts all tool calling to plain text format to avoid
        OpenAI SDK 1.99+ tool call validation errors, while preserving all message content.
        """
        reformatted_messages = []
        
        for message in messages:
            reformatted_message = message.copy()
            
            # Handle content field
            if isinstance(message.get('content'), str):
                content = message['content']
                
                # Clean up orphaned tool call references that could cause validation errors
                if 'call_' in content and ('tool_calls' not in message):
                    # Replace call_id references with plain text to avoid SDK validation
                    import re
                    content = re.sub(r'call_[a-zA-Z0-9_-]+', '[tool-call-reference]', content)
                    self.logger.debug(f"Reformatted tool call references in message")
                
                # Check for XML action tags - they're Penguin's tool system and should be preserved
                if self._contains_penguin_action_tags(content):
                    self.logger.debug(f"Preserving Penguin XML action tags in message: {content[:100]}...")
                
                reformatted_message['content'] = content
            
            # AGGRESSIVE FIX: Convert ALL tool calling to plain text to avoid validation errors
            # This prevents the "No tool call found" error by not sending tool call formats at all
            
            if message.get('role') == 'assistant' and 'tool_calls' in message:
                # Convert assistant message with tool_calls to plain assistant message
                self.logger.debug(f"Converting assistant message with tool_calls to plain text")
                # Remove tool_calls field and keep content as-is (it already has the action tags)
                reformatted_message = {
                    'role': 'assistant',
                    'content': message.get('content', '')
                }
                # Copy other fields but exclude tool_calls
                for key, value in message.items():
                    if key not in ['role', 'content', 'tool_calls']:
                        reformatted_message[key] = value
            
            elif message.get('role') == 'tool':
                # Convert ALL tool messages to assistant messages with prefixed content
                self.logger.debug(f"Converting tool result message to assistant message")
                reformatted_message = {
                    'role': 'assistant', 
                    'content': f"[Tool Result] {message.get('content', '')}"
                }
                # Copy other fields but exclude tool_call_id
                for key, value in message.items():
                    if key not in ['role', 'content', 'tool_call_id']:
                        reformatted_message[key] = value
            
            reformatted_messages.append(reformatted_message)
        
        self.logger.debug(f"Reformatted conversation: {len(messages)} messages processed, all tool calling converted to plain text")
        return reformatted_messages

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
        # # Initialize debug session
        # debug_config = {
        #     'model': self.model_config.model,
        #     'provider': 'openrouter',
        #     'streaming': stream if stream is not None else self.model_config.streaming_enabled,
        #     'reasoning_enabled': bool(self.model_config.get_reasoning_config()),
        #     'temperature': temperature if temperature is not None else self.model_config.temperature,
        #     'max_tokens': max_tokens or self.model_config.max_tokens
        # }
        # request_id = debug_request(messages, debug_config, "openrouter_completion")
        
        # self.logger.info(f"[OpenRouterGateway] ENTERING get_response [{request_id}]: stream_arg={stream}, stream_callback_arg={stream_callback}, model_config_streaming={self.model_config.streaming_enabled}")

        # Determine if streaming should be used *based on the passed flag first*
        # If stream is explicitly False, don't stream, even if config says yes.
        # If stream is explicitly True, try to stream.
        # If stream is None, fall back to config.
        use_streaming = stream if stream is not None else self.model_config.streaming_enabled
        
        # If streaming is decided but no callback is provided, log warning and disable
        if use_streaming and stream_callback is None:
            self.logger.warning("Streaming requested/configured but no stream_callback provided. Falling back to non-streaming mode.")
            use_streaming = False

        # --- Process messages for vision and reformat conversation --- 
        try:
            processed_messages = await self._process_messages_for_vision(messages)
            # Reformat conversation to be compatible with OpenAI SDK while preserving content
            processed_messages = self._clean_conversation_format(processed_messages)
        except Exception as e:
            # error_context = {'request_id': request_id, 'phase': 'vision_processing', 'messages_count': len(messages)}
            # debug_error(e, error_context)
            self.logger.error(f"Error processing messages for vision and conversation format: {e}", exc_info=True)
            return f"[Error: Failed to process message content - {str(e)}]"
        # --- End vision and conversation processing ---

        # --- Reasoning tokens configuration ---
        reasoning_config = self.model_config.get_reasoning_config()

        request_params = {
            "model": self.model_config.model,
            "messages": processed_messages, # Use processed messages
            "max_tokens": max_tokens or self.model_config.max_tokens,
            "temperature": temperature if temperature is not None else self.model_config.temperature,
            "stream": use_streaming,
            "extra_headers": self.extra_headers,
            **kwargs # Pass through other arguments like tools
        }
        
        # Add new unified reasoning parameter if reasoning is enabled
        if reasoning_config:
            # Use new unified reasoning format instead of include_reasoning
            if isinstance(reasoning_config, dict):
                request_params["reasoning"] = reasoning_config
                self.logger.info(f"[OpenRouterGateway] Using new reasoning config: {reasoning_config}")
            else:
                # Fallback to simple enabled format for backwards compatibility
                request_params["reasoning"] = {"enabled": True}
                self.logger.info(f"[OpenRouterGateway] Using basic reasoning config with enabled=True")
        
        # Handle reasoning configuration - always use direct API for reasoning
        use_direct_api = bool(reasoning_config)
        if reasoning_config:
            self.logger.info(f"[OpenRouterGateway] Reasoning enabled, will use direct API call to bypass SDK limitations")
            
        # Filter out None values for cleaner API calls
        request_params = {k: v for k, v in request_params.items() if v is not None}

        self.logger.debug(f"Calling OpenRouter chat completion with params: "
                          f"model={request_params.get('model')}, "
                          f"stream={use_streaming}, "
                          f"max_tokens={request_params.get('max_tokens')}, "
                          f"temp={request_params.get('temperature')}, "
                          f"headers={request_params.get('extra_headers')}, "
                          f"reasoning={request_params.get('reasoning')}, "
                          f"other_keys={list(kwargs.keys())}")

        full_response_content = ""
        full_reasoning_content = ""
        
        # Use direct API call if reasoning is enabled to avoid SDK compatibility issues
        if use_direct_api:
            self.logger.debug(f"[OpenRouterGateway] Using direct API call for reasoning support")
            return await self._direct_api_call_with_reasoning(
                request_params, reasoning_config, use_streaming, stream_callback
            )
        
        # Use OpenAI SDK for non-reasoning requests
        try:
            completion = await self.client.chat.completions.create(**request_params)
        except Exception:
            raise
            
        try:

            if use_streaming:
                # self.logger.info(f"[OpenRouterGateway] Starting stream processing loop [{request_id}].")
                # debug_stream_start(request_id, debug_config)
                chunk_index = 0
                # Separate accumulators for reasoning and content
                _gateway_accumulated_reasoning = ""
                _gateway_accumulated_content = ""
                reasoning_phase_complete = False
                
                async for chunk in completion:
                    delta_obj = chunk.choices[0].delta

                    # ChoiceDelta objects expose attributes but not dict methods; fall back to dict check.
                    content_delta = getattr(delta_obj, "content", None)
                    if content_delta is None and isinstance(delta_obj, dict):
                        content_delta = delta_obj.get("content")

                    reasoning_delta = getattr(delta_obj, "reasoning", None)
                    if reasoning_delta is None and isinstance(delta_obj, dict):
                        reasoning_delta = delta_obj.get("reasoning")
                    tool_calls_delta = delta_obj.tool_calls

                    try:
                        chunk_log = f"[OpenRouterGateway] Raw Chunk {chunk_index}: ID={chunk.id}, Model={chunk.model}, FinishReason={chunk.choices[0].finish_reason}, DeltaContent='{content_delta}', DeltaReasoning='{reasoning_delta}', DeltaTools='{tool_calls_delta}'"
                    except Exception:
                        chunk_log = f"[OpenRouterGateway] Raw Chunk {chunk_index} (Minimal Log): DeltaContent='{content_delta}', DeltaReasoning='{reasoning_delta}'"
                    self.logger.debug(chunk_log)
                    chunk_index += 1

                    # Handle reasoning tokens
                    if reasoning_delta and not reasoning_phase_complete:
                        new_reasoning_segment = ""
                        if reasoning_delta.startswith(_gateway_accumulated_reasoning):
                            new_reasoning_segment = reasoning_delta[len(_gateway_accumulated_reasoning):]
                        else:
                            new_reasoning_segment = reasoning_delta
                        
                        if new_reasoning_segment:
                            _gateway_accumulated_reasoning += new_reasoning_segment
                            # debug_stream_chunk(request_id, {'chunk': new_reasoning_segment, 'type': 'reasoning'}, "reasoning")
                            if stream_callback:
                                try:
                                    if new_reasoning_segment.strip():
                                        self.logger.debug(f"[OpenRouterGateway] Calling stream_callback with reasoning segment: '{new_reasoning_segment}'")
                                        # Use a special message type to indicate reasoning
                                        await stream_callback(new_reasoning_segment, "reasoning")
                                except Exception as cb_err:
                                    self.logger.error(f"[OpenRouterGateway] Error in reasoning stream_callback: {cb_err}", exc_info=True)
                        
                        full_reasoning_content = _gateway_accumulated_reasoning

                    # Handle content tokens
                    elif content_delta:
                        # Mark reasoning phase as complete when we start getting content
                        if not reasoning_phase_complete and _gateway_accumulated_reasoning:
                            reasoning_phase_complete = True
                            self.logger.debug("[OpenRouterGateway] Reasoning phase complete, switching to content phase")
                        
                        new_content_segment = ""
                        if content_delta.startswith(_gateway_accumulated_content):
                            new_content_segment = content_delta[len(_gateway_accumulated_content):]
                        else:
                            new_content_segment = content_delta
                        
                        if new_content_segment:
                            _gateway_accumulated_content += new_content_segment
                            # debug_stream_chunk(request_id, {'chunk': new_content_segment, 'type': 'content'}, "content")
                            if stream_callback:
                                try:
                                    if new_content_segment.strip():
                                        self.logger.debug(f"[OpenRouterGateway] Calling stream_callback with content segment: '{new_content_segment}'")
                                        await stream_callback(new_content_segment, "assistant")
                                except Exception as cb_err:
                                    self.logger.error(f"[OpenRouterGateway] Error in content stream_callback: {cb_err}", exc_info=True)
                        
                        full_response_content = _gateway_accumulated_content

                    elif tool_calls_delta:
                         self.logger.debug(f"[OpenRouterGateway] Received tool_calls delta: {tool_calls_delta}.")
                         # Tool call streaming logic would go here if needed for external callback
                    else:
                        self.logger.debug(f"[OpenRouterGateway] Chunk {chunk_index-1} had no text/reasoning/tool delta.")

                # self.logger.info(f"[OpenRouterGateway] Finished stream [{request_id}]. Accumulated reasoning length: {len(full_reasoning_content)}, content length: {len(full_response_content)}")
                # debug_stream_complete(request_id, full_response_content)

                # For streaming responses, we return only the content part
                # The reasoning was already streamed via callback
                return full_response_content

            else: # Not streaming
                # Extract content and reasoning
                if completion.choices and completion.choices[0].message:
                     response_message = completion.choices[0].message
                     full_response_content = response_message.content or ""
                     
                     # Extract reasoning if present
                     reasoning_content = getattr(response_message, 'reasoning', None)
                     if reasoning_content:
                         full_reasoning_content = reasoning_content
                         self.logger.info(f"[OpenRouterGateway] Non-streaming response includes reasoning tokens: {len(reasoning_content)} chars")
                         
                         # If reasoning is not excluded, we could prepend it to the response
                         # or handle it separately based on configuration
                         if not self.model_config.reasoning_exclude and reasoning_content:
                             # For non-streaming, we can emit the reasoning via callback if provided
                             if stream_callback:
                                 try:
                                     await stream_callback(reasoning_content, "reasoning")
                                 except Exception as cb_err:
                                     self.logger.error(f"[OpenRouterGateway] Error in non-streaming reasoning callback: {cb_err}", exc_info=True)

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
            # error_context = {'request_id': request_id, 'phase': 'api_call', 'model': self.model_config.model}
            # debug_error(e, error_context)
            self.logger.error(f"OpenRouter API error [{request_id}]: {e}", exc_info=True)
            return f"[Error: OpenRouter API Error - {e.status_code} - {e.message}]"
        except Exception as e:
            # error_context = {'request_id': request_id, 'phase': 'unexpected', 'model': self.model_config.model}
            # debug_error(e, error_context)
            self.logger.error(f"Unexpected error during OpenRouter API call [{request_id}]: {e}", exc_info=True)
            return f"[Error: Unexpected error communicating with OpenRouter - {str(e)}]"

    async def _direct_api_call_with_reasoning(
        self,
        request_params: Dict[str, Any],
        reasoning_config: Dict[str, Any],
        use_streaming: bool,
        stream_callback: Optional[Callable[[str, str], None]]
    ) -> str:
        """
        Make a direct HTTP call to OpenRouter API with reasoning support.
        
        This bypasses the OpenAI SDK when it doesn't support the reasoning parameter.
        """
        # Remove parameters that are SDK-specific
        direct_params = request_params.copy()
        extra_headers = direct_params.pop("extra_headers", {})
        
        # Add reasoning configuration using new unified format
        direct_params["reasoning"] = reasoning_config
        # Remove include_reasoning - now using unified reasoning parameter
        
        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json",
            **extra_headers
        }
        
        url = "https://openrouter.ai/api/v1/chat/completions"
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                if use_streaming:
                    return await self._handle_streaming_response(
                        client, url, headers, direct_params, stream_callback
                    )
                else:
                    return await self._handle_non_streaming_response(
                        client, url, headers, direct_params, stream_callback
                    )
                    
        except Exception as e:
            self.logger.error(f"Direct API call failed: {e}", exc_info=True)
            return f"[Error: Direct API call failed - {str(e)}]"

    async def _handle_streaming_response(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        stream_callback: Optional[Callable[[str, str], None]]
    ) -> str:
        """Handle streaming response from direct API call."""
        params["stream"] = True
        
        full_content = ""
        full_reasoning = ""
        reasoning_phase_complete = False
        
        async with client.stream("POST", url, headers=headers, json=params) as response:
            if response.status_code != 200:
                error_text = (await response.aread()).decode()
                self.logger.error(f"Direct API call failed with status {response.status_code}: {error_text}")
                return f"[Error: API call failed with status {response.status_code}]"
            
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                    
                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix
                    
                    if data_str.strip() == "[DONE]":
                        break
                        
                    try:
                        data = json.loads(data_str)
                        choice = data.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        
                        # Handle reasoning content
                        reasoning_delta = getattr(delta, "reasoning", None) if hasattr(delta, "reasoning") else delta.get("reasoning")
                        if reasoning_delta and not reasoning_phase_complete:
                            full_reasoning += reasoning_delta
                            if stream_callback:
                                try:
                                    await stream_callback(reasoning_delta, "reasoning")
                                except Exception as cb_err:
                                    self.logger.error(f"Error in reasoning callback: {cb_err}")
                        
                        # Handle regular content
                        content_delta = getattr(delta, "content", None) if hasattr(delta, "content") else delta.get("content")
                        if content_delta:
                            if not reasoning_phase_complete and full_reasoning:
                                reasoning_phase_complete = True
                                self.logger.debug("Reasoning phase complete, switching to content")
                            
                            full_content += content_delta
                            if stream_callback:
                                try:
                                    await stream_callback(content_delta, "assistant")
                                except Exception as cb_err:
                                    self.logger.error(f"Error in content callback: {cb_err}")
                        
                    except json.JSONDecodeError as e:
                        self.logger.warning(f"Failed to parse SSE data: {data_str[:100]}... Error: {e}")
                        continue
        
        self.logger.info(f"Direct streaming call completed. Reasoning: {len(full_reasoning)} chars, Content: {len(full_content)} chars")
        return full_content

    async def _handle_non_streaming_response(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        stream_callback: Optional[Callable[[str, str], None]]
    ) -> str:
        """Handle non-streaming response from direct API call."""
        params["stream"] = False
        
        response = await client.post(url, headers=headers, json=params)
        
        if response.status_code != 200:
            error_text = response.text
            self.logger.error(f"Direct API call failed with status {response.status_code}: {error_text}")
            return f"[Error: API call failed with status {response.status_code}]"
        
        try:
            data = response.json()
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            
            # Some providers include keys with explicit None values; coalesce to empty strings
            content = message.get("content") or ""
            reasoning = message.get("reasoning") or ""
            
            # If we have reasoning and a callback, emit it
            if reasoning and stream_callback:
                try:
                    await stream_callback(reasoning, "reasoning")
                except Exception as cb_err:
                    self.logger.error(f"Error in reasoning callback: {cb_err}")
            
            self.logger.info(f"Direct non-streaming call completed. Reasoning: {len(reasoning)} chars, Content: {len(content)} chars")
            return content
            
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse response JSON: {e}")
            return f"[Error: Failed to parse response - {str(e)}]"

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