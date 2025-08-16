import asyncio
import base64
import logging
import os
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple, AsyncIterator, Callable, Union

import anthropic
from anthropic.types import ContentBlock, MessageParam # type: ignore
from anthropic import AsyncAnthropic, Anthropic

from .base import BaseAdapter
from ..model_config import ModelConfig

logger = logging.getLogger(__name__)

class AnthropicAdapter(BaseAdapter):
    """Direct Anthropic SDK adapter"""
    
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")
        
        # Initialize synchronous client for token counting
        self.sync_client = anthropic.Anthropic(api_key=self.api_key)
        
        # Initialize async client for message creation
        self.async_client = AsyncAnthropic(api_key=self.api_key)
        
        # Add a logger for the adapter
        self.logger = logging.getLogger(__name__)
    
    @property
    def provider(self) -> str:
        return "anthropic"
    
    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> Any:
        """Create a message using Anthropic's API directly"""
        try:
            # Format messages for Anthropic
            formatted_messages = self.format_messages(messages)
            
            # Prepare request parameters
            request_params = {
                "model": self.model_config.model,
                "messages": formatted_messages,
                "max_tokens": max_tokens or self.model_config.max_tokens or 8192,
                "temperature": temperature or self.model_config.temperature or 0.4,
            }
            
            # Add system prompt if provided (strip trailing whitespace)
            if system_prompt:
                request_params["system"] = system_prompt.rstrip()
            
            # Make the API call
            safe_params = self._safe_log_content(request_params.copy())
            # logger.warning(f"FINAL REQUEST TO ANTHROPIC: {safe_params}")

            # Log estimated input tokens before call
            try:
                input_tokens = self.count_tokens(messages) # Count original messages
                self.logger.debug(f"Estimated input tokens for Anthropic call: {input_tokens}")
            except Exception as tk_err:
                self.logger.warning(f"Could not estimate input tokens before call: {tk_err}")

            # Add double-check for trailing whitespace in all text content
            self._ensure_no_trailing_whitespace(request_params)
            
            self.logger.debug(f"Sending non-streaming request to Anthropic: Model={request_params['model']}, MaxTokens={request_params['max_tokens']}, Temp={request_params['temperature']}, SystemPromptLength={len(request_params.get('system', ''))}, NumMessages={len(request_params['messages'])}")
            
            response = await self.async_client.messages.create(**request_params)
            
            # Log the raw response object
            try:
                # Use pformat for potentially large/complex objects
                import pprint
                raw_response_str = pprint.pformat(response.model_dump()) # Convert pydantic model to dict for logging
                self.logger.debug(f"Raw Anthropic non-streaming response object:\n{raw_response_str}")
            except Exception as log_err:
                self.logger.warning(f"Error logging raw Anthropic response: {log_err}")

            return response
        
        except Exception as e:
            logger.error(f"Error in Anthropic API call: {str(e)}")
            # Add detailed error information
            logger.error(f"Error details: {traceback.format_exc()}")
            # Check if specific Anthropic error
            if hasattr(e, 'status_code'):
                logger.error(f"Anthropic API error code: {getattr(e, 'status_code')}")
            if hasattr(e, 'response'):
                # Log raw error response if available
                try:
                    import pprint
                    error_response_str = pprint.pformat(getattr(e, 'response'))
                    logger.error(f"Raw error response data:\n{error_response_str}")
                except Exception as log_err:
                    logger.warning(f"Error logging raw error response data: {log_err}")
            raise
    
    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> Any:
        """Create a completion request with optional streaming"""
        try:
            # Format messages for Anthropic
            formatted_messages = self.format_messages(messages)
            
            # Extract system message if present
            system_message = None
            for msg in messages:
                if msg.get("role") == "system":
                    system_message = msg.get("content", "")
                    # Strip trailing whitespace from system message
                    if system_message:
                        system_message = system_message.rstrip()
                    break
            
            # Prepare request parameters
            request_params = {
                "model": self.model_config.model,
                "messages": formatted_messages,
                "max_tokens": max_tokens or self.model_config.max_tokens or 4096,
                "temperature": temperature or self.model_config.temperature or 0.7,
                "stream": stream,
            }
            
            # Add system message if found
            if system_message:
                request_params["system"] = system_message
            
            # Make sure no trailing whitespace in any message
            self._ensure_no_trailing_whitespace(request_params)
            
            # Log estimated input tokens before call
            try:
                input_tokens = self.count_tokens(messages) # Count original messages
                self.logger.debug(f"Estimated input tokens for Anthropic call: {input_tokens}")
            except Exception as tk_err:
                self.logger.warning(f"Could not estimate input tokens before call: {tk_err}")
                
            # Make the API call
            safe_params = self._safe_log_content(request_params.copy())
            self.logger.debug(f"Sending request to Anthropic: Model={request_params['model']}, MaxTokens={request_params['max_tokens']}, Temp={request_params['temperature']}, SystemPromptLength={len(request_params.get('system', ''))}, NumMessages={len(request_params['messages'])}, Stream={stream}")
            
            if stream:
                return await self._handle_streaming(request_params, stream_callback)
            else:
                response = await self.async_client.messages.create(**request_params)
                # Log the raw response object for non-streaming completion as well
                try:
                    import pprint
                    raw_response_str = pprint.pformat(response.model_dump())
                    self.logger.debug(f"Raw Anthropic non-streaming completion response object:\n{raw_response_str}")
                except Exception as log_err:
                    self.logger.warning(f"Error logging raw Anthropic non-streaming completion response: {log_err}")
                return response
                
        except Exception as e:
            logger.error(f"Error in Anthropic API call: {str(e)}")
            raise

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Unified entrypoint to satisfy BaseAdapter interface.

        - Streams via create_completion when stream=True and returns accumulated text
        - Non-streaming: calls create_completion and processes the response
        """
        if stream:
            # Ensure callback is callable; pass through directly
            final_text = await self.create_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stream_callback=stream_callback,
            )
            # create_completion returns a string when streaming
            return final_text or ""

        # Non-streaming path
        response = await self.create_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
            stream_callback=None,
        )
        content, _ = self.process_response(response)
        return content or ""
    
    async def _handle_streaming(
        self, 
        params: Dict[str, Any], 
        callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """Handle streaming response from Anthropic API with enhanced error handling"""
        accumulated_response = []
        stream_start_time = time.time()
        streaming_timeout = 30  # seconds
        final_response_object = None # To store the final message object
        stream_error = None # To store any exception during streaming
        stop_reason = None # To store the stop reason if available
        usage_info = None # To store usage info if available
        
        try:
            # Create the streaming response
            stream = await self.async_client.messages.create(**params)
            
            # Track content reception
            received_content = False
            last_chunk_time = time.time()
            chunk_timeout = 10  # seconds
            chunk_count = 0
            
            # Process each chunk as it comes in
            async for chunk in stream:
                last_chunk_time = time.time()
                chunk_count += 1
                
                # Extract text content based on chunk type
                content = None
                
                try:
                    # Handle different event types
                    self.logger.debug(f"Received chunk type: {chunk.type} (Chunk {chunk_count})")
                    if hasattr(chunk, 'type'):
                        
                        if chunk.type == 'message_stop':
                             # Capture the final response object from the stream if possible
                             # Note: The structure might vary, need to check Anthropic docs/examples
                             # For now, just log that we stopped. The final object might not be in the chunk itself.
                             self.logger.debug("Stream processing stopped due to 'message_stop' event.")
                             # We might get the final message object *after* the loop, see below

                        elif chunk.type == 'content_block_delta' and hasattr(chunk, 'delta'):
                            if chunk.delta.type == 'text_delta' and hasattr(chunk.delta, 'text'):
                                content = chunk.delta.text
                        
                        elif chunk.type == 'content_block_start' and hasattr(chunk, 'content_block'):
                            if chunk.content_block.type == 'text' and hasattr(chunk.content_block, 'text'):
                                content = chunk.content_block.text
                        
                        elif chunk.type == 'message_delta' and hasattr(chunk, 'usage') and hasattr(chunk, 'stop_reason'):
                            # Capture usage and stop reason from message_delta if available
                            stop_reason = chunk.stop_reason
                            usage_info = chunk.usage
                            self.logger.debug(f"Received message_delta: stop_reason={stop_reason}, usage={usage_info}")

                    # Process extracted content
                    if content:
                        received_content = True
                        # self.logger.debug(f"Extracted content from chunk {chunk_count}: {content[:20]}...") # Less verbose logging
                        # Call the callback with the content
                        if callback:
                            callback(content)
                        # Add to accumulated response
                        accumulated_response.append(content)
                        
                except Exception as e:
                    error_msg = f"Error processing chunk {chunk_count}: {str(e)}"
                    self.logger.error(f"{error_msg}\n{traceback.format_exc()}")
                
                # Check for chunk timeout
                current_time = time.time()
                if current_time - last_chunk_time > chunk_timeout:
                    self.logger.warning(f"No chunks received for {chunk_timeout} seconds, stopping stream")
                    stream_error = TimeoutError(f"Chunk timeout after {chunk_timeout}s")
                    break
                
                # Check for overall timeout
                if current_time - stream_start_time > streaming_timeout:
                    self.logger.warning(f"Streaming exceeded timeout of {streaming_timeout} seconds, stopping")
                    stream_error = TimeoutError(f"Streaming timeout after {streaming_timeout}s")
                    break

            # ---- After the loop ----
            # Try to get the final message object AFTER the stream completes
            try:
                final_response_object = await stream.get_final_message()
                if final_response_object:
                    # Log the raw final message object from the stream
                    import pprint
                    final_object_str = pprint.pformat(final_response_object.model_dump())
                    self.logger.debug(f"Raw Anthropic final message object from stream:\n{final_object_str}")
                    # Extract final stop reason and usage if not already captured
                    if not stop_reason: stop_reason = final_response_object.stop_reason
                    if not usage_info: usage_info = final_response_object.usage
            except Exception as e:
                 self.logger.warning(f"Could not get final message object from stream: {e}")


            # Log streaming stats
            total_stream_time = time.time() - stream_start_time
            self.logger.info(f"Streaming complete: {chunk_count} chunks in {total_stream_time:.2f}s. Received content: {received_content}. Stop Reason: {stop_reason}. Usage: {usage_info}. Error: {stream_error}")
            
            # Join all chunks to get the complete response
            complete_response = ''.join(accumulated_response)
            
            # Validate the response
            if not received_content or len(complete_response.strip()) <= 5:
                # Handle suspiciously short responses
                self.logger.warning(f"Suspiciously short response received: '{complete_response}'. Stop Reason: {stop_reason}, Usage: {usage_info}")
                
                # Check if it's effectively empty (just whitespace or minimal punctuation)
                if complete_response.strip() in ['', '.', '?', '!', ','] or len(complete_response.strip()) <= 1:
                    error_message = f"I encountered an issue generating a response. The connection may have been interrupted or the response filtered. Stop Reason: {stop_reason}"
                    self.logger.error(f"Empty response detected: '{complete_response}'. Stop Reason: {stop_reason}, Usage: {usage_info}")
                    
                    # If we got nothing but have some chunks, try to salvage
                    if chunk_count > 0:
                        return error_message
                    else:
                        # Truly empty - raise exception to trigger retry
                        raise ValueError(f"Stream produced no content. Stop Reason: {stop_reason}")
            
            # Add detailed debugging for very short responses
            if 1 < len(complete_response.strip()) <= 5:
                self.logger.warning(f"Very short but non-empty response: '{complete_response}', from {chunk_count} chunks. Stop Reason: {stop_reason}")
            
            self.logger.debug(f"Returning final accumulated streaming response (length {len(complete_response)} chars)")
            return complete_response
            
        except asyncio.CancelledError as e:
            self.logger.warning("Anthropic streaming was cancelled")
            stream_error = e
            # Return what we've accumulated so far or an error message
            if accumulated_response:
                self.logger.info(f"Returning partial response from cancelled stream ({len(accumulated_response)} chunks)")
                return ''.join(accumulated_response)
            else:
                raise  # Re-raise to properly handle cancellation
            
        except Exception as e:
            stream_error = e
            error_msg = f"Error during Anthropic streaming: {str(e)}"
            self.logger.error(f"{error_msg}\n{traceback.format_exc()}")
            
            # Log more details about the streaming state
            elapsed_time = time.time() - stream_start_time
            self.logger.error(f"Stream error details: elapsed_time={elapsed_time:.2f}s, chunks_received={chunk_count}, stop_reason={stop_reason}, usage={usage_info}")
            
            if callback:
                callback(f"\n[Streaming Error: {str(e)}]")
                
            # Return partial response if we have any content
            if accumulated_response:
                self.logger.info(f"Returning partial response despite error ({chunk_count} chunks)")
                return ''.join(accumulated_response)
            
            # Otherwise return an error message including stop reason if available
            return f"Error during response generation: {str(e)}. Stop Reason: {stop_reason}"
        finally:
            # Log final state regardless of how we exited
             total_stream_time = time.time() - stream_start_time
             self.logger.info(f"Exiting _handle_streaming: Time={total_stream_time:.2f}s, Chunks={chunk_count}, ReceivedContent={received_content}, StopReason={stop_reason}, Usage={usage_info}, Error={stream_error}")


    def process_response(self, response: Any) -> Tuple[str, List[Any]]:
        """Process Anthropic API response into standardized format"""
        try:
            # Log the raw response object being processed
            self.logger.debug(f"Processing Anthropic response of type: {type(response)}")
            if hasattr(response, 'model_dump'): # Check if pydantic model
                 try:
                     import pprint
                     raw_response_str = pprint.pformat(response.model_dump())
                     self.logger.debug(f"Raw response object received by process_response:\n{raw_response_str}")
                 except Exception as log_err:
                     self.logger.warning(f"Error logging raw response in process_response: {log_err}")
            else:
                 self.logger.debug(f"Response object received by process_response (non-pydantic): {str(response)[:500]}...") # Log snippet if not easily dumpable


            # Handle AsyncAnthropic Message object (from non-streaming calls)
            if hasattr(response, 'content') and hasattr(response, 'stop_reason'):
                stop_reason = response.stop_reason
                usage = getattr(response, 'usage', None)
                
                # Extract text from content blocks
                text_content = []
                if response.content: # Ensure content is not None or empty
                    for block in response.content:
                        # Check if block is a ContentBlock pydantic model or dict
                        block_type = getattr(block, 'type', None) or (isinstance(block, dict) and block.get("type"))
                        block_text = getattr(block, 'text', None) or (isinstance(block, dict) and block.get("text"))

                        if block_type == "text" and block_text is not None:
                            text_content.append(block_text)
                        else:
                            self.logger.warning(f"Skipping non-text or empty text block in response content: type={block_type}")
                else:
                     # Content is empty, log the reason
                     self.logger.warning(f"Response object has no content blocks. Stop Reason: {stop_reason}, Usage: {usage}")

                final_text = "\n".join(text_content)
                self.logger.debug(f"Extracted text from non-streaming response (Length: {len(final_text)}): '{final_text[:100]}...' Stop Reason: {stop_reason}, Usage: {usage}")
                
                # Check stop reason - handle empty content with normal stop_reason
                if not final_text.strip() and stop_reason in ['end_turn', 'stop_sequence']:
                    self.logger.warning(f"Empty content extracted despite normal stop_reason: {stop_reason}. Returning specific message.")
                    # Return a more informative message instead of just empty string
                    info_message = f"[Model finished ({stop_reason}) but produced no text content. Input Tokens: {usage.input_tokens if usage else 'N/A'}, Output Tokens: {usage.output_tokens if usage else 'N/A'}]"
                    return info_message, []
                elif not final_text.strip():
                    # Handle empty content due to other stop reasons (like max_tokens)
                     self.logger.warning(f"Empty content extracted, likely due to stop_reason: {stop_reason}. Returning empty string.")
                     # Could return specific messages based on other stop_reasons if needed
                     # e.g., if stop_reason == 'max_tokens': return "[Response truncated due to token limit]", []

                # TODO: Add tool use extraction if Anthropic starts returning tool calls here
                tool_uses = [] 
                return final_text, tool_uses
            
            # Fallback for string response (likely from streaming completion or error handling)
            if isinstance(response, str):
                # Check if the string indicates an error or specific state from streaming
                if "[Model finished" in response and "produced no text content" in response:
                    # Pass through the informative message from streaming
                    self.logger.debug(f"Processing informative string response from streaming: '{response[:100]}...'")
                else:
                     self.logger.debug(f"Processing generic string response (Length: {len(response)}): '{response[:100]}...'")
                return response, []
            
            # Last resort - handle unexpected types
            self.logger.warning(f"Processing unexpected response type: {type(response)}. Converting to string.")
            return str(response), []
            
        except Exception as e:
            self.logger.error(f"Error processing Anthropic response: {str(e)}")
            self.logger.error(f"Processing error details: {traceback.format_exc()}")
            return f"Error processing response: {str(e)}", []
            
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format messages for Anthropic API, properly handling images"""
        formatted_messages = []
        
        # Second pass - handle regular messages
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Skip all system messages (handled separately)
            if role == "system":
                continue
            
            # Map roles for Anthropic
            if role == "assistant":
                role = "assistant"
            else:
                role = "user"
            
            # Handle different content formats
            formatted_content = []
            
            # Handle string content
            if isinstance(content, str):
                # Strip trailing whitespace for assistant messages to avoid API errors
                if role == "assistant":
                    content = content.rstrip()
                formatted_content.append({"type": "text", "text": content})
            
            # Handle list content (multimodal)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        # Handle image parts - with more flexible field detection
                        if part.get("type") in ["image_url", "image"]:
                            try:
                                # Extract image URL from various possible formats
                                image_url = None
                                image_path = None
                                
                                # Handle direct image_url format (most common in your codebase)
                                if "image_url" in part:
                                    # Handle both string and dict variants
                                    if isinstance(part["image_url"], dict) and "url" in part["image_url"]:
                                        image_url = part["image_url"]["url"]
                                    else:
                                        image_url = part["image_url"]
                                        
                                # Also check for direct path
                                elif "image_path" in part:
                                    image_path = part["image_path"]
                                # Check for direct url field
                                elif "url" in part:
                                    image_url = part["url"]
                                # Also check for source.url pattern
                                elif "source" in part and isinstance(part["source"], dict) and "url" in part["source"]:
                                    image_url = part["source"]["url"]
                                
                                # Process the image source appropriately
                                if image_url and image_url.startswith(('http://', 'https://')):
                                    # For web URLs, use URL source type
                                    formatted_content.append({
                                        "type": "image",
                                        "source": {
                                            "type": "url",
                                            "url": image_url
                                        }
                                    })
                                elif image_path and os.path.exists(image_path):
                                    # For local files, read and encode as base64
                                    from PIL import Image # type: ignore
                                    import io
                                    
                                    # Open and process the image
                                    with Image.open(image_path) as img:
                                        # Resize if needed
                                        max_size = (1024, 1024)
                                        img.thumbnail(max_size, Image.LANCZOS)
                                        
                                        # Convert to RGB if necessary
                                        if img.mode != "RGB":
                                            img = img.convert("RGB")
                                        
                                        # Determine media type based on file extension
                                        ext = os.path.splitext(image_path)[1].lower()
                                        media_type = {
                                            '.jpg': 'image/jpeg',
                                            '.jpeg': 'image/jpeg',
                                            '.png': 'image/png',
                                            '.gif': 'image/gif',
                                            '.webp': 'image/webp'
                                        }.get(ext, 'image/jpeg')
                                        
                                        # Encode to base64
                                        buffer = io.BytesIO()
                                        img.save(buffer, format=media_type.split('/')[1].upper())
                                        base64_data = base64.b64encode(buffer.getvalue()).decode('utf-8')
                                        
                                        # Format for Anthropic API using base64
                                        formatted_content.append({
                                            "type": "image",
                                            "source": {
                                                "type": "base64",
                                                "media_type": media_type,
                                                "data": base64_data
                                            }
                                        })
                                elif image_url:
                                    # For other URLs (like file:// or unsupported), try to load and convert to base64
                                    try:
                                        from PIL import Image # type: ignore
                                        import io
                                        # Import base64 again in this scope to avoid the variable shadowing issue
                                        import base64 as image_base64
                                        
                                        # Try to open as local file by removing file:// prefix if present
                                        local_path = image_url
                                        if image_url.startswith('file://'):
                                            local_path = image_url[7:]
                                        
                                        if os.path.exists(local_path):
                                            with Image.open(local_path) as img:
                                                # Same processing as above
                                                max_size = (1024, 1024)
                                                img.thumbnail(max_size, Image.LANCZOS)
                                                if img.mode != "RGB":
                                                    img = img.convert("RGB")
                                                
                                                # Determine media type
                                                ext = os.path.splitext(local_path)[1].lower()
                                                media_type = {
                                                    '.jpg': 'image/jpeg',
                                                    '.jpeg': 'image/jpeg',
                                                    '.png': 'image/png',
                                                    '.gif': 'image/gif',
                                                    '.webp': 'image/webp'
                                                }.get(ext, 'image/jpeg')
                                                
                                                # Encode to base64 using the renamed import
                                                buffer = io.BytesIO()
                                                img.save(buffer, format=media_type.split('/')[1].upper())
                                                base64_data = image_base64.b64encode(buffer.getvalue()).decode('utf-8')
                                                
                                                # Format for Anthropic API using base64
                                                formatted_content.append({
                                                    "type": "image",
                                                    "source": {
                                                        "type": "base64",
                                                        "media_type": media_type,
                                                        "data": base64_data
                                                    }
                                                })
                                        else:
                                            self.logger.error(f"Image not found at path: {local_path}")
                                            formatted_content.append({
                                                "type": "text",
                                                "text": f"[Failed to process image: File not found]"
                                            })
                                    except Exception as e:
                                        self.logger.error(f"Error processing image URL {image_url}: {str(e)}")
                                        formatted_content.append({
                                            "type": "text",
                                            "text": f"[Failed to process image: {str(e)}]"
                                        })
                                else:
                                    # No valid image source found
                                    self.logger.error(f"Invalid image format in message: {part}")
                                    formatted_content.append({
                                        "type": "text",
                                        "text": "[Failed to process image: Invalid format]"
                                    })
                            except Exception as e:
                                self.logger.error(f"Error formatting image: {str(e)}")
                                formatted_content.append({
                                    "type": "text",
                                    "text": f"[Failed to process image: {str(e)}]"
                                })
                        elif part.get("type") == "text":
                            # Text content in a list
                            text = part.get("text", "")
                            # Strip trailing whitespace for assistant messages
                            if role == "assistant":
                                text = text.rstrip()
                            formatted_content.append({
                                "type": "text", 
                                "text": text
                            })
                        else:
                            # Unknown content type
                            formatted_content.append(part)
                    else:
                        # Plain strings in a list
                        # Strip trailing whitespace if needed
                        content_str = str(part)
                        if role == "assistant":
                            content_str = content_str.rstrip()
                        formatted_content.append({"type": "text", "text": content_str})
            else:
                # Fallback for any other content type
                content_str = str(content)
                if role == "assistant":
                    content_str = content_str.rstrip()
                formatted_content.append({"type": "text", "text": content_str})
            
            # Create the formatted message with proper content array
            formatted_messages.append({"role": role, "content": formatted_content})
        
        return formatted_messages
    
    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """Count tokens using Anthropic's dedicated token counting endpoint"""
        try:
            # Convert to simplest possible format for count_tokens endpoint
            simple_messages = []
            
            # Handle different content types
            if isinstance(content, str):
                # Simple string
                simple_messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": content}]
                })
            elif isinstance(content, list):
                # Convert list to simple text-only content
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        # Add just the text content without other fields
                        text_parts.append({"type": "text", "text": item.get("text", "")})
                    elif isinstance(item, dict) and item.get("type") in ["image", "image_url"]:
                        # Replace images with text placeholder 
                        text_parts.append({"type": "text", "text": "[Image: ~1300 tokens]"})
                    else:
                        # Convert anything else to simple text
                        text_parts.append({"type": "text", "text": str(item)})
                
                simple_messages.append({
                    "role": "user", 
                    "content": text_parts
                })
            elif isinstance(content, dict):
                if "role" in content and "content" in content:
                    # It's a message, extract role and convert content to simple format
                    role = "assistant" if content["role"] == "assistant" else "user"
                    
                    if isinstance(content["content"], list):
                        # Process list content
                        text_parts = []
                        for item in content["content"]:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text_parts.append({"type": "text", "text": item.get("text", "")})
                            elif isinstance(item, dict) and item.get("type") in ["image", "image_url"]:
                                text_parts.append({"type": "text", "text": "[Image: ~1300 tokens]"})
                            else:
                                text_parts.append({"type": "text", "text": str(item)})
                            
                        simple_messages.append({
                            "role": role,
                            "content": text_parts
                        })
                    else:
                        # Convert to simple text
                        simple_messages.append({
                            "role": role,
                            "content": [{"type": "text", "text": str(content["content"])}]
                        })
                else:
                    # Treat as generic content
                    simple_messages.append({
                        "role": "user",
                        "content": [{"type": "text", "text": str(content)}]
                    })
            else:
                # Fallback for any other type
                simple_messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": str(content)}]
                })
            
            # Call token counting API with simplified messages
            logger.debug(f"Counting tokens with simplified format: {simple_messages}")
            response = self.sync_client.messages.count_tokens(
                model=self.model_config.model,
                messages=simple_messages
            )
            
            logger.debug(f"Token count from Anthropic API: {response.input_tokens}")
            return response.input_tokens
            
        except Exception as e:
            logger.error(f"Error counting tokens via Anthropic API: {str(e)}")
            # Fall back to approximate counting
            token_count = self._approximate_token_count(content)
            logger.debug(f"Using approximate token count: {token_count}")
            return token_count
    
    def _approximate_token_count(self, content) -> int:
        """Fallback method for token counting when API fails"""
        try:
            # Try tiktoken first
            import tiktoken # type: ignore
            encoder = tiktoken.get_encoding("cl100k_base")
            
            if isinstance(content, str):
                return len(encoder.encode(content))
            elif isinstance(content, list):
                # Handle content array with images
                text_content = ""
                image_count = 0
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_content += item.get("text", "")
                        elif item.get("type") in ["image", "image_url"]:
                            image_count += 1
                    else:
                        text_content += str(item)
                
                # Count text tokens + estimate for images
                text_tokens = len(encoder.encode(text_content))
                image_tokens = image_count * 1300  # Claude's approx for images
                return text_tokens + image_tokens
            else:
                return len(encoder.encode(str(content)))
            
        except Exception:
            # Ultimate fallback - character-based estimation
            if isinstance(content, str):
                return len(content) // 4 + 1
            elif isinstance(content, list):
                # Estimate with images
                char_count = 0
                image_count = 0
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            char_count += len(item.get("text", ""))
                        elif item.get("type") in ["image", "image_url"]:
                            image_count += 1
                    else:
                        char_count += len(str(item))
                
                return (char_count // 4 + 1) + (image_count * 1300)
            else:
                return len(str(content)) // 4 + 1
    
    def supports_system_messages(self) -> bool:
        """Whether this provider supports system messages"""
        return True
    
    def supports_vision(self) -> bool:
        """Whether this provider supports vision/images"""
        return "claude-3" in self.model_config.model

    def _safe_log_content(self, content):
        """Create a safe version of content for logging, removing base64 data"""
        if isinstance(content, list):
            return [self._safe_log_content(item) for item in content]
        elif isinstance(content, dict):
            result = {}
            for k, v in content.items():
                if k == "data" and isinstance(v, str) and len(v) > 100:
                    result[k] = f"[BASE64 DATA REDACTED: {len(v)} bytes]"
                elif isinstance(v, dict) or isinstance(v, list):
                    result[k] = self._safe_log_content(v)
                else:
                    result[k] = v
            return result
        return content

    def _ensure_no_trailing_whitespace(self, request_params: Dict[str, Any]) -> None:
        """Ensure no trailing whitespace in any text content to avoid API errors"""
        # Check system prompt
        if "system" in request_params and isinstance(request_params["system"], str):
            request_params["system"] = request_params["system"].rstrip()
        
        # Check all messages
        if "messages" in request_params and isinstance(request_params["messages"], list):
            for msg in request_params["messages"]:
                if not isinstance(msg, dict):
                    continue
                    
                # Check content list
                if "content" in msg and isinstance(msg["content"], list):
                    for item in msg["content"]:
                        if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                            # Strip trailing whitespace from all text content
                            item["text"] = item["text"].rstrip()

Adapter = AnthropicAdapter  # Alias for consistent imports