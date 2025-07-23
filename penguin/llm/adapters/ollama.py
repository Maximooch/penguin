import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import ollama  # type: ignore

from ..model_config import ModelConfig
from ...utils.diagnostics import diagnostics
from .base import BaseAdapter

logger = logging.getLogger(__name__)


class OllamaAdapter(BaseAdapter):
    """Native adapter using the official `ollama` Python library."""

    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        base_url = model_config.api_base or "http://localhost:11434"
        self.client = ollama.AsyncClient(host=base_url)

    @property
    def provider(self) -> str:
        return "ollama"

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Ollama accepts OpenAI style chat messages
        return messages

    def process_response(self, response: Any) -> Tuple[str, List[Any]]:
        if isinstance(response, dict) and "message" in response:
            return str(response["message"].get("content", "")), []
        if isinstance(response, str):
            return response, []
        return str(response), []

    def count_tokens(self, text: str) -> int:
        return diagnostics.count_tokens(text)

    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> Any:
        options: Dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_tokens is not None:
            options["num_predict"] = max_tokens

        params = {
            "model": self.model_config.model,
            "messages": self.format_messages(messages),
            "stream": stream,
            "options": options or None,
        }

        if stream:
            response = await self.client.chat(**params)
            async for chunk in response:
                text = chunk.get("message", {}).get("content", "")
                # Debug: log the raw chunk to see formatting
                # logger.debug(f"Ollama chunk received: {repr(text)} (length: {len(text) if text else 0})")
                # Always call the callback, even for empty chunks, as they might contain formatting
                if stream_callback:
                    await stream_callback(text)
            return chunk
        else:
            return await self.client.chat(**params)

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        if stream:
            collected: List[str] = []

            async def _cb(chunk: str):
                collected.append(chunk)
                if stream_callback:
                    await stream_callback(chunk)

            await self.create_completion(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stream_callback=_cb,
            )
            return "".join(collected)
        else:
            resp = await self.create_completion(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=False,
            )
            text, _ = self.process_response(resp)
            return text
