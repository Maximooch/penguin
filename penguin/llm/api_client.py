import asyncio
import base64
import io
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Union

import yaml  # type: ignore
import tiktoken  # type: ignore

# TODO: decouple litellm from api_client. # Been done for quite a while. 
# TODO: greatly simplify api_client while maintaining full functionality
# TODO: add streaming support # Done for quite a while. 
# TODO: add support for images, files, audio, and video
# Lazy import litellm to avoid 1+ second import time overhead
# from litellm import acompletion, completion, token_counter, cost_per_token, completion_cost
from PIL import Image  # type: ignore

from .model_config import ModelConfig
from .adapters import get_adapter # Keep for native preference
# Lazy import gateways to avoid import overhead
# from .litellm_gateway import LiteLLMGateway
# from .openrouter_gateway import OpenRouterGateway
# from penguin.llm.provider_adapters import get_provider_adapter # Seems unused

logger = logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    """Load Penguin config using central resolver, with safe fallback.

    Delegates to penguin.config.load_config, which already checks:
    - PENGUIN_CONFIG_PATH
    - ~/.config/penguin/config.yml (or platform equivalent)
    - dev/repo defaults
    Returns an empty dict on failure instead of raising during import.
    """
    try:
        from penguin.config import load_config as core_load_config
        data = core_load_config()
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"api_client.load_config fallback: {e}")
        return {}


# Load the model configurations from the config file
MODEL_CONFIGS = load_config().get("model_configs", {})


