import os
import logging
import mimetypes
import base64
from typing import Any, Dict, List, Optional, AsyncIterator, Callable
from anthropic import AsyncAnthropic, AsyncMessageStream
from anthropic.types import Message, MessageStreamEvent # type: ignore
from penguin.llm.model_config import ModelConfig
from ..base_provider import ProviderAdapter

class NativeAnthropicAdapter(ProviderAdapter):
    def __init__(self, model_config: ModelConfig):
        super().__init__(model_config)
        self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.logger = logging.getLogger(__name__)
        self.stream_callback = None

    @property
    def provider(self) -> str:
        return "anthropic-native"

    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> Any:
        """Handle native Anthropic API calls with streaming support"""
        try:
            system_prompt = next(
                (msg["content"] for msg in messages if msg["role"] == "system"), ""
            )
            conversation = self._format_conversation(messages)

            response = await self.client.messages.create(
                model=self.model_config.model,
                system=system_prompt,
                messages=conversation,
                max_tokens=max_tokens or self.model_config.max_tokens,
                temperature=temperature or self.model_config.temperature,
                stream=stream_callback is not None
            )

            if isinstance(response, AsyncMessageStream):
                return await self._handle_streaming_response(response, stream_callback)
            return response

        except Exception as e:
            self.logger.error(f"Anthropic API error: {str(e)}")
            raise

    def _format_conversation(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted = []
        for msg in messages:
            if msg["role"] not in ["user", "assistant"]:
                continue
                
            content = []
            for part in msg.get("content", []):
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        image_data = self._process_image_url(part["image_url"]["url"])
                        content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_data["media_type"],
                                "data": image_data["data"]
                            }
                        })
                    elif part.get("type") == "text":
                        content.append({"type": "text", "text": part["text"]})
                else:
                    content.append({"type": "text", "text": str(part)})
            
            formatted.append({"role": msg["role"], "content": content})
        return formatted

    def _process_image_url(self, url: str) -> Dict[str, str]:
        if url.startswith("data:image/"):
            media_type, data = url.split(",", 1)
            media_type = media_type.split(":")[1].split(";")[0]
            return {"media_type": media_type, "data": data}
        
        # Handle local file paths
        if os.path.exists(url):
            mime_type, _ = mimetypes.guess_type(url)
            if not mime_type or not mime_type.startswith("image/"):
                raise ValueError(f"Unsupported image format: {url}")
            
            with open(url, "rb") as image_file:
                return {
                    "media_type": mime_type,
                    "data": base64.b64encode(image_file.read()).decode("utf-8")
                }
        
        raise ValueError(f"Unsupported image URL format: {url}")

    async def _handle_streaming_response(
        self,
        stream: AsyncMessageStream,
        stream_callback: Optional[Callable[[str], None]]
    ) -> Message:
        content = []
        async for event in stream:
            if event.type == "content_block_delta":
                delta = event.delta
                if stream_callback and delta.text:
                    stream_callback(delta.text)
                content.append(delta.text)
            elif event.type == "message_stop":
                return Message(
                    id=event.message.id,
                    content=[{"type": "text", "text": "".join(content)}],
                    model=event.message.model,
                    role="assistant",
                    usage=event.message.usage,
                    stop_reason=event.message.stop_reason,
                    stop_sequence=event.message.stop_sequence
                )
        return Message(
            id="",
            content=[{"type": "text", "text": "".join(content)}],
            model=self.model_config.model,
            role="assistant",
            usage=None,
            stop_reason=None,
            stop_sequence=None
        )

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """Process both streaming and non-streaming responses"""
        if isinstance(response, Message):
            return self._process_message(response)
        return "", []

    def _process_message(self, response: Message) -> tuple[str, List[Any]]:
        if not response.content:
            return "", []
        return "".join([block.text for block in response.content if block.type == "text"]), []

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert to Anthropic message format"""
        return [
            {
                "role": msg["role"], 
                "content": str(msg.get("content", ""))
            } 
            for msg in messages
            if msg["role"] in ["user", "assistant", "system"]
        ]

    def supports_system_messages(self) -> bool:
        return True