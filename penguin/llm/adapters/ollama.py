import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import ollama  # type: ignore

from ..contracts import FinishReason
from ..model_config import ModelConfig
from ..provider_transform import normalize_finish_reason
from ...utils.callbacks import adapt_stream_callback
from ...utils.diagnostics import diagnostics
from .base import BaseAdapter

logger = logging.getLogger(__name__)


class OllamaAdapter(BaseAdapter):
    """Native adapter using the official `ollama` Python library."""

    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        base_url = model_config.api_base or "http://localhost:11434"
        self.client = ollama.AsyncClient(host=base_url)
        self._last_finish_reason = FinishReason.UNKNOWN

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

    def get_last_finish_reason(self) -> FinishReason:
        """Return why the last reply ended; UNKNOWN if the stream never finished."""
        return self._last_finish_reason

    def _record_finish(self, chunk: Any) -> None:
        get = getattr(chunk, "get", None)
        if callable(get) and get("done"):
            self._last_finish_reason = normalize_finish_reason(get("done_reason"))

    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> Any:
        legacy_max_tokens = kwargs.pop("max_tokens", None)
        if max_output_tokens is None and legacy_max_tokens is not None:
            max_output_tokens = legacy_max_tokens

        options: Dict[str, Any] = {}
        if temperature is not None:
            options["temperature"] = temperature
        if max_output_tokens is not None:
            options["num_predict"] = max_output_tokens

        params = {
            "model": self.model_config.model,
            "messages": self.format_messages(messages),
            "stream": stream,
            "options": options or None,
        }

        self._last_finish_reason = FinishReason.UNKNOWN
        if stream:
            response = await self.client.chat(**params)
            last_chunk = None
            async for chunk in response:
                last_chunk = chunk
                text = chunk.get("message", {}).get("content", "")
                # Always call the callback, even for empty chunks, as they might contain formatting
                if stream_callback:
                    await stream_callback(text)
                self._record_finish(chunk)
            return last_chunk
        reply = await self.client.chat(**params)
        self._record_finish(reply)
        return reply

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        if stream:
            collected: List[str] = []
            # APIClient passes a (chunk, message_type) callback; direct callers
            # may pass a one-argument one.
            on_chunk = adapt_stream_callback(stream_callback) if stream_callback else None

            async def _cb(chunk: str):
                collected.append(chunk)
                if on_chunk:
                    await on_chunk(chunk, "assistant")

            await self.create_completion(
                messages,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                stream=True,
                stream_callback=_cb,
                **kwargs,
            )
            return "".join(collected)
        else:
            resp = await self.create_completion(
                messages,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                stream=False,
                **kwargs,
            )
            text, _ = self.process_response(resp)
            return text
