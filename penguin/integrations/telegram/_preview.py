"""Per-turn Telegram typing and streaming preview lifecycle."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from penguin.integrations.telegram._helpers import message_id
from penguin.integrations.telegram.formatting import StreamingCoalescer, html_chunks

if TYPE_CHECKING:
    from penguin.channels.schema import InboundEnvelope

logger = logging.getLogger(__name__)


class Preview:
    """Per-turn typing/progress task; stream callbacks only mutate memory."""

    def __init__(self, manager: Any, envelope: InboundEnvelope) -> None:
        self.manager = manager
        self.envelope = envelope
        self.coalescer = StreamingCoalescer(
            interval_seconds=manager.config.edit_interval_ms / 1000
        )
        self.message_id: str | None = None
        self._event = asyncio.Event()
        self._closed = asyncio.Event()
        self._tasks: list[asyncio.Task[Any]] = []

    async def start(self) -> None:
        self._tasks.append(asyncio.create_task(self._typing_loop()))
        if self.manager.config.streaming_mode == "progress":
            await self._send_or_edit("Penguin is working…")
        if self.manager.config.streaming_mode in {"edit", "progress"}:
            self._tasks.append(asyncio.create_task(self._preview_loop()))

    async def push(self, chunk: str, message_type: str = "assistant") -> None:
        if message_type == "reasoning" and not self.manager.config.include_reasoning:
            return
        if chunk:
            self.coalescer.push(chunk)
            self._event.set()

    async def finish(self) -> str | None:
        self._closed.set()
        self._event.set()
        for task in self._tasks:
            if task.get_name() == "telegram-typing":
                task.cancel()
        await asyncio.sleep(0)
        return self.message_id

    async def close(self) -> None:
        self._closed.set()
        self._event.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _typing_loop(self) -> None:
        asyncio.current_task().set_name("telegram-typing")
        while not self._closed.is_set():
            kwargs: dict[str, Any] = {
                "chat_id": self.envelope.address.chat_id,
                "action": "typing",
            }
            if self.envelope.address.topic_id:
                kwargs["message_thread_id"] = int(self.envelope.address.topic_id)
            with suppress(Exception):
                await self.manager._api_call(
                    self.manager.bot.send_chat_action(**kwargs)
                )
            try:
                await asyncio.wait_for(self._closed.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                continue

    async def _preview_loop(self) -> None:
        mode = self.manager.config.streaming_mode
        while not self._closed.is_set():
            try:
                await asyncio.wait_for(
                    self._event.wait(),
                    timeout=self.manager.config.edit_interval_ms / 1000,
                )
            except asyncio.TimeoutError:
                pass
            self._event.clear()
            if mode != "edit":
                continue
            preview = self.coalescer.take(time.monotonic())
            if preview:
                await self._send_or_edit(preview)

    async def _send_or_edit(self, text: str) -> None:
        chunks = html_chunks(text)
        rendered = chunks[-1] if chunks else "…"
        try:
            if self.message_id:
                await self.manager._api_call(
                    self.manager.bot.edit_message_text(
                        chat_id=self.envelope.address.chat_id,
                        message_id=int(self.message_id),
                        text=rendered,
                        parse_mode="HTML",
                    )
                )
                return
            kwargs: dict[str, Any] = {
                "chat_id": self.envelope.address.chat_id,
                "text": rendered,
                "parse_mode": "HTML",
            }
            if self.envelope.address.topic_id:
                kwargs["message_thread_id"] = int(self.envelope.address.topic_id)
            message = await self.manager._api_call(
                self.manager.bot.send_message(**kwargs)
            )
            self.message_id = message_id(message)
        except Exception:
            logger.debug("Telegram preview update failed", exc_info=True)
