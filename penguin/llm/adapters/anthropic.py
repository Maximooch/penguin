import asyncio
import base64
import logging
import os
from typing import Any, Dict, List, Optional, Tuple, AsyncIterator, Callable

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
            logger.debug(f"Sending request to Anthropic: {request_params}")
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
            logger.debug(f"Sending request to Anthropic: {request_params}")
            
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
            
            # Process each chunk as it comes in
            async for chunk in stream:
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
        """Format messages for Anthropic API"""
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
            
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        # Handle image parts
                        if part.get("type") == "image_url":
                            try:
                                image_url = part.get("image_url", {}).get("url", "")
                                formatted_content.append({
                                    "type": "image",
                                    "source": {
                                        "type": "base64" if "data:image" in image_url else "url",
                                        "media_type": "image/jpeg",
                                        "data": image_url.split("base64,")[1] if "data:image" in image_url else image_url
                                    }
                                })
                            except Exception as e:
                                logger.error(f"Error formatting image: {str(e)}")
                                formatted_content.append({
                                    "type": "text",
                                    "text": f"[Failed to process image: {str(e)}]"
                                })
                        else:
                            # Text or other content types
                            formatted_content.append(part)
                    else:
                        # Plain strings in a list
                        formatted_content.append({"type": "text", "text": str(part)})
            else:
                # Simple string content
                formatted_content.append({"type": "text", "text": str(content)})
            
            formatted_messages.append({"role": role, "content": formatted_content})
        
        return formatted_messages
    
    def count_tokens(self, text: str) -> int:
        """Count tokens using Anthropic's tokenizer"""
        try:
            return self.sync_client.count_tokens(text)
        except Exception as e:
            logger.error(f"Error counting tokens: {str(e)}")
            # Fallback to approximate counting
            return len(text) // 4 
    
    def supports_system_messages(self) -> bool:
        """Whether this provider supports system messages"""
        return True
    
    def supports_vision(self) -> bool:
        """Whether this provider supports vision/images"""
        return "claude-3" in self.model_config.model