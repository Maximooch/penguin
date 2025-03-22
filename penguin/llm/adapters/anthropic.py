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
                "max_tokens": max_tokens or self.model_config.max_tokens or 4096,
                "temperature": temperature or self.model_config.temperature or 0.7,
            }
            
            # Add system prompt if provided
            if system_prompt:
                request_params["system"] = system_prompt
            
            # Make the API call
            safe_params = self._safe_log_content(request_params.copy())
            logger.debug(f"Sending request to Anthropic: {safe_params}")
            response = await self.async_client.messages.create(**request_params)
            
            return response
        
        except Exception as e:
            logger.error(f"Error in Anthropic API call: {str(e)}")
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
            
            # Make the API call
            safe_params = self._safe_log_content(request_params.copy())
            logger.debug(f"Sending request to Anthropic: {safe_params}")
            
            if stream:
                return await self._handle_streaming(request_params, stream_callback)
            else:
                response = await self.async_client.messages.create(**request_params)
                return response
                
        except Exception as e:
            logger.error(f"Error in Anthropic API call: {str(e)}")
            raise
    
    async def _handle_streaming(
        self, 
        params: Dict[str, Any], 
        callback: Optional[Callable[[str], None]] = None
    ) -> str:
        """Handle streaming response from Anthropic API"""
        accumulated_response = []
        
        try:
            # Create the streaming response
            stream = await self.async_client.messages.create(**params)
            
            # Track content reception
            received_content = False
            last_chunk_time = time.time()
            
            # Process each chunk as it comes in
            async for chunk in stream:
                last_chunk_time = time.time()
                
                # Extract text content based on chunk type
                content = None
                
                try:
                    # Handle different event types
                    if hasattr(chunk, 'type'):
                        self.logger.debug(f"Received chunk type: {chunk.type}")
                        
                        if chunk.type == 'content_block_delta' and hasattr(chunk, 'delta'):
                            if chunk.delta.type == 'text_delta' and hasattr(chunk.delta, 'text'):
                                content = chunk.delta.text
                        
                        elif chunk.type == 'content_block_start' and hasattr(chunk, 'content_block'):
                            if chunk.content_block.type == 'text' and hasattr(chunk.content_block, 'text'):
                                content = chunk.content_block.text
                
                    # Process extracted content
                    if content:
                        received_content = True
                        self.logger.debug(f"Extracted content: {content}")
                        # Call the callback with the content
                        if callback:
                            callback(content)
                        # Add to accumulated response
                        accumulated_response.append(content)
                        
                except Exception as e:
                    error_msg = f"Error processing chunk: {str(e)}"
                    self.logger.error(error_msg)
            
            # Join all chunks to get the complete response
            complete_response = ''.join(accumulated_response)
            
            # Check for suspiciously short responses after stream completes
            if len(complete_response.strip()) <= 1:
                self.logger.warning(f"Suspiciously short response received: '{complete_response}'")
                # Only replace with error message if it's just punctuation or empty
                if complete_response.strip() in ['', '.', '?', '!', ',']:
                    return "I encountered an issue while generating a response. The connection may have been interrupted. Please try again." + complete_response + traceback.format_exc()
            
            return complete_response
            
        except Exception as e:
            error_msg = f"Error during Anthropic streaming: {str(e)}"
            self.logger.error(error_msg)
            if callback:
                callback(f"\n[Streaming Error: {str(e)}]")
            return ''.join(accumulated_response) or error_msg
    
    def process_response(self, response: Any) -> Tuple[str, List[Any]]:
        """Process Anthropic API response into standardized format"""
        try:
            logger.debug(f"Processing Anthropic response of type: {type(response)}")
            
            # Handle AsyncAnthropic Message object
            if hasattr(response, 'content'):
                # Extract text from content blocks
                text_content = []
                for block in response.content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_content.append(block.get("text", ""))
                    elif hasattr(block, "text") and hasattr(block, "type") and block.type == "text":
                        text_content.append(block.text)
                
                return "\n".join(text_content), []
            
            # Fallback for string or other response types
            if isinstance(response, str):
                return response, []
            
            # Last resort - convert to string
            return str(response), []
            
        except Exception as e:
            logger.error(f"Error processing Anthropic response: {str(e)}")
            return f"Error processing response: {str(e)}", []
    
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format messages for Anthropic API, properly handling images"""
        formatted_messages = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Skip system messages (handled separately in create_message)
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
                            formatted_content.append({
                                "type": "text", 
                                "text": part.get("text", "")
                            })
                        else:
                            # Unknown content type
                            formatted_content.append(part)
                    else:
                        # Plain strings in a list
                        formatted_content.append({"type": "text", "text": str(part)})
            else:
                # Fallback for any other content type
                formatted_content.append({"type": "text", "text": str(content)})
            
            # Create the formatted message with proper content array
            formatted_messages.append({"role": role, "content": formatted_content})
        
        return formatted_messages
    
    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """Count tokens using Anthropic's dedicated token counting endpoint"""
        try:
            # Handle simple string content directly
            if isinstance(content, str):
                return self.sync_client.count_tokens(content)
            
            # For complex content (including images), use the messages/count_tokens endpoint
            if isinstance(content, list) or isinstance(content, dict):
                # Format the content as a proper message
                if isinstance(content, list):
                    # If it's a list of message parts, wrap it as a user message
                    formatted_content = {"role": "user", "content": content}
                else:
                    # If it's already a dict, use as is
                    formatted_content = content
                    
                # Format as a complete messages request
                messages = [formatted_content]
                
                # Call the count_tokens endpoint
                response = self.sync_client.messages.count_tokens(messages=messages)
                
                # Return the token count from the response
                return response.input_tokens
            
            # Fallback for other content types
            return self.sync_client.count_tokens(str(content))
            
        except Exception as e:
            logger.error(f"Error counting tokens via Anthropic API: {str(e)}")
            # Fall back to approximate counting in case of API errors
            if isinstance(content, list) and any(isinstance(part, dict) and part.get("type") in ["image", "image_url"] 
                                                for part in content if isinstance(part, dict)):
                # Conservative estimate for content with images
                text_content = ' '.join([part.get("text", "") for part in content 
                                        if isinstance(part, dict) and part.get("type") == "text"])
                # Base text tokens plus 1500 per image (conservative estimate)
                image_count = sum(1 for part in content if isinstance(part, dict) 
                                 and part.get("type") in ["image", "image_url"])
                return len(text_content) // 4 + (image_count * 1500)
            else:
                # Basic fallback
                return len(str(content)) // 4
    
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