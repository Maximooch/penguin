import asyncio
import json
import base64
import io
import logging
import mimetypes
import os
from typing import Any, Dict, List, Optional, Tuple, Callable, Union

import tiktoken  # type: ignore
from openai import AsyncOpenAI  # type: ignore

from .base import BaseAdapter
from ..model_config import ModelConfig


logger = logging.getLogger(__name__)


class OpenAIAdapter(BaseAdapter):
    """Native OpenAI adapter using the Responses API.

    This adapter calls OpenAI's Responses API directly for both streaming and
    non-streaming requests. It supports reasoning tokens (o-series) via the
    unified ``reasoning`` parameter and performs basic multimodal handling by
    encoding local images to data URIs.

    The adapter adheres to the BaseAdapter interface expected by APIClient when
    ``client_preference == 'native'`` and ``provider == 'openai'``.
    """

    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        api_key = model_config.api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Missing OpenAI API key. Set OPENAI_API_KEY or model_config.api_key.")

        # Respect custom base URL if provided (e.g., Azure/OpenAI-compatible gateways)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=model_config.api_base or None,
        )

    @property
    def provider(self) -> str:
        return "openai"

    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> Any:
        """Create a completion using the Responses API.

        Args:
            messages: Conversation in OpenAI-style message format.
            max_tokens: Max output tokens (model dependent).
            temperature: Sampling temperature.
            stream: Whether to stream the response.
            stream_callback: Callback invoked with chunks during streaming. If
                provided by callers in Penguin it may accept (chunk) or
                (chunk, message_type). We will only pass a single positional
                argument here and let APIClient wrap signatures as needed.
        """
        processed_messages = await self._process_messages_for_vision(messages)

        reasoning_config = self.model_config.get_reasoning_config()
        temp_val = temperature if temperature is not None else self.model_config.temperature

        # Pull optional openai-specific kwargs
        instructions: Optional[str] = kwargs.get("instructions")
        previous_response_id: Optional[str] = kwargs.get("previous_response_id")
        conversation_id: Optional[str] = kwargs.get("conversation")
        response_format: Optional[Dict[str, Any]] = kwargs.get("response_format")
        tools: Optional[List[Dict[str, Any]]] = kwargs.get("tools")
        tool_choice: Optional[Union[str, Dict[str, Any]]] = kwargs.get("tool_choice")
        stream_options: Optional[Dict[str, Any]] = kwargs.get("stream_options")

        # Build input either as compact string or as structured content parts when images present
        input_parts = self._build_input_parts(processed_messages)
        if input_parts is not None:
            request_params: Dict[str, Any] = {
                "model": self.model_config.model,
                "input": input_parts,
                **({"max_output_tokens": max_tokens} if max_tokens else {}),
                **({"reasoning": reasoning_config} if reasoning_config else {}),
            }
        else:
            input_text = self._build_transcript_input(processed_messages)
            request_params = {
                "model": self.model_config.model,
                "input": input_text,
                **({"max_output_tokens": max_tokens} if max_tokens else {}),
                **({"reasoning": reasoning_config} if reasoning_config else {}),
            }

        # Optional top-level params
        if instructions:
            request_params["instructions"] = instructions
        if previous_response_id:
            request_params["previous_response_id"] = previous_response_id
        if conversation_id:
            request_params["conversation"] = conversation_id
        if response_format:
            request_params["response_format"] = response_format
        if tools:
            request_params["tools"] = tools
        if tool_choice:
            request_params["tool_choice"] = tool_choice
        # Per OpenAI Responses API, o-/gpt-5 style reasoning models do not accept temperature
        try:
            uses_effort_style = bool(self.model_config._uses_effort_style())
        except Exception:
            uses_effort_style = False
        if not uses_effort_style:
            request_params["temperature"] = temp_val

        if stream:
            # Default include_usage unless explicitly disabled
            so = dict(stream_options or {})
            if "include_usage" not in so:
                so["include_usage"] = True
            if so:
                request_params["stream_options"] = so
            try:
                return await self._stream_with_sdk(request_params, stream_callback)
            except Exception as e:
                logger.warning(f"SDK streaming failed, falling back to HTTP SSE: {e}")
                return await self._stream_with_http(request_params, stream_callback)

        # Non-streaming
        resp = await self.client.responses.create(**request_params)

        output_text = getattr(resp, "output_text", None)
        if isinstance(output_text, str):
            return output_text
        return self._extract_text_from_response_object(resp) or ""

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """Unified interface expected by APIClient/BaseAdapter."""
        if stream:
            accumulated = await self.create_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stream_callback=stream_callback,
                **kwargs,
            )
            return accumulated or ""
        # Non-streaming path
        resp = await self.create_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
            stream_callback=None,
            **kwargs,
        )
        # create_completion returns text for non-streaming
        if isinstance(resp, str):
            return resp
        return str(resp)

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Pass-through for OpenAI chat format with minimal normalization.

        The Responses API accepts ``messages`` similar to Chat Completions.
        This method keeps strings intact and ensures multimodal list content
        items conform to expected shapes.
        """
        normalized: List[Dict[str, Any]] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                fixed_parts: List[Dict[str, Any]] = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "image_url" and "image_url" in part:
                            # Keep as-is; _process_messages_for_vision will encode local files
                            fixed_parts.append(part)
                        elif part.get("type") == "text":
                            fixed_parts.append({"type": "text", "text": str(part.get("text", ""))})
                        else:
                            fixed_parts.append(part)
                    else:
                        fixed_parts.append({"type": "text", "text": str(part)})
                normalized.append({"role": role, "content": fixed_parts})
            else:
                normalized.append({"role": role, "content": str(content)})
        return normalized

    def process_response(self, response: Any) -> Tuple[str, List[Any]]:
        """Extract assistant text and return with empty tool list for now."""
        if isinstance(response, str):
            return response, []
        text = self._extract_text_from_response_object(response)
        return (text or ""), []

    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """Count tokens using tiktoken with a default GPT-4o encoding.

        Falls back to ``cl100k_base`` and rough estimates when needed.
        """
        if not self.model_config.enable_token_counting:
            return 0
        model_for_counting = "gpt-4o"
        try:
            encoding = tiktoken.encoding_for_model(model_for_counting)
        except Exception:
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                return len(str(content)) // 4

        if isinstance(content, str):
            return len(encoding.encode(content))
        if isinstance(content, dict):
            return len(encoding.encode(str(content)))
        if isinstance(content, list):
            # Approximate chat tokenization
            tokens = 3
            for m in content:
                tokens += 3
                if isinstance(m, dict):
                    for k, v in m.items():
                        if k == "content" and isinstance(v, list):
                            for item in v:
                                if isinstance(item, dict) and item.get("type") == "text":
                                    tokens += len(encoding.encode(item.get("text", "")))
                                elif isinstance(item, dict) and item.get("type") == "image_url":
                                    # Skip exact accounting for images
                                    tokens += 1300
                        else:
                            tokens += len(encoding.encode(str(v)))
                else:
                    tokens += len(encoding.encode(str(m)))
            tokens += 3
            return tokens
        return len(encoding.encode(str(content)))

    def supports_system_messages(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return True

    async def _process_messages_for_vision(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Encode local image paths in content lists into data URIs."""
        processed: List[Dict[str, Any]] = []
        for message in self.format_messages(messages):
            content = message.get("content")
            if isinstance(content, list):
                new_content: List[Dict[str, Any]] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        url_obj = item.get("image_url")
                        path: Optional[str] = None
                        if isinstance(url_obj, dict) and "image_path" in url_obj:
                            path = url_obj.get("image_path")
                        elif isinstance(url_obj, dict) and "url" in url_obj and str(url_obj["url"]).startswith("file://"):
                            path = str(url_obj["url"])[7:]
                        # Back-compat: sometimes we get {type:"image_url", image_path:"..."}
                        if not path and "image_path" in item:
                            path = item.get("image_path")
                        if path and os.path.exists(path):
                            data_uri = await self._encode_image(path)
                            if data_uri:
                                new_content.append({"type": "image_url", "image_url": {"url": data_uri}})
                                continue
                    new_content.append(item)
                processed.append({**message, "content": new_content})
            else:
                processed.append(message)
        return processed

    async def _encode_image(self, image_path: str) -> Optional[str]:
        """Encode an image file to a base64 data URI suitable for OpenAI."""
        try:
            from PIL import Image as PILImage  # type: ignore
            with PILImage.open(image_path) as img:
                max_size = (1024, 1024)
                img.thumbnail(max_size, PILImage.LANCZOS)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG")
                image_bytes = buffer.getvalue()
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            mime, _ = mimetypes.guess_type(image_path)
            if not mime or not mime.startswith("image"):
                mime = "image/jpeg"
            return f"data:{mime};base64,{b64}"
        except Exception as e:
            logger.error(f"Failed to encode image '{image_path}': {e}")
            return None

    async def _stream_with_sdk(
        self,
        request_params: Dict[str, Any],
        stream_callback: Optional[Callable[[str], None]],
    ) -> str:
        """Stream using the official OpenAI SDK responses.stream API."""
        accumulated_content: List[str] = []
        try:
            # Async streaming context
            async with self.client.responses.stream(**request_params) as stream:  # type: ignore[attr-defined]
                async for event in stream:
                    etype = getattr(event, "type", None)
                    if etype == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            accumulated_content.append(delta)
                            if stream_callback:
                                await self._safe_invoke_callback(stream_callback, delta, "assistant")
                    elif etype in ("response.thinking.delta", "response.reasoning.delta"):
                        delta = getattr(event, "delta", "")
                        if delta and stream_callback:
                            await self._safe_invoke_callback(stream_callback, delta, "reasoning")
                final = await stream.get_final_response()
                # Prefer SDK's convenience property if present
                final_text = getattr(final, "output_text", None)
                if isinstance(final_text, str) and final_text:
                    return final_text
        except AttributeError:
            # Older SDK without responses.stream async support
            raise
        except Exception:
            raise
        # Fallback to accumulated content
        return "".join(accumulated_content)

    async def _stream_with_http(
        self,
        request_params: Dict[str, Any],
        stream_callback: Optional[Callable[[str], None]],
    ) -> str:
        """HTTP SSE streaming fallback for the Responses API."""
        import httpx  # type: ignore

        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json",
        }
        url = (self.client.base_url or "https://api.openai.com/v1").rstrip("/") + "/responses"
        payload = dict(request_params)
        payload["stream"] = True

        accumulated_content: List[str] = []
        reasoning_phase = False

        async with httpx.AsyncClient(timeout=60.0) as http:
            async with http.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    text = (await resp.aread()).decode()
                    logger.error(f"Responses SSE failed {resp.status_code}: {text}")
                    return ""
                async for line in resp.aiter_lines():
                    if not line or not line.strip():
                        continue
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        etype = data.get("type")
                        if etype == "response.output_text.delta":
                            delta = data.get("delta", "")
                            if delta:
                                accumulated_content.append(delta)
                                if stream_callback:
                                    await self._safe_invoke_callback(stream_callback, delta, "assistant")
                        elif etype in ("response.thinking.delta", "response.reasoning.delta"):
                            delta = data.get("delta", "")
                            if delta and stream_callback:
                                await self._safe_invoke_callback(stream_callback, delta, "reasoning")
                    except Exception:
                        # Skip malformed lines
                        continue
        return "".join(accumulated_content)

    async def _safe_invoke_callback(self, cb: Callable[[str], None], chunk: str, message_type: str) -> None:
        """Invoke provided callback safely with support for legacy signatures."""
        try:
            import inspect
            if asyncio.iscoroutinefunction(cb):
                params = list(inspect.signature(cb).parameters.keys())
                if len(params) >= 2:
                    await cb(chunk, message_type)
                else:
                    await cb(chunk)
            else:
                loop = asyncio.get_event_loop()
                params = []
                try:
                    import inspect as _insp
                    params = list(_insp.signature(cb).parameters.keys())
                except Exception:
                    params = []
                if len(params) >= 2:
                    await loop.run_in_executor(None, cb, chunk, message_type)
                else:
                    await loop.run_in_executor(None, cb, chunk)
        except Exception as e:
            logger.error(f"Error in stream callback: {e}")

    def _extract_text_from_response_object(self, resp: Any) -> str:
        """Best-effort extraction of text from a Responses API object/dict."""
        try:
            text = getattr(resp, "output_text", None)
            if isinstance(text, str):
                return text
        except Exception:
            pass
        try:
            # Handle raw dict JSON shape
            if isinstance(resp, dict):
                if "output_text" in resp and isinstance(resp["output_text"], str):
                    return resp["output_text"]
                # Attempt to drill into output/message/content
                out = resp.get("output") or resp.get("choices")
                if isinstance(out, list) and out:
                    first = out[0]
                    # message.content -> list of parts with {type:"output_text","text":...}
                    content = None
                    if isinstance(first, dict):
                        content = first.get("message", {}).get("content") or first.get("content")
                    if isinstance(content, list):
                        texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in ("output_text", "text")]
                        if texts:
                            return "".join(texts)
        except Exception:
            pass
        return ""

    def _build_transcript_input(self, messages: List[Dict[str, Any]]) -> str:
        """Flatten chat messages to a single textual transcript for input."""
        parts: List[str] = []
        for m in self.format_messages(messages):
            role = m.get("role", "user")
            content = m.get("content", "")
            text = ""
            if isinstance(content, list):
                texts: List[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(str(item.get("text", "")))
                    elif isinstance(item, dict) and item.get("type") == "image_url":
                        texts.append("[image]")
                    else:
                        texts.append(str(item))
                text = " ".join(texts)
            else:
                text = str(content)
            prefix = "User" if role == "user" else ("Assistant" if role == "assistant" else role.capitalize())
            parts.append(f"{prefix}: {text}")
        return "\n".join(parts)

    def _build_input_parts(self, messages: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
        """Return input as structured parts when images are present; otherwise None.

        Output shape example:
        [
          {"type": "input_text", "text": "..."},
          {"type": "input_image", "image_url": {"url": "data:..."}}
        ]
        """
        any_image = False
        texts: List[str] = []
        images: List[Dict[str, Any]] = []

        for m in self.format_messages(messages):
            content = m.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        url_obj = item.get("image_url")
                        url_val = None
                        if isinstance(url_obj, dict):
                            url_val = url_obj.get("url")
                        elif isinstance(url_obj, str):
                            url_val = url_obj
                        if url_val:
                            any_image = True
                            images.append({"type": "input_image", "image_url": {"url": url_val}})
                    elif isinstance(item, dict) and item.get("type") == "text":
                        txt = str(item.get("text", ""))
                        if txt:
                            texts.append(txt)
                    else:
                        # Unknown item type → coerce to text
                        texts.append(str(item))
            else:
                # Coerce plain string content
                if str(content):
                    texts.append(str(content))

        if not any_image:
            return None

        parts: List[Dict[str, Any]] = []
        if texts:
            parts.append({"type": "input_text", "text": "\n".join(texts)})
        parts.extend(images)
        return parts

    # def _build_input_payload(
    #     self,
    #     messages: List[Dict[str, Any]],
    #     *,
    #     max_tokens: Optional[int],
    #     temperature: float,
    #     reasoning: Optional[Dict[str, Any]],
    # ) -> Dict[str, Any]:
    #     """Construct a payload using Responses API "input" and "instructions" fields.

    #     - System message (first) becomes "instructions"
    #     - Entire transcript becomes a single input_text for continuity
    #     - Image parts from the most recent user message are appended as input_image
    #     """
    #     system_text = ""
    #     other_messages: List[Dict[str, Any]] = []
    #     for m in messages:
    #         if m.get("role") == "system" and not system_text:
    #             system_text = str(m.get("content", ""))
    #         else:
    #             other_messages.append(m)

    #     # Flatten transcript to text
    #     transcript_parts: List[str] = []
    #     for m in other_messages:
    #         role = m.get("role", "user")
    #         content = m.get("content", "")
    #         if isinstance(content, list):
    #             texts: List[str] = []
    #             for part in content:
    #                 if isinstance(part, dict) and part.get("type") == "text":
    #                     texts.append(str(part.get("text", "")))
    #                 elif isinstance(part, dict) and part.get("type") == "image_url":
    #                     texts.append("[image]")
    #                 else:
    #                     texts.append(str(part))
    #             content_text = " ".join(texts)
    #         else:
    #             content_text = str(content)
    #         prefix = "User" if role == "user" else ("Assistant" if role == "assistant" else role.capitalize())
    #         transcript_parts.append(f"{prefix}: {content_text}")

    #     input_items: List[Dict[str, Any]] = [{"type": "input_text", "text": "\n".join(transcript_parts)}]

    #     # Append images from the last user message (if any) as input_image
    #     last_user = None
    #     for m in reversed(other_messages):
    #         if m.get("role") == "user":
    #             last_user = m
    #             break
    #     if last_user and isinstance(last_user.get("content"), list):
    #         for part in last_user["content"]:
    #             if isinstance(part, dict) and part.get("type") == "image_url":
    #                 url_obj = part.get("image_url")
    #                 url = None
    #                 if isinstance(url_obj, dict) and "url" in url_obj:
    #                     url = url_obj["url"]
    #                 if url:
    #                     input_items.append({"type": "input_image", "image_url": url})

    #     payload: Dict[str, Any] = {
    #         "model": self.model_config.model,
    #         "input": input_items,
    #         "temperature": temperature,
    #         **({"max_output_tokens": max_tokens} if max_tokens else {}),
    #     }
    #     if system_text:
    #         payload["instructions"] = system_text
    #     if reasoning:
    #         payload["reasoning"] = reasoning
    #     return payload