class APIClient:
    """
    A client for interacting with various AI model APIs, routing requests
    to either a native adapter or the LiteLLM gateway based on configuration.

    Attributes:
        model_config (ModelConfig): Configuration for the AI model.
        system_prompt (str): The system prompt to be sent with each request.
        client_handler (Any): The actual handler instance (native adapter or LiteLLMGateway).
        logger (logging.Logger): Logger for this class.
    """

    def __init__(self, model_config: ModelConfig):
        """
        Initialize the APIClient.

        Args:
            model_config (ModelConfig): Configuration for the AI model, including
                                        the 'client_preference'.
        """
        self.model_config = model_config
        self.system_prompt = None
        self.logger = logging.getLogger(__name__)
        self.client_handler = None # Will be set based on preference

        self.logger.info(f"Initializing APIClient for model: {model_config.model}, "
                         f"Provider: {model_config.provider}, "
                         f"Preference: {model_config.client_preference}")

        # --- Instantiate the correct handler ---
        if model_config.client_preference == 'litellm':
            try:
                # Lazy import LiteLLMGateway to avoid import overhead
                from .litellm_gateway import LiteLLMGateway
                # LiteLLM gateway handles API keys/base internally based on model_config
                self.client_handler = LiteLLMGateway(model_config)
                self.logger.info(f"Using LiteLLMGateway for {model_config.model}")
            except Exception as e:
                self.logger.error(f"Failed to initialize LiteLLMGateway: {e}", exc_info=True)
                raise ValueError(f"Could not initialize LiteLLMGateway: {e}") from e

        elif model_config.client_preference == 'openrouter':
            try:
                # Lazy import OpenRouterGateway to avoid import overhead
                from .openrouter_gateway import OpenRouterGateway
                # Initialize OpenRouter gateway with model_config
                self.client_handler = OpenRouterGateway(model_config)
                self.logger.info(f"Using OpenRouterGateway for {model_config.model}")
            except Exception as e:
                self.logger.error(f"Failed to initialize OpenRouterGateway: {e}", exc_info=True)
                raise ValueError(f"Could not initialize OpenRouterGateway: {e}") from e

        elif model_config.client_preference == 'native':
            try:
                # Get native adapter
                # Note: Native adapters might expect simpler model names in model_config.model
                self.client_handler = get_adapter(model_config.provider, model_config)
                if not self.client_handler:
                     raise ValueError(f"No native adapter found for provider: {model_config.provider}")
                self.logger.info(f"Using native adapter for provider: {model_config.provider} "
                                 f"(Model: {model_config.model})")
                # Native adapter might need API key directly (handled by get_adapter?)
                # self.api_key = model_config.api_key # Store if needed separately? get_adapter should handle it.

            except Exception as e:
                self.logger.error(f"Failed to initialize native adapter for {model_config.provider}: {e}", exc_info=True)
                raise ValueError(f"Could not initialize native adapter: {e}") from e
        else:
            raise ValueError(f"Invalid client_preference: {model_config.client_preference}. Must be 'native', 'litellm', or 'openrouter'.")

        # Common properties (potentially less relevant now?)
        self.max_history_tokens = model_config.max_history_tokens or 200000

        # Clean up old logging/prints
        # print("\n=== API Client Initialization ===")
        # print(f"Model: {model_config.model}") # Logged above
        # print(f"Provider: {model_config.provider}") # Logged above
        # print(f"Client Handler: {type(self.client_handler).__name__}") # Logged above
        # print(f"API Key Present: {bool(model_config.api_key)}") # Less direct control now
        # print("===============================\n")

        # OpenAI Assistants API handling - needs review
        # This seems tied to OpenAI native implementation. How does it fit with LiteLLM?
        # LiteLLM has its own proxy endpoint for assistants. If using that, this logic is wrong.
        # If using OpenAI native adapter, this might still be relevant.
        # Let's comment it out for now, needs rethinking based on how Assistants are used.
        # if model_config.use_assistants_api and model_config.provider == 'openai' and model_config.client_preference == 'native':
        #     self.logger.info("Attempting to use OpenAI Assistants API via native adapter")
        #     # Logic for Assistants API tied to native adapter needs confirmation
        #     if hasattr(self.client_handler, 'assistant_manager'):
        #          self.logger.info("Native adapter has assistant manager.")
        #     else:
        #          self.logger.warning("Native adapter selected with use_assistants_api=True, but adapter lacks assistant_manager.")
        # else:
        #      pass # Not using assistants or not using OpenAI native

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self.system_prompt = prompt
        # TODO: How to pass system prompt?
        # Native adapters might have specific methods.
        # LiteLLM expects it in the messages list.
        # We might need to handle this within get_response based on handler type.
        self.logger.debug(f"System prompt set. Length: {len(prompt)}")
        # Commenting out assistant-specific update for now
        # if self.model_config.use_assistants_api and hasattr(self.client_handler, 'assistant_manager'):
        #     self.client_handler.assistant_manager.update_system_prompt(prompt)

    def _prepare_messages_with_system_prompt(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Inject the system prompt while preserving other system‑role
        messages (e.g. action results, iteration markers).
        """
        if not self.system_prompt:
            return messages[:]          # nothing to do

        processed = []
        prompt_already_present = False

        for msg in messages:
            if msg.get("role") == "system":
                if msg.get("content") == self.system_prompt:
                    # Drop existing duplicate of the global prompt
                    prompt_already_present = True
                else:
                    # KEEP other system messages (action results, etc.)
                    processed.append(msg)
            else:
                processed.append(msg)

        # Ensure the global system prompt is in slot‑0
        if not prompt_already_present:
            processed.insert(0, {"role": "system", "content": self.system_prompt})
        else:
            # If some other message grabbed index‑0, still enforce the prompt first
            if processed and processed[0].get("content") != self.system_prompt:
                processed.insert(0, {"role": "system", "content": self.system_prompt})

        return processed

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: Optional[bool] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any
    ) -> str:
        """
        Get a response from the configured AI model, using the chosen client handler.

        Args:
            messages: List of message dictionaries (OpenAI format).
            max_tokens: Optional max tokens to generate.
            temperature: Optional temperature parameter.
            stream: Optional override for streaming preference.
            stream_callback: Callback for handling streaming chunks. Should accept (chunk: str, message_type: str).
            **kwargs: Additional parameters to pass to the handler (e.g., reasoning config).

        Returns:
            The complete response text from the model.
        """
        if not self.client_handler:
            raise RuntimeError("APIClient handler not initialized.")

        use_streaming = stream if stream is not None else self.model_config.streaming_enabled
        prepared_messages = self._prepare_messages_with_system_prompt(messages)

        # <<<--- ADD THIS LOGGING for PREPARED MESSAGES ---<<<
        request_id_api = os.urandom(4).hex() # Simple ID for this layer
        self.logger.info(f"[Request:{request_id_api}] APIClient calling handler {type(self.client_handler).__name__}.get_response")
        try:
             safe_msgs_for_log = []
             for msg in prepared_messages:
                  role = msg.get('role', 'unknown')
                  content_log = "[omitted]"
                  if isinstance(msg.get('content'), str):
                       content_log = msg['content'][:100] + ("..." if len(msg['content']) > 100 else "")
                  elif isinstance(msg.get('content'), list):
                       content_log = f"[{len(msg['content'])} parts: " + ", ".join([p.get('type', 'unknown') for p in msg['content']]) + "]"
                  safe_msgs_for_log.append({"role": role, "content": content_log})
             self.logger.debug(f"[Request:{request_id_api}] Messages passed to handler (summary): {safe_msgs_for_log}")

             # <<<--- Add Token Count Logging ---<<<
             try:
                 final_token_count = self.count_tokens(prepared_messages)
                 self.logger.info(f"[Request:{request_id_api}] Estimated token count for prepared messages: {final_token_count}")
                 if final_token_count > (self.max_history_tokens * 0.95): # Warn if close to limit
                      self.logger.warning(f"[Request:{request_id_api}] Prepared message token count ({final_token_count}) is close to limit ({self.max_history_tokens}).")
             except Exception as count_err:
                 self.logger.warning(f"[Request:{request_id_api}] Failed to count tokens for prepared messages: {count_err}")
             # >>> --- End Token Count Logging --- >>>

        except Exception as log_err:
             self.logger.warning(f"[Request:{request_id_api}] Error creating safe log/counting tokens for prepared_messages: {log_err}")
        # >>>------------------------------------------- >>>

        try:
            # --- Ideal Flow (Enforce Interface - See Step 2) ---
            if not hasattr(self.client_handler, 'get_response'):
                 # This should ideally not happen if Step 2 is done.
                 self.logger.error(f"CRITICAL: Client handler {type(self.client_handler).__name__} missing required 'get_response' method!")
                 return f"[Error: Handler {type(self.client_handler).__name__} interface mismatch]"

            # <<< ADD LOGGING HERE >>>
            effective_callback = stream_callback if use_streaming else None
            self.logger.debug(f"[APIClient:{request_id_api}] Calling {type(self.client_handler).__name__}.get_response. Streaming: {use_streaming}. Callback Provided: {effective_callback is not None}")
            
            # Ensure the callback is async and handles the new signature if provided
            if effective_callback and not asyncio.iscoroutinefunction(effective_callback):
                # Convert to async function if it's not already
                original_callback = effective_callback
                self.logger.debug(f"[APIClient:{request_id_api}] Converting non-async callback to async")
                
                async def async_callback_wrapper(chunk: str, message_type: str = "assistant"):
                    # Call the original callback in an asyncio-friendly way
                    try:
                        # Check if the original callback accepts message_type parameter
                        import inspect
                        sig = inspect.signature(original_callback)
                        params = list(sig.parameters.keys())
                        
                        if len(params) >= 2:
                            # Callback accepts message_type
                            if asyncio.iscoroutinefunction(original_callback):
                                await original_callback(chunk, message_type)
                            else:
                                # Run sync callback in thread pool to avoid blocking
                                await asyncio.get_event_loop().run_in_executor(
                                    None, original_callback, chunk, message_type
                                )
                        else:
                            # Legacy callback that only accepts chunk
                            if asyncio.iscoroutinefunction(original_callback):
                                await original_callback(chunk)
                            else:
                                await asyncio.get_event_loop().run_in_executor(
                                    None, original_callback, chunk
                                )
                    except Exception as e:
                        self.logger.error(f"[APIClient:{request_id_api}] Error in callback: {e}")
                
                effective_callback = async_callback_wrapper
            elif effective_callback and asyncio.iscoroutinefunction(effective_callback):
                # Already async, but we need to ensure it handles the signature properly
                original_async_callback = effective_callback
                
                async def async_signature_wrapper(chunk: str, message_type: str = "assistant"):
                    try:
                        # Check if the async callback accepts message_type parameter
                        import inspect
                        sig = inspect.signature(original_async_callback)
                        params = list(sig.parameters.keys())
                        
                        if len(params) >= 2:
                            await original_async_callback(chunk, message_type)
                        else:
                            # Legacy async callback
                            await original_async_callback(chunk)
                    except Exception as e:
                        self.logger.error(f"[APIClient:{request_id_api}] Error in async callback: {e}")
                
                effective_callback = async_signature_wrapper
            
            if effective_callback:
                 self.logger.debug(f"[APIClient:{request_id_api}] Callback object details: {effective_callback}")
            # <<< END LOGGING >>>

            self.logger.info(f"[APIClient:{request_id_api}] PRE-CALL TO HANDLER: use_streaming={use_streaming}, effective_callback is {effective_callback}")

            response_text = await self.client_handler.get_response(
                messages=prepared_messages,
                max_tokens=max_tokens or self.model_config.max_tokens,
                temperature=temperature if temperature is not None else self.model_config.temperature,
                stream=use_streaming,
                stream_callback=effective_callback, # Pass the potentially wrapped async callback
                **kwargs  # Pass through additional parameters like reasoning config
            )

            # If streaming, the callback handled output. Return minimal response.
            # The response_text here is the final accumulated text from the gateway.
            if use_streaming:
                logger.info(f"[APIClient:{request_id_api}] Stream finished. Returning accumulated text (length: {len(response_text or '')}).")
                # In streaming mode, we rely on the callback for output.
                # We return the final accumulated text, but core.py might ignore it.
                return response_text or "" # Return accumulated string

            # <<<--- ADD Check for Error/Placeholder Strings ---<<<
            if isinstance(response_text, str):
                if response_text.startswith("[Error:") or response_text.startswith("[Model finished"):
                     self.logger.warning(f"[Request:{request_id_api}] Handler returned non-content string: {response_text}")
                     # Propagate this specific info instead of just empty?
                     # Maybe core.py needs to check for these specific strings too.
                     # For now, returning it might still trigger core's retry loop if core only checks for "" or None.
                     # Let's return it as is for now, core needs adjustment later if this is the case.

                elif not response_text.strip() and not use_streaming:
                     # Log if we get an empty string in non-streaming mode
                     self.logger.warning(f"[Request:{request_id_api}] Handler returned empty string in non-streaming mode.")
            # >>>----------------------------------------------->>>

            return response_text
            # --- End Ideal Flow ---

        except Exception as e:
            error_message = f"LLM API call failed via {type(self.client_handler).__name__}: {str(e)}"
            self.logger.error(error_message, exc_info=True)
            # Return the error message to the user interface
            return f"Error: {error_message}"


    # --- Methods below might be simplified or removed if get_response handles all ---

    # process_response is likely no longer needed here, as the handler should return processed text
    # def process_response(self, response: Any) -> tuple[str, List[Any]]:
    #     """Process the raw response (delegated to handler if possible)."""
    #     # This logic is now likely within the handler's get_response or internal methods
    #     logger.warning("APIClient.process_response called - this might be deprecated.")
    #     if hasattr(self.client_handler, 'process_response'):
    #         try:
    #              # Assuming native adapter style response processing
    #              content, tool_uses = self.client_handler.process_response(response)
    #              return content, tool_uses
    #         except Exception as e:
    #              logger.error(f"Error in handler's process_response: {e}", exc_info=True)
    #              return f"[Error processing response: {e}]", []
    #     else:
    #          # LiteLLM gateway handles processing internally in its get_response
    #          logger.info("Handler does not have process_response, assuming processed result already handled.")
    #          # We expect get_response to return the final string now
    #          if isinstance(response, str):
    #               return response, [] # Assume response *is* the content string
    #          else:
    #               return "[Error: Unexpected response type after handler call]", []


    # create_message might be replaced by get_response logic
    # async def create_message(
    #     self,
    #     messages: List[Dict[str, Any]],
    #     max_tokens: Optional[int] = None,
    #     temperature: Optional[float] = None,
    # ) -> Any:
    #     """ Deprecated: Use get_response instead """
    #     logger.warning("APIClient.create_message called - this is likely deprecated. Use get_response.")
    #     # This logic should be part of the get_response implementation or the handler itself
    #     response_text = await self.get_response(
    #         messages=messages,
    #         max_tokens=max_tokens,
    #         temperature=temperature,
    #         stream=False # create_message implies non-streaming
    #     )
    #     # Need to return something compatible with old flow if called?
    #     # This is problematic. Better to refactor callers to use get_response.
    #     return {"choices": [{"message": {"content": response_text}}]} # Simulate OpenAI structure


    # create_streaming_completion might be replaced by get_response logic
    # async def create_streaming_completion(
    #     self,
    #     messages: List[Dict[str, Any]],
    #     max_tokens: Optional[int] = None,
    #     temperature: Optional[float] = None,
    #     stream_callback: Optional[Callable[[str], None]] = None
    # ) -> str:
    #     """ Deprecated: Use get_response with stream=True instead """
    #     logger.warning("APIClient.create_streaming_completion called - this is likely deprecated. Use get_response.")
    #     return await self.get_response(
    #          messages=messages,
    #          max_tokens=max_tokens,
    #          temperature=temperature,
    #          stream=True,
    #          stream_callback=stream_callback
    #     )


    # Token counting delegated
    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """
        Count tokens for content, using the chosen client handler.

        Args:
            content: Text or structured content to count tokens for

        Returns:
            Token count as integer
        """
        if not self.client_handler:
            self.logger.error("Cannot count tokens, client handler not initialized.")
            return len(str(content)) // 4 # Very rough fallback

        if not self.model_config.enable_token_counting:
             self.logger.debug("Token counting disabled in ModelConfig.")
             return 0

        if hasattr(self.client_handler, 'count_tokens'):
            try:
                # Use the handler's count_tokens method
                return self.client_handler.count_tokens(content)
            except Exception as e:
                self.logger.warning(f"Token counting failed using {type(self.client_handler).__name__}: {e}")
                # Fallback to LiteLLM's generic counter if handler fails?
                try:
                     logger.info(f"Falling back to LiteLLM generic token counter for model {self.model_config.model}")
                     # Ensure model name is suitable for LiteLLM counter
                     model_for_counting = self.model_config.model
                     if isinstance(content, str):
                          return token_counter(model=model_for_counting, text=content)
                     elif isinstance(content, list):
                           # Assume OpenAI message format for LiteLLM counter
                          return token_counter(model=model_for_counting, messages=content)
                     else:
                          return len(str(content)) // 4 # Rough fallback
                except Exception as litellm_e:
                     self.logger.error(f"LiteLLM generic token counter also failed: {litellm_e}")
                     return len(str(content)) // 4 # Final rough fallback
        else:
            self.logger.warning(f"Client handler {type(self.client_handler).__name__} does not implement count_tokens.")
            # Fallback to LiteLLM generic counter?
            try:
                logger.info(f"Falling back to LiteLLM generic token counter for model {self.model_config.model}")
                model_for_counting = self.model_config.model
                if isinstance(content, str):
                    return token_counter(model=model_for_counting, text=content)
                elif isinstance(content, list):
                    return token_counter(model=model_for_counting, messages=content)
                else:
                    return len(str(content)) // 4
            except Exception as litellm_e:
                self.logger.error(f"LiteLLM generic token counter also failed: {litellm_e}")
                return len(str(content)) // 4

    def _truncate_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Truncate the conversation history to fit within the maximum token limit,
        using the handler's token counting method.
        """
        total_tokens = 0
        truncated_messages = []
        # Ensure system prompt is preserved if present (should be first)
        system_msg = None
        processed_messages = messages[:] # Copy
        if processed_messages and processed_messages[0].get("role") == "system":
             system_msg = processed_messages.pop(0)
             # Count system prompt tokens separately
             system_tokens = self.count_tokens(system_msg['content']) if system_msg else 0
             total_tokens += system_tokens


        # Iterate through remaining messages in reverse
        for message in reversed(processed_messages):
            # Count tokens for the current message
            message_tokens = self.count_tokens(message) # Use the central count_tokens method

            if total_tokens + message_tokens > self.max_history_tokens:
                self.logger.warning(
                    f"Truncating history: Limit {self.max_history_tokens}, "
                    f"Current total {total_tokens}, "
                    f"Next msg tokens {message_tokens}. Stopping."
                )
                break
            total_tokens += message_tokens
            truncated_messages.insert(0, message) # Add to the beginning

        # Re-add system prompt if it existed
        if system_msg:
            truncated_messages.insert(0, system_msg)

        num_truncated = len(messages) - len(truncated_messages)
        if num_truncated > 0:
            self.logger.info(f"Truncated {num_truncated} messages from history. "
                             f"Final token count (approx): {total_tokens}")

        return truncated_messages

    def encode_image_to_base64(self, image_path: str) -> str:
        """
        Encode an image file to a base64 string. (Moved to gateway, keep here for compatibility?)
        This might only be relevant for native adapters that don't handle it.
        LiteLLM gateway handles encoding internally. Let's keep it for now.
        """
        # ... (encode_image_to_base64 remains the same) ...
        try:
            with Image.open(image_path) as img:
                max_size = (1024, 1024)
                img.thumbnail(max_size, Image.LANCZOS)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format="JPEG")
                return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
        except Exception as e:
            self.logger.error(f"Error encoding image {image_path}: {str(e)}")
            return f"Error encoding image: {str(e)}"


    def reset(self):
        """Reset the client state (primarily the system prompt)."""
        # self.messages = [] # History is managed by the caller (e.g., Core)
        # Resetting the handler might be complex, just clear the prompt for now
        self.system_prompt = None
        self.logger.info("APIClient state reset (system prompt cleared).")
        # Re-applying system prompt might require calling set_system_prompt again by caller
